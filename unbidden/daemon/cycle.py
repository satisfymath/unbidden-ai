"""The job graph. Each handler does one step and queues the next; every step is idempotent."""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, Proposal, ProposalStatus, Verdict
from unbidden.contracts.jobs import Job
from unbidden.contracts.opportunity import ActionKind, Decision, Opportunity, OpportunityStatus
from unbidden.director.decide import Context, decide
from unbidden.director.learn import Belief, beliefs, kind_of
from unbidden.lab.fixlab import FixLab
from unbidden.observe.ci import ci_commands
from unbidden.observe.scan import scan
from unbidden.observe.stack import Stack
from unbidden.publish.github import NeedsApproval, Publisher, PublishError
from unbidden.publish.proposal import prepare
from unbidden.runtime import Runtime
from unbidden.sandbox.provision import DependencyImage
from unbidden.workspace import head_sha

Handler = Callable[[Job], Awaitable[None]]
Log = Callable[[str], None]
EXPERIMENTS_PER_SWEEP = 3
# How long a commit's CI verdict is reused: a finished one for an hour (a re-run can still change it); "no checks" for
# ten minutes (checks may not have been created yet); anything else not at all.
CI_TTL_S: dict[str | None, float] = {"green": 3600.0, "red": 3600.0, None: 600.0}

# Lower runs first: follow-ups on GitHub, then publishing, then observing, then the slow lab.
PRIORITY = {
    "observe.live": 5,
    "ops.deploy": 8,
    "research.investigate": 15,
    "research.probe": 65,
    "github.poll": 10,
    "github.publish": 20,
    "proposal.prepare": 30,
    "observe.head": 40,
    "observe.scan": 50,
    "director.sweep": 60,
    "lab.experiment": 70,
    "forge.build": 55,
    "world.refresh": 45,
    "connect.survey": 42,
    "goal.pursue": 58,
}


def job(type_: str, key: str, payload: dict[str, Any] | None = None, *, correlation_id: str | None = None) -> Job:
    return Job(
        type=type_,
        idempotency_key=f"{type_}:{key}",
        payload=payload or {},
        priority=PRIORITY[type_],
        correlation_id=correlation_id,
    )


