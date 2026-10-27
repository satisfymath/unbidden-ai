"""The job graph. Each handler does one step and queues the next; every step is idempotent."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, Proposal, ProposalStatus, Verdict
from unbidden.contracts.jobs import Job
from unbidden.contracts.opportunity import ActionKind, Decision, Opportunity, OpportunityStatus
from unbidden.director.decide import Context, decide
from unbidden.lab.fixlab import FixLab
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

# Lower runs first: follow-ups on GitHub, then publishing, then observing, then the slow lab.
PRIORITY = {
    "observe.live": 5,
    "ops.deploy": 8,
    "research.investigate": 15,
    "github.poll": 10,
    "github.publish": 20,
    "proposal.prepare": 30,
    "observe.head": 40,
    "observe.scan": 50,
    "director.sweep": 60,
    "lab.experiment": 70,
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
        self.store.enqueue(job("director.sweep", f"{rev}:{utc_now():%Y%m%d%H%M}"))

    async def director_sweep(self, _: Job) -> None:
        mandate = self.runtime.workspace.mandate()
        open_prs = len(self.store.list("proposals", Proposal, status=ProposalStatus.PR_OPENED.value))
        checked = self._checked_dirs()
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
        for opp in opps:
            attempts = int(opp.details.get("attempts", 0))
            decision = decide(
                opp, mandate, Context(open_pull_requests=open_prs, attempts=attempts, checked_dirs=checked)
            )
            last: dict[str, Any] = opp.details.get("decision", {})
            seen = (last.get("chosen"), last.get("level"), last.get("attempts"))
            if seen != (decision.chosen.value, int(opp.evidence_level), attempts):
                # One recorded decision per opportunity, evidence level and attempt; acting on it is retried
                # every sweep, safely, because every job is queued under an idempotency key.
                self._record_decision(opp, decision)
            if decision.chosen is ActionKind.RUN_EXPERIMENT and queued < EXPERIMENTS_PER_SWEEP:
                if self.store.enqueue(
                    job("lab.experiment", f"{opp.id}:{attempts}", {"id": opp.id}, correlation_id=opp.id)
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
                open_prs += 1
            elif decision.chosen is ActionKind.DECLINE:
                opp.status = OpportunityStatus.DECLINED
                self.store.put("opportunities", opp)
                withdrawn = unpublished.get(opp.id)
                if withdrawn is not None:
                    withdrawn.status = ProposalStatus.REJECTED
                    self.store.put("proposals", withdrawn)
                    self.log(f"{opp.id}: proposal withdrawn before publishing ({decision.reason})")

    def _checked_dirs(self) -> tuple[str, ...]:
        from unbidden.observe.ci import ci_test_plan

        head = self.store.get_value("head")
        if not head:
            return ()
        dirs: list[str] = []
        for language in ("python", "node"):
            plan = ci_test_plan(self.runtime.workspace.repo, head, language)
            if plan is not None:
                dirs += [s.cwd or "." for s in plan.steps]
        return tuple(dict.fromkeys(dirs))

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
        if result.verdict is not None and result.verdict.improved:
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

    async def ops_deploy(self, j: Job) -> None:
        """Deploy what was merged: fast-forward the deployment checkout to the remote base, then the team's steps."""
        from unbidden.operate.deploy import OperationRefused, deploy

        repo = self.runtime.workspace.repo
        mandate = self.runtime.workspace.mandate()
        base = mandate.egress.github.base_branch
        await asyncio.to_thread(subprocess.run, ["git", "-C", str(repo), "fetch", "-q", "origin", base], check=False)
        target = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", f"origin/{base}"], capture_output=True, text=True, check=False
        ).stdout.strip()
        try:
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
                self.store.enqueue(job("ops.deploy", merged.id, {"reason": f"merged {merged.title}"}))


RETRY = timedelta(minutes=2)
