"""The job graph. Each handler does one step and queues the next; every step is idempotent."""

from __future__ import annotations

import asyncio
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
        queued = 0
        live = (OpportunityStatus.OPEN, OpportunityStatus.EXPERIMENTING)
        opps = [o for o in self.store.list("opportunities", Opportunity) if o.status in live]
        opps.sort(key=lambda o: (-o.evidence_level, o.created_at))
        for opp in opps:
            attempts = int(opp.details.get("attempts", 0))
            decision = decide(opp, mandate, Context(open_pull_requests=open_prs, attempts=attempts))
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
                self.store.enqueue(job("proposal.prepare", opp.id, {"id": opp.id}, correlation_id=opp.id))
                open_prs += 1
            elif decision.chosen is ActionKind.DECLINE:
                opp.status = OpportunityStatus.DECLINED
                self.store.put("opportunities", opp)

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
        if opp.category == "performance":
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


RETRY = timedelta(minutes=2)
