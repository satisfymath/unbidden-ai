"""The live loop: probe, judge each deploy once, record real outcomes, and act on bad ones within the mandate."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, EvidenceLevel, EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.contracts.world import WorldModel
from unbidden.observe.impact import CRITERIA, Impact, Round, judge_endpoint, overall
from unbidden.observe.probe import Prober
from unbidden.operate.deploy import OperationRefused, deploy
from unbidden.operate.holds import place
from unbidden.store import Store

Log = Callable[[str], None]
HEALTH_HINTS = ("health", "healthz", "ping", "status")
OUTAGE_ROUNDS = 3  # consecutive failing rounds of a health endpoint


class DeployVerdict(Contract):
    id: str  # the version judged
    previous: str
    impact: Impact
    endpoints: list[dict[str, Any]]
    criteria: dict[str, float | int | str]
    judged_at: str = Field(default_factory=lambda: utc_now().isoformat())


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout.strip()


def contains(repo: Path, version: str, commit: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, version], capture_output=True, check=False
        ).returncode
        == 0
    )


@dataclass
class LiveWatcher:
    """Works per deploy (an index in the deploy sequence), not per version: a version deployed again after a
    rollback starts a window of its own and inherits none of its earlier rounds."""

    repo: Path
    store: Store
    mandate: Mandate
    world: WorldModel
    log: Log = print

    def prober(self) -> Prober:
        return Prober(self.repo, self.store, self.world, self.mandate.operations.probe_auth)

    def history(self) -> list[str]:
        """Deployed versions in order; a version appears again when it is deployed again (a rollback)."""
        return list(self.store.get_value("deploy_sequence", []))

    def _rounds(self, target: str, deploy: int) -> list[Round]:
        return [Round(v, tuple(s), tuple(ms)) for _, v, s, ms in self.store.rounds(target, deploy=deploy)]

    def tick(self) -> None:
        if not self.prober().round():
            return
        history = self.history()
        if len(history) < 2:
            return
        current = len(history) - 1
        baseline = self._baseline(history)
        if self._outage(current):
            self._bad(history, current, Impact.OUTAGE)
            return
        if self.store.get("deploy_verdicts", f"{current}:{history[current]}", DeployVerdict) is None:
            self._judge(history, current, baseline)

    def _baseline(self, history: list[str]) -> int:
        """The deploy to compare against: the previous one, or, when it ran too briefly to be judged or was an
        outage, the most recent earlier one with enough rounds. What was skipped over is a confounder."""
        need = self.mandate.operations.guard_samples
        targets = self.store.round_targets()
        for index in range(len(history) - 2, -1, -1):
            if self.store.get_value(f"outage_deploy:{index}") is not None:
                continue
            if any(len(self._rounds(t, index)) >= need for t in targets):
                return index
        return len(history) - 2

    def _served(self, target: str, deploy: int) -> bool:
        """Endpoints the probe user may not read (401/403 throughout) cannot be judged; they are left out."""
        return any(r.served for r in self._rounds(target, deploy))

    def _outage(self, deploy: int) -> bool:
        if self.store.get_value(f"outage_deploy:{deploy}") is not None:
            return False
        for target in self.store.round_targets():
            if not any(h in target.lower() for h in HEALTH_HINTS):
                continue
            recent = self._rounds(target, deploy)[-OUTAGE_ROUNDS:]
            if len(recent) == OUTAGE_ROUNDS and all(all(s == 0 or s >= 500 for s in r.statuses) for r in recent):
                return True
        return False

    def _judge(self, history: list[str], current: int, baseline: int) -> None:
        need = self.mandate.operations.guard_samples
        judgeable = [t for t in self.store.round_targets() if self._served(t, baseline)]
        endpoints = [judge_endpoint(t, self._rounds(t, baseline), self._rounds(t, current), need) for t in judgeable]
        verdict = overall(endpoints)
        if verdict is Impact.INSUFFICIENT and any(e.rounds_after < need for e in endpoints):
            return  # still filling the window of the new deploy
        version, previous = history[current], history[baseline]
        record = DeployVerdict(
            id=f"{current}:{version}",
            previous=previous,
            impact=verdict,
            endpoints=[e.as_dict() for e in endpoints],
            criteria=CRITERIA,
        )
        self.store.put("deploy_verdicts", record)
        self.store.set_value(f"verdict_of:{current}", verdict.value)
        self.store.append_event(
            Event(
                type=EventType.IMPACT_JUDGED,
                actor="observer",
                entity_id=record.id,
                payload={
                    "baseline": f"{baseline}:{previous}",
                    "impact": verdict.value,
                    "endpoints": {e.target: e.impact.value for e in endpoints},
                },
            )
        )
        notable = "; ".join(f"{e.target} {e.reasons[0]}" for e in endpoints if e.impact is not Impact.HEALTHY)
        self.log(f"deploy {current} ({version[:12]}) judged {verdict.value} against deploy {baseline}: {notable[:300]}")
        self._outcomes(history, current, baseline, endpoints)
        if verdict in (Impact.DEGRADED, Impact.OUTAGE):
            self._bad(history, current, verdict)

    def _outcomes(self, history: list[str], current: int, baseline: int, endpoints: list[Any]) -> None:
        """Level 5 for each merged proposal whose first deploy this is, with what else could explain the change.
        A proposal already present in any earlier deploy was judged there, or never can be."""
        version, previous = history[current], history[baseline]
        by_target = {e.target: e for e in endpoints}
        commits = _git(self.repo, "log", "--format=%h %s", f"{previous}..{version}").splitlines()
        skipped = [history[i][:12] for i in range(baseline + 1, current)]
        for proposal in self.store.list("proposals", Proposal, status=ProposalStatus.MERGED.value):
            shipped = proposal.merge_sha or proposal.commit_sha
            if not contains(self.repo, version, shipped):
                continue
            if any(contains(self.repo, history[i], shipped) for i in range(current)):
                continue  # not this deploy's change
            opp = self.store.get("opportunities", proposal.opportunity_id, Opportunity)
            if opp is None or opp.details.get("outcome"):
                continue
            judged = [by_target[e] for e in opp.details.get("endpoints", []) if e in by_target]
            confounders = [
                f"{len(commits)} commit(s) between the two measured versions: " + "; ".join(commits[:5]),
                *(
                    [f"{len(skipped)} intermediate deploy(s) not used as baseline: {', '.join(skipped)}"]
                    if skipped
                    else []
                ),
                "traffic is unbidden's own probes, not users",
                "data volume and cache state differ between the two windows",
            ]
            outcome = {
                "deploy": f"{current}:{version}",
                "baseline": f"{baseline}:{previous}",
                "impact": [e.as_dict() for e in judged],
                "confounders": confounders,
                "criteria": CRITERIA,
            }
            opp.details = {**opp.details, "outcome": outcome}
            if judged and all(e.impact is Impact.IMPROVED for e in judged):
                opp.evidence_level = EvidenceLevel.OPERATIONAL_RESULT
                opp.status = OpportunityStatus.VERIFIED
                opp.evidence = [
                    *opp.evidence,
                    EvidenceRef(kind="config", locator=f"deploy_verdicts/{current}:{version}"),
                ]
            self.store.put("opportunities", opp)
            self.store.append_event(
                Event(
                    type=EventType.OUTCOME_RECORDED,
                    actor="observer",
                    entity_id=opp.id,
                    correlation_id=opp.id,
                    payload=outcome,
                )
            )
            self.log(
                f"{opp.id}: real outcome after deploy {current}: "
                + ", ".join(f"{e.target} {e.impact.value}" for e in judged)
            )

    def _last_healthy(self, history: list[str], current: int) -> str | None:
        """The most recent earlier deploy judged healthy or improved (the first one served before any change)."""
        for index in range(current - 1, -1, -1):
            if history[index] == history[current]:
                continue
            verdict = self.store.get("deploy_verdicts", f"{index}:{history[index]}", DeployVerdict)
            if index == 0 or (verdict is not None and verdict.impact in (Impact.HEALTHY, Impact.IMPROVED)):
                return history[index]
        return None

    def _bad(self, history: list[str], current: int, impact: Impact) -> None:
        if impact is Impact.OUTAGE:
            self.store.set_value(f"outage_deploy:{current}", utc_now().isoformat())
            self.store.set_value(f"verdict_of:{current}", impact.value)
        reason = f"deploy {current} ({history[current][:12]}) judged {impact.value}"
        place(self.store, reason)
        target = self._last_healthy(history, current)
        if target is not None:
            # Explain it, read-only, before anyone touches it again.
            from unbidden.contracts.jobs import Job

            self.store.enqueue(
                Job(
                    type="research.investigate",
                    idempotency_key=f"research.investigate:{current}",
                    priority=15,
                    payload={
                        "good": target,
                        "bad": history[current],
                        "incident": reason,
                        "subject": f"deploy {current}",
                    },
                )
            )
        if self.mandate.autonomy.rollback is not Autonomy.ALLOW or target is None:
            self.log(f"{reason}: hold placed; rollback needs a person (`unbidden mode`) or a healthy version")
            return
        self.log(f"{reason}: rolling back to {target[:12]}, the last healthy version")
        try:
            result = deploy(self.repo, self.store, self.mandate, target, reason=reason, rollback=True)
        except OperationRefused as exc:
            self.log(f"rollback refused: {exc}")
            return
        self.log(f"rollback {'done' if result.ok else 'FAILED'}; a hold stays until a person releases it")
