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


def _contains(repo: Path, version: str, commit: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, version], capture_output=True, check=False
        ).returncode
        == 0
    )


@dataclass
class LiveWatcher:
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

    def _rounds(self, target: str, version: str) -> list[Round]:
        return [Round(v, tuple(s), tuple(ms)) for _, v, s, ms in self.store.rounds(target, version=version)]

    def tick(self) -> None:
        sent = self.prober().round()
        if not sent:
            return
        history = self.history()
        if len(history) < 2:
            return
        current, previous = history[-1], history[-2]
        deploy_id = f"{len(history) - 1}:{current}"
        if self._outage(current):
            self._bad(current, previous, Impact.OUTAGE, [])
            return
        if self.store.get("deploy_verdicts", deploy_id, DeployVerdict) is None:
            self._judge(deploy_id, current, previous)

    def _outage(self, version: str) -> bool:
        for target in self.store.round_targets():
            if not any(h in target.lower() for h in HEALTH_HINTS):
                continue
            recent = self._rounds(target, version)[-OUTAGE_ROUNDS:]
            if len(recent) == OUTAGE_ROUNDS and all(all(s == 0 or s >= 500 for s in r.statuses) for r in recent):
                return self.store.get_value(f"outage:{version}") is None
        return False

    def _judge(self, deploy_id: str, current: str, previous: str) -> None:
        need = self.mandate.operations.guard_samples
        endpoints = [
            judge_endpoint(t, self._rounds(t, previous), self._rounds(t, current), need)
            for t in self.store.round_targets()
        ]
        verdict = overall(endpoints)
        waiting = verdict is Impact.INSUFFICIENT and any(e.rounds_after < need for e in endpoints)
        if waiting:
            return  # still filling the window of the new version
        record = DeployVerdict(
            id=deploy_id,
            previous=previous,
            impact=verdict,
            endpoints=[e.as_dict() for e in endpoints],
            criteria=CRITERIA,
        )
        self.store.put("deploy_verdicts", record)
        self.store.append_event(
            Event(
                type=EventType.IMPACT_JUDGED,
                actor="observer",
                entity_id=current,
                payload={
                    "previous": previous,
                    "impact": verdict.value,
                    "endpoints": {e.target: e.impact.value for e in endpoints},
                },
            )
        )
        self.log(
            f"deploy {current[:12]} judged {verdict.value}: "
            + "; ".join(f"{e.target} {e.reasons[0]}" for e in endpoints if e.impact is not Impact.HEALTHY)[:300]
        )
        self._outcomes(record, endpoints, previous)
        if verdict in (Impact.DEGRADED, Impact.OUTAGE):
            self._bad(current, previous, verdict, endpoints)

    def _outcomes(self, record: DeployVerdict, endpoints: list[Any], previous: str) -> None:
        """Level 5 for every merged proposal this deploy carried, with what else could explain the change."""
        by_target = {e.target: e for e in endpoints}
        version = record.id.split(":", 1)[1]
        commits = _git(self.repo, "log", "--format=%h %s", f"{previous}..{version}").splitlines()
        for proposal in self.store.list("proposals", Proposal):
            if proposal.status not in (ProposalStatus.MERGED, ProposalStatus.PR_OPENED):
                continue
            if not _contains(self.repo, record.id, proposal.commit_sha) or _contains(
                self.repo, previous, proposal.commit_sha
            ):
                continue
            opp = self.store.get("opportunities", proposal.opportunity_id, Opportunity)
            if opp is None or opp.details.get("outcome"):
                continue
            judged = [by_target[e] for e in opp.details.get("endpoints", []) if e in by_target]
            confounders = [
                f"{len(commits)} commit(s) shipped in this deploy: " + "; ".join(commits[:5]),
                "traffic is unbidden's own probes, not users",
                "data volume and cache state differ between the two windows",
            ]
            outcome = {"deploy": record.id, "impact": [e.as_dict() for e in judged], "confounders": confounders}
            opp.details = {**opp.details, "outcome": outcome}
            if judged and all(e.impact is Impact.IMPROVED for e in judged):
                opp.evidence_level = EvidenceLevel.OPERATIONAL_RESULT
                opp.status = OpportunityStatus.VERIFIED
                opp.evidence = [*opp.evidence, EvidenceRef(kind="config", locator=f"deploy_verdicts/{record.id}")]
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
                f"{opp.id}: real outcome after deploy {record.id[:12]}: "
                + ", ".join(f"{e.target} {e.impact.value}" for e in judged)
            )

    def _last_healthy(self, current: str) -> str | None:
        """The most recent earlier deploy judged healthy or improved (the first one served before any change)."""
        history = self.history()
        for index in range(len(history) - 2, -1, -1):
            version = history[index]
            if version == current:
                continue
            verdict = self.store.get("deploy_verdicts", f"{index}:{version}", DeployVerdict)
            if index == 0 or (verdict is not None and verdict.impact in (Impact.HEALTHY, Impact.IMPROVED)):
                return version
        return None

    def _bad(self, current: str, previous: str, impact: Impact, endpoints: list[Any]) -> None:
        if impact is Impact.OUTAGE:
            self.store.set_value(f"outage:{current}", utc_now().isoformat())
        reason = f"deploy {current[:12]} judged {impact.value}"
        place(self.store, reason)
        target = self._last_healthy(current)
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