@dataclass
class Cycle:
    runtime: Runtime
    log: Log = print
    _stacks: dict[str, tuple[Stack, dict[str, DependencyImage]]] = field(default_factory=dict)
    _ci: dict[str, tuple[str | None, dict[str, str], set[str], float]] = field(default_factory=dict)

    @property
    def store(self):
        return self.runtime.store

    def handlers(self) -> dict[str, Handler]:
        return {
            "observe.head": self.observe_head,
            "observe.scan": self.observe_scan,
            "director.sweep": self.director_sweep,
            "lab.experiment": self.lab_experiment,
            "proposal.prepare": self.proposal_prepare,
            "github.publish": self.github_publish,
            "github.poll": self.github_poll,
            "observe.live": self.observe_live,
            "ops.deploy": self.ops_deploy,
            "research.investigate": self.research_investigate,
            "research.probe": self.research_probe,
            "forge.build": self.forge_build,
            "world.refresh": self.world_refresh,
            "connect.survey": self.connect_survey,
            "goal.pursue": self.goal_pursue,
        }

    def _env(self, rev: str) -> tuple[Stack, dict[str, DependencyImage]]:
        if rev not in self._stacks:
            self._stacks[rev] = self.runtime.stack_and_images(rev)
        return self._stacks[rev]

    # Steps ---------------------------------------------------------------------------------------------

    async def observe_head(self, _: Job) -> None:
        repo = self.runtime.workspace.repo
        head = head_sha(repo)
        last = self.store.get_value("head")
        if head == last:
            return
        self.store.set_value("head", head)
        self.store.append_event(Event(type=EventType.HEAD_MOVED, actor="observer", payload={"from": last, "to": head}))
        self.log(f"HEAD is {head[:12]}")
        self.store.enqueue(job("observe.scan", head, {"rev": head}))

    async def observe_scan(self, j: Job) -> None:
        rev = j.payload["rev"]
        result = await asyncio.to_thread(
            scan, self.runtime.workspace.repo, rev, self.store, self.runtime.workspace.mandate(), progress=self.log
        )
        opened = sum(len(s.opened) for s in result.sweeps)
        self.log(f"scan of {rev[:12]}: {len(result.reports)} reports, {opened} new opportunities")
        from unbidden.world.discover import discover

        world = await discover(
            self.runtime.workspace.repo, rev, self.store, self.runtime.workspace.mandate(), self.runtime.brain
        )
        self.log(f"map of {rev[:12]}: {len(world.resources)} resources, {len(world.blind_spots)} blind spots")
        self._plan_probe(rev, result.stack)
        self.store.enqueue(job("director.sweep", f"{rev}:{utc_now():%Y%m%d%H%M}"))

    async def world_refresh(self, _: Job) -> None:
        """The running system, mapped again without waiting for a commit: data grows, a migration is applied, a
        database comes back. No model call: what the local model inferred is carried until the code changes."""
        from unbidden.world.discover import discover

        head = self.store.get_value("head")
        if head is None:
            return
        world = await discover(self.runtime.workspace.repo, head, self.store, self.runtime.workspace.mandate(), None)
        self.log(f"map refreshed: {len(world.resources)} resources, {len(world.blind_spots)} blind spots")

    def _plan_probe(self, rev: str, stack: Stack) -> None:
        """Whether to look for crashes nobody reported: once per commit, in the package with the most public surface,
        when the mandate allows experiments. The decision is recorded either way, with its reason."""
        from unbidden.contracts.guardian import ActionRequest
        from unbidden.guardian.policy import PolicyEngine
        from unbidden.research.robustness import probe_targets

        if stack.python is None:
            return
        allowed = PolicyEngine(self.runtime.workspace.mandate()).evaluate(
            ActionRequest(capability="sandbox.run", purpose="robustness probe")
        )
        targets = probe_targets(self.runtime.workspace.repo, rev, stack.python)
        if not allowed.allowed:
            chosen, reason = "decline", "; ".join(allowed.reasons)
        elif not targets:
            chosen, reason = "decline", "no importable package with public functions under the source roots"
        else:
            chosen, reason = "investigate", f"probe {targets[0][0]} ({targets[0][1]} public functions sampled)"
        self.store.append_event(
            Event(
                type=EventType.DECISION_MADE,
                actor="director",
                payload={"chosen": chosen, "reason": reason, "kind": "robustness_probe", "rev": rev,
                         "targets": targets[:5]},
            )
        )  # fmt: skip
        self.log(f"robustness probe at {rev[:12]}: {chosen} ({reason})")
        if chosen == "investigate":
            package = targets[0][0]
            self.store.enqueue(job("research.probe", f"{rev}:{package}", {"rev": rev, "package": package}))

    async def research_probe(self, j: Job) -> None:
        from unbidden.research.robustness import RobustnessProbe, parse_crashes, probe_package, property_violations

        rev, package = j.payload["rev"], j.payload["package"]
        if rev != self.store.get_value("head"):
            return
        record: dict[str, object] = {"rev": rev, "package": package, "ran": False}
        try:
            _, images = await asyncio.to_thread(self._env, rev)
        except Exception as exc:
            self.store.set_value("last_probe", {**record, "why": f"environment: {str(exc)[:300]}"})
            raise
        if "python" not in images:
            self.store.set_value("last_probe", {**record, "why": "no Python image could be built"})
            self.log(f"robustness probe of {package}: no Python image could be built")
            return
        probe = RobustnessProbe(self.runtime.workspace.repo, self.store, self.runtime.brain, images["python"])
        outcome = await probe_package(
            probe,
            rev,
            package,
            run=lambda r, tests: asyncio.to_thread(probe.run_tests, r, tests),
            progress=self.log,
        )
        artifacts = self.runtime.workspace.dir / "artifacts"
        artifacts.mkdir(exist_ok=True)
        (artifacts / f"robustness-{rev[:12]}.answer.md").write_text(probe.last_answer)
        if outcome is None:
            self.store.set_value("last_probe", {**record, "why": "no usable tests were written"})
            self.log(f"robustness probe of {package}: no usable tests were written")
            return
        tests, output = outcome
        (artifacts / f"robustness-{rev[:12]}.py").write_text(tests)
        (artifacts / f"robustness-{rev[:12]}.log").write_text(output)
        crashes = parse_crashes(output, package)
        opened = probe.record(rev, package, tests, crashes)
        kept = property_violations(output)
        summary = next((ln for ln in reversed(output.splitlines()) if " passed" in ln or " failed" in ln), None)
        self.store.set_value(
            "last_probe",
            {**record, "ran": summary is not None, "summary": summary or output[-300:], "crashes": len(crashes),
             "opened": len(opened), "violations": len(kept)},
        )  # fmt: skip
        if summary is None:
            self.log(f"robustness probe of {package}: the tests did not run ({output.strip().splitlines()[-1:]})")
        else:
            self.log(
                f"robustness probe of {package}: {summary.strip()}; {len(crashes)} crash(es), {len(opened)} new; "
                f"{len(kept)} property violation(s) kept for a person (L1)"
            )
        if opened:
            self.store.enqueue(job("director.sweep", f"probe:{j.id}"))

    async def director_sweep(self, _: Job) -> None:
        self._queue_needs()
        mandate = self.runtime.workspace.mandate()
        open_prs = len(self.store.list("proposals", Proposal, status=ProposalStatus.PR_OPENED.value))
        checked = self._checked_dirs()
        head = self.store.get_value("head")
        commands = ci_commands(self.runtime.workspace.repo, head) if head else ""
        ci_status, per_tool, ci_problem = self._ci_verdicts(head, mandate)
        queued = 0
        live = (OpportunityStatus.OPEN, OpportunityStatus.EXPERIMENTING, OpportunityStatus.PROPOSED)
        unpublished = {
            p.opportunity_id: p for p in self.store.list("proposals", Proposal, status=ProposalStatus.READY.value)
        }
        opps = [
            o
            for o in self.store.list("opportunities", Opportunity)
            if o.status in live and (o.status is not OpportunityStatus.PROPOSED or o.id in unpublished)
        ]
        opps.sort(key=lambda o: (-o.evidence_level, o.created_at))
        learned = beliefs(self.store)
        from unbidden.contracts.capability import CapabilityNeed
        from unbidden.forge.needs import COLLECTION as NEEDS

        needs = {n.source: n.status.value for n in self.store.list(NEEDS, CapabilityNeed)}
        decided: list[tuple[Opportunity, Decision, int]] = []
        for opp in opps:
            attempts = int(opp.details.get("attempts", 0))
            decision = decide(
                opp,
                mandate,
                Context(
                    open_pull_requests=open_prs,
                    attempts=attempts,
                    checked_dirs=checked,
                    ci_commands=commands,
                    ci_status=ci_status,
                    tool_status=per_tool,
                    ci_problem=ci_problem,
                    p_experiment=learned.get(kind_of(opp), Belief(0, 0)).mean,
                    capability_needs=needs,
                ),
            )
            if decision.chosen is ActionKind.PROPOSE_CHANGE:
                open_prs += 1  # the next opportunity sees the pull request this one will open
            decided.append((opp, decision, attempts))
        # One budget for the whole sweep: experiments go to the highest expected net value first, not the oldest.
        decided.sort(key=lambda d: -_chosen_utility(d[1]) if d[1].chosen is ActionKind.RUN_EXPERIMENT else 0.0)
        for opp, decision, attempts in decided:
            last: dict[str, Any] = opp.details.get("decision", {})
            seen = (last.get("chosen"), last.get("level"), last.get("attempts"))
            if seen != (decision.chosen.value, int(opp.evidence_level), attempts):
                # One recorded decision per opportunity, evidence level and attempt; acting on it is retried
                # every sweep, safely, because every job is queued under an idempotency key.
                self._record_decision(opp, decision)
            if decision.chosen is ActionKind.RUN_EXPERIMENT and queued < EXPERIMENTS_PER_SWEEP:
                # One experiment per attempt at each commit (a lab blocked at one commit runs again at the next) and
                # per reopening: a reopened opportunity's attempts start again under a new key.
                rev, reopened = str(opp.details.get("rev", ""))[:12], int(opp.details.get("reopened", 0))
                if self.store.enqueue(
                    job(
                        "lab.experiment",
                        f"{opp.id}:{rev}:r{reopened}:{attempts}",
                        {"id": opp.id},
                        correlation_id=opp.id,
                    )
                ):
                    queued += 1
            elif decision.chosen is ActionKind.PROPOSE_CHANGE:
                ready = unpublished.get(opp.id)
                if ready is None:
                    self.store.enqueue(job("proposal.prepare", opp.id, {"id": opp.id}, correlation_id=opp.id))
                else:
                    # Prepared earlier and still unpublished: try again now (the mandate may allow it now).
                    self.store.enqueue(
                        job(
                            "github.publish",
                            f"{ready.id}:{self.store.get_value('head')}",
                            {"id": ready.id},
                            correlation_id=opp.id,
                        )
                    )
            elif decision.chosen in (ActionKind.MEASURE, ActionKind.ACQUIRE_CAPABILITY, ActionKind.INVESTIGATE):
                self._before_experiment(opp, decision.chosen)
            elif decision.chosen is ActionKind.DECLINE:
                opp.status = OpportunityStatus.DECLINED
                self.store.put("opportunities", opp)
                withdrawn = unpublished.get(opp.id)
                if withdrawn is not None:
                    withdrawn.status = ProposalStatus.REJECTED
                    self.store.put("proposals", withdrawn)
                    self.log(f"{opp.id}: proposal withdrawn before publishing ({decision.reason})")

    def _before_experiment(self, opp: Opportunity, kind: ActionKind) -> None:
        """Carry out MEASURE, ACQUIRE_CAPABILITY or INVESTIGATE through the jobs that already do each (PLAN.md, PR12):
        a map refresh, a Forge build, an investigation. Each is counted on the opportunity so it cannot repeat."""
        rev = str(opp.details.get("rev", ""))
        if kind is ActionKind.MEASURE:
            measure = opp.details.get("measure") or {}
            asked = int(measure.get("asked", 0)) if measure.get("rev") == rev else 0
            if self.store.enqueue(job("world.refresh", f"measure:{opp.id}:{rev[:12]}:{asked}")):
                opp.details = {**opp.details, "measure": {"rev": rev, "asked": asked + 1}}
                self.store.put("opportunities", opp)
        elif kind is ActionKind.ACQUIRE_CAPABILITY:
            from unbidden.contracts.capability import CapabilityNeed
            from unbidden.forge.needs import COLLECTION as NEEDS

            source = f"compose:{opp.details.get('service')}"
            for need in self.store.list(NEEDS, CapabilityNeed):
                wake = {"type": "director.sweep", "key": f"need:{opp.id}"}
                if need.source == source and wake not in need.resume:
                    need.resume = [*need.resume, wake]  # in use, the need queues the sweep that decides this again
                    self.store.put(NEEDS, need)
            self._queue_needs()
        elif kind is ActionKind.INVESTIGATE:
            incident = opp.details.get("incident") or {}
            reopened = int(opp.details.get("reopened", 0))
            if self.store.enqueue(
                job("research.investigate", f"{opp.id}:r{reopened}", incident, correlation_id=opp.id)
            ):
                opp.details = {**opp.details, "investigations": int(opp.details.get("investigations", 0)) + 1}
                self.store.put("opportunities", opp)

    def _ci_verdicts(self, head: str | None, mandate: Any) -> tuple[str | None, dict[str, str], str | None]:
        """The team's CI on HEAD, read once per commit (the sweep runs often; GitHub limits unauthenticated reads)."""
        from unbidden.contracts.guardian import ActionRequest
        from unbidden.guardian.credentials import broker
        from unbidden.guardian.policy import PolicyEngine
        from unbidden.observe.ci import analyzer_tool, ci_verdicts

        slug = mandate.egress.github.repository
        if not head or not slug:
            return None, {}, None
        if not PolicyEngine(mandate).evaluate(ActionRequest(capability="github.read", purpose="CI status")).allowed:
            return None, {}, None
        tools = {analyzer_tool(o.details) for o in self.store.list("opportunities", Opportunity)}
        cached = self._ci.get(head)
        fresh = cached is not None and time.monotonic() < cached[3] and tools <= cached[2]
        if not fresh:
            token = broker().get(mandate.egress.github.token_env, "github")
            status, per_tool, problem = ci_verdicts(self.runtime.workspace.repo, head, slug, token, tools)
            ttl = CI_TTL_S.get(status, 0.0)  # a running, unknown or unreadable CI is asked again next sweep
            if not ttl:
                return status, per_tool, problem
            cached = (status, per_tool, tools, time.monotonic() + ttl)
            self._ci[head] = cached
        assert cached is not None
        return cached[0], cached[1], None

    def _checked_dirs(self) -> tuple[str, ...]:
        head = self.store.get_value("head")
        return checked_dirs(self.runtime.workspace.repo, head) if head else ()

    def _record_decision(self, opp: Opportunity, decision: Decision) -> None:
        self.store.put("decisions", decision)
        opp.details = {
            **opp.details,
            "decision": {
                "id": decision.id,
                "chosen": decision.chosen.value,
                "level": int(opp.evidence_level),
                "attempts": int(opp.details.get("attempts", 0)),
                "reason": decision.reason,
            },
        }
        self.store.put("opportunities", opp)
        self.store.append_event(
            Event(
                type=EventType.DECISION_MADE,
                actor="director",
                entity_id=decision.id,
                correlation_id=opp.id,
                payload={
                    "chosen": decision.chosen.value,
                    "reason": decision.reason,
                    "candidates": [{"kind": c.kind.value, "utility": round(c.utility, 3)} for c in decision.candidates],
                },
            )
        )
        self.log(f"{opp.id}: {decision.chosen.value} ({decision.reason})")

    async def lab_experiment(self, j: Job) -> None:
        opp = self.store.get("opportunities", j.payload["id"], Opportunity)
        if opp is None or opp.status is not OpportunityStatus.OPEN:
            return
        if opp.details.get("rev") != self.store.get_value("head"):
            # Measured just in time: findings of an older commit are re-observed before any lab run.
            return
        stack, images = await asyncio.to_thread(self._env, opp.details["rev"])
        if opp.source == "robustness":
            from unbidden.lab.robust import RobustLab

            result = await RobustLab(
                self.runtime.workspace.repo, self.store, self.runtime.brain, stack, images["python"], progress=self.log
            ).run(opp)
        elif opp.category == "performance":
            from unbidden.lab.perf import PerfLab

            perf = PerfLab(
                self.runtime.workspace.repo, self.runtime.brain, self.store, stack, images, progress=self.log
            )
            result = await perf.run(opp)
        else:
            lab = FixLab(
                self.runtime.workspace.repo,
                self.store,
                self.runtime.brain,
                stack,
                images,
                progress=self.log,
                bridge=self.runtime.bridge(),
            )
            result = await lab.run(opp)
        opp = self.store.get("opportunities", opp.id, Opportunity) or opp
        blocked = getattr(result, "blocked", None)
        if blocked:
            # Nothing ran: what is missing is Unbidden's, not evidence against the opportunity.
            opp.details = {**opp.details, "blocked": {"rev": opp.details.get("rev"), "why": blocked}}
            self.store.put("opportunities", opp)
            self.log(f"{opp.id}: not measured ({blocked})")
        elif result.verdict is not None and result.verdict.improved:
            self.log(f"{opp.id}: improved, evidence L{int(opp.evidence_level)}")
        else:
            opp.details = {**opp.details, "attempts": int(opp.details.get("attempts", 0)) + 1}
            self.store.put("opportunities", opp)
            self.log(f"{opp.id}: no proven fix ({'; '.join(result.notes[-1:])})")
        self.store.enqueue(job("director.sweep", f"after:{j.id}"))

    async def proposal_prepare(self, j: Job) -> None:
        opp = self.store.get("opportunities", j.payload["id"], Opportunity)
        if opp is None or opp.status is OpportunityStatus.PROPOSED:
            return
        experiment = self.store.get("experiments", opp.details["experiment_id"], Experiment)
        if experiment is None:
            return
        verdict = Verdict.model_validate(opp.details["verdict"])
        proposal = prepare(self.runtime.workspace.repo, self.store, opp, experiment, verdict)
        self.log(f"{opp.id}: branch {proposal.branch} ready")
        self.store.enqueue(job("github.publish", proposal.id, {"id": proposal.id}, correlation_id=opp.id))

    async def github_publish(self, j: Job) -> None:
        proposal = self.store.get("proposals", j.payload["id"], Proposal)
        if proposal is None:
            return
        patch_path = self.runtime.workspace.dir / "artifacts" / f"{proposal.experiment_id}.patch"
        patch = patch_path.read_text() if patch_path.exists() else ""
        publisher = Publisher(self.runtime.workspace.repo, self.store, self.runtime.workspace.mandate())
        try:
            proposal = await asyncio.to_thread(publisher.publish, proposal, patch)
            self.log(f"pull request opened: {proposal.pr.url if proposal.pr else '?'}")
        except NeedsApproval as exc:
            self.log(f"{proposal.opportunity_id}: waiting for a person: {exc}")
        except PublishError as exc:
            self.log(f"{proposal.opportunity_id}: not published: {exc}")

    async def observe_live(self, _: Job) -> None:
        from unbidden.contracts.world import WorldModel
        from unbidden.observe.live import LiveWatcher

        world = self.store.get("world", "world", WorldModel)
        if world is None or not world.of_kind("endpoint"):
            return
        watcher = LiveWatcher(
            self.runtime.workspace.repo, self.store, self.runtime.workspace.mandate(), world, self.log
        )
        await asyncio.to_thread(watcher.tick)

    async def research_investigate(self, j: Job) -> None:
        from unbidden.research.investigate import Investigation

        investigation = Investigation(
            self.runtime.workspace.repo,
            self.runtime.brain,
            self.store,
            self.runtime.workspace.mandate(),
            j.payload["good"],
            j.payload["bad"],
            j.payload["incident"],
            j.payload["subject"],
            log=self.log,
        )
        hypothesis = await investigation.run()
        if hypothesis is not None:
            self.log(
                f"hypothesis ({hypothesis.mechanism}, confidence {hypothesis.confidence:.2f}): {hypothesis.statement}"
            )

    def _queue_needs(self) -> None:
        """Each capability need the cycle can still build, once per attempt."""
        from unbidden.contracts.capability import CapabilityNeed
        from unbidden.forge.needs import COLLECTION, buildable

        for need in self.store.list(COLLECTION, CapabilityNeed):
            if buildable(need):
                self.store.enqueue(job("forge.build", f"{need.id}:{need.attempts}:{need.unblocked}", {"id": need.id}))

    async def forge_build(self, j: Job) -> None:
        """Fill a capability need: read the source, build with Forge, judge with its oracle, admit by the mandate."""
        from unbidden.contracts.capability import CapabilityNeed
        from unbidden.forge import needs, stats_build
        from unbidden.forge.build import Forge, compose_logs

        need = self.store.get(needs.COLLECTION, j.payload["id"], CapabilityNeed)
        if need is None:
            return
        # Local model only: remote help (the privacy bridge) spends credit, and stays a person's `forge build`.
        repo, brain = self.runtime.workspace.repo, self.runtime.brain

        def read(kind: str, source: str) -> list[str]:
            if kind in ("api_client", "api_extension"):
                return [source]  # an integration is built from the connection's documentation, read by Forge
            if kind == "stats_reader":
                return stats_build.fetch(source)
            return compose_logs(repo, source.removeprefix("compose:"))

        async def forge(n: CapabilityNeed, lines: list[str]) -> tuple[str | None, str, list[str]]:
            if n.kind == "api_extension":
                from unbidden.connect.registry import get
                from unbidden.forge import integrate

                conn = get(self.store, n.source.split("#", 1)[0])
                if conn is None:
                    return None, "failed", [f"no connection {n.source}"]
                mandate = self.runtime.workspace.mandate()
                extended, decision, notes = await integrate.extend(self.store, mandate, conn, n.operations)
                return (extended.id if extended else None), decision, notes
            if n.kind == "api_client":
                from unbidden.connect.registry import get
                from unbidden.forge import integrate

                conn = get(self.store, n.source)
                if conn is None:
                    return None, "failed", [f"no connection {n.source}"]
                built, decision, notes = await integrate.build(
                    brain, self.store, self.runtime.workspace.mandate(), conn
                )
                return (built.id if built else None), decision, notes
            if n.kind == "stats_reader":
                built = await stats_build.build(brain, self.store, n.source, lines, permissions=n.permissions)
                return (built.adapter.id if built.adapter else None), built.decision, built.notes
            result = await Forge(brain, self.store, remote=False).build_log_adapter(n.source, lines)
            return (
                (result.adapter.id if result.adapter else None),
                "built" if result.adapter else "failed",
                result.notes,
            )

        need = await needs.build(self.store, self.runtime.workspace.mandate(), need, read, forge)
        self.log(f"capability need {need.kind} for {need.source}: {need.status.value}")
        if need.kind in ("api_client", "api_extension") and need.capability_id:
            self._attach(need.source.split("#", 1)[0], need.capability_id)

    def _attach(self, connection: str, capability_id: str) -> None:
        """The connection is used through its integration from now on: checked through it, at once."""
        from unbidden.connect.kinds import connectors
        from unbidden.connect.registry import get, record, survey
        from unbidden.contracts.world import WorldModel

        conn = get(self.store, connection)
        if conn is None:
            return
        conn.capability_id = capability_id
        record(self.store, conn, reason=f"integration {capability_id} attached")
        world = self.store.get("world", "world", WorldModel)
        survey(self.runtime.workspace.repo, self.store, self.runtime.workspace.mandate(), world, connectors())

    async def connect_survey(self, _: Job) -> None:
        """The project's connections checked again; deploy procedures found proposed; each goal pursued."""
        from unbidden.connect.kinds import connectors
        from unbidden.connect.mapping import add_to_world
        from unbidden.connect.registry import survey
        from unbidden.contracts.world import WorldModel
        from unbidden.operate.actions import propose_procedure

        repo, mandate = self.runtime.workspace.repo, self.runtime.workspace.mandate()
        world = self.store.get("world", "world", WorldModel)
        found = await asyncio.to_thread(survey, repo, self.store, mandate, world, connectors())
        add_to_world(self.store, repo, found)
        for proposal in propose_procedure(self.store, repo):
            self.log(f"deploy procedure found, proposed only: {proposal.operation}")
        states = ", ".join(f"{c.id} {c.state.value}" for c in found if c.grant)
        self.log(f"connections: {states}")
        # A goal is pursued again each hour, and as soon as what it can use changes (a connection revoked, restored,
        # given an integration) or what is deployed changes (a page shows what the deployed commit renders): the
        # same state in the same hour is not pursued twice.
        import hashlib

        from unbidden.workspace import head_sha

        hour = f"{utc_now():%Y%m%d%H}"
        usable = sorted(f"{c.id}={c.state.value}/{c.capability_id}" for c in found if c.grant)
        usable.append(f"deployed={head_sha(repo)}")
        signature = hashlib.sha256("|".join(usable).encode()).hexdigest()[:8]
        for goal in mandate.goals:
            self.store.enqueue(job("goal.pursue", f"{goal.id}:{hour}:{signature}", {"goal": goal.id}))

    async def goal_pursue(self, j: Job) -> None:
        from unbidden.director.goals import pursue

        mandate = self.runtime.workspace.mandate()
        goal = next((g for g in mandate.goals if g.id == j.payload["goal"]), None)
        if goal is None:
            return
        run = await pursue(
            self.runtime.brain, self.store, mandate, goal, window=f"{utc_now():%Y-%m-%d}",
            workspace=self.runtime.workspace,
        )  # fmt: skip
        self.log(f"goal {goal.id}: {run.status}: {run.notes[-1] if run.notes else ''}")
        if run.status in ("waiting_capability", "waiting_extension"):
            self._queue_needs()

    async def ops_deploy(self, j: Job) -> None:
        """Deploy what was merged: fast-forward the deployment checkout to the remote base, then the team's steps."""
        from unbidden.operate.deploy import OperationRefused, deploy, merged_evidence

        repo = self.runtime.workspace.repo
        mandate = self.runtime.workspace.mandate()
        base = mandate.egress.github.base_branch
        await asyncio.to_thread(subprocess.run, ["git", "-C", str(repo), "fetch", "-q", "origin", base], check=False)
        target = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", f"origin/{base}"], capture_output=True, text=True, check=False
        ).stdout.strip()
        try:
            merged_evidence(repo, self.store, j.payload.get("proposal"), target)
            result = await asyncio.to_thread(
                deploy, repo, self.store, mandate, target, reason=j.payload.get("reason", "merged")
            )
        except OperationRefused as exc:
            self.log(f"deploy refused: {exc}")
            return
        self.log(f"deployed {target[:12]}: {'ok' if result.ok else 'FAILED'}")

    async def github_poll(self, _: Job) -> None:
        opened = self.store.list("proposals", Proposal, status=ProposalStatus.PR_OPENED.value)
        if not opened:
            return
        publisher = Publisher(self.runtime.workspace.repo, self.store, self.runtime.workspace.mandate())
        for proposal in opened:
            try:
                updated = await asyncio.to_thread(publisher.poll, proposal)
            except PublishError as exc:
                self.log(f"poll of {proposal.id} failed: {exc}")
                continue
            if updated.status is not ProposalStatus.PR_OPENED:
                self.log(f"{proposal.pr.url if proposal.pr else proposal.id}: {updated.status.value}")
                continue
            mandate = self.runtime.workspace.mandate()
            if mandate.autonomy.merge_pull_requests.value != "allow":
                continue
            try:
                merged = await asyncio.to_thread(publisher.merge, updated)
            except PublishError as exc:
                self.log(f"not merged: {exc}")
                continue
            except Exception as exc:  # refused by Guardian, a hold or the hourly limit
                self.log(f"not merged: {exc}")
                continue
            self.log(f"merged {merged.pr.url if merged.pr else merged.id}")
            if mandate.autonomy.deploy.value == "allow":
                self.store.enqueue(
                    job("ops.deploy", merged.id, {"reason": f"merged {merged.title}", "proposal": merged.id})
                )


def _chosen_utility(decision: Decision) -> float:
    return max((c.utility for c in decision.candidates if c.kind is decision.chosen), default=0.0)


def checked_dirs(repo: Path, head: str) -> tuple[str, ...]:
    """Where the team's CI checks code: the packages it lints, or the directories its test steps run in."""
    import json as _json

    from unbidden.observe.ci import ci_lint_packages, ci_test_plan
    from unbidden.observe.stack import detect_stack

    stack = detect_stack(repo, head)
    if stack.node is not None and stack.node.packages:
        root = subprocess.run(["git", "-C", str(repo), "show", f"{head}:package.json"], capture_output=True, text=True)
        scripts = _json.loads(root.stdout or "{}").get("scripts", {}) if root.returncode == 0 else {}
        names = {p.name: p.path for p in stack.node.packages}
        linted = ci_lint_packages(repo, head, names, scripts)
        if linted is not None:
            return tuple(sorted(linted))
    dirs: list[str] = []
    for language in ("python", "node"):
        plan = ci_test_plan(repo, head, language)
        if plan is not None:
            dirs += [s.cwd or "." for s in plan.steps]
    return tuple(dict.fromkeys(dirs))


RETRY = timedelta(minutes=2)

# A job that runs past its limit is cancelled and retried later, so one hung call never stops the worker. Lab work
# (builds, test rounds on both sides) is long by nature; everything else should be quick.
TIMEOUT_S: dict[str, float] = {
    "lab.experiment": 3 * 3600,
    "observe.scan": 3600,
    "proposal.prepare": 1800,
    "ops.deploy": 2400,
    "research.investigate": 900,
    "research.probe": 3600,
    "forge.build": 1800,
    "goal.pursue": 1800,
}
DEFAULT_TIMEOUT_S = 600.0


def timeout_for(job_type: str) -> float:
    return TIMEOUT_S.get(job_type, DEFAULT_TIMEOUT_S)


def retry_after(attempts: int) -> timedelta:
    """2, 4, 8 ... minutes, at most an hour: a failing dependency is not hammered."""
    return min(RETRY * (2 ** max(0, attempts - 1)), timedelta(hours=1))
