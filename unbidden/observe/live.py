"""The live loop: probe, judge each deploy once, record real outcomes, and act on bad ones within the mandate."""

from __future__ import annotations

import statistics
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from unbidden.contracts.common import Contract, EvidenceLevel, EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.contracts.world import Deployment, WorldModel
from unbidden.observe.impact import (
    CRITERIA,
    SUSTAINED_CRITERIA,
    SUSTAINED_PERSISTENCE,
    EndpointImpact,
    Impact,
    Round,
    judge_endpoint,
    overall,
    sustained,
)
from unbidden.observe.probe import Prober
from unbidden.operate import ledger
from unbidden.operate.deploy import OperationRefused, deploy
from unbidden.operate.holds import place
from unbidden.store import Store
from unbidden.world.scope import scope

Log = Callable[[str], None]
HEALTH_HINTS = ("health", "healthz", "ping", "status")
OUTAGE_ROUNDS = 3  # consecutive failing rounds of a health endpoint
SUSTAINED_WINDOW = timedelta(hours=4)
SUSTAINED_EVERY_S = 60.0
SUSTAINED_BASELINE_MINUTES = 30
SUSTAINED_MIN_MINUTES = 120


class DeployVerdict(Contract):
    id: str  # the version judged
    previous: str
    impact: Impact
    endpoints: list[dict[str, Any]]
    criteria: dict[str, float | int | str]
    judged_at: str = Field(default_factory=lambda: utc_now().isoformat())
    commits: dict[str, str] = Field(default_factory=dict)  # deploy -> how its commit is known
    scope: list[dict[str, Any]] = Field(default_factory=list)  # components behind what went wrong


OutcomeResult = Literal["positive", "negative", "inconclusive", "invalid"]


def classify_outcome(
    judged: list[EndpointImpact], baseline: Deployment | None, current: Deployment | None, external: list[str]
) -> tuple[OutcomeResult, list[str]]:
    """What a deploy's measurements say about one change, under criteria fixed before the measurement.

    `invalid`: the comparison cannot be credited to the change (a version that is not verified or observed, or
    a deploy nobody accounts for in between). `negative`: worse. `positive`: every endpoint the change targets
    improved. `inconclusive`: anything else (no change claimed, too few samples, endpoints not measured).
    """
    why: list[str] = []
    for name, d in (("baseline", baseline), ("candidate", current)):
        if d is None:
            why.append(f"the {name} deploy has no ledger record: the code it ran is unknown")
        elif not ledger.is_attributable(d):
            why.append(f"the {name} deploy's commit is {d.commit_status}: {d.commit_reason}")
    if external:
        why.append("deploys not made by Unbidden between the windows: " + ", ".join(external))
    if why:
        return "invalid", why
    if not judged:
        return "inconclusive", ["none of the change's endpoints was measured on both sides"]
    impacts = {e.impact for e in judged}
    if impacts & {Impact.DEGRADED, Impact.OUTAGE}:
        return "negative", [f"{e.target}: {e.reasons[0]}" for e in judged if e.reasons]
    if impacts == {Impact.IMPROVED}:
        return "positive", [f"{e.target}: {e.reasons[0]}" for e in judged if e.reasons]
    return "inconclusive", [f"{e.target}: {e.reasons[0]}" for e in judged if e.reasons]


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
        self._sustained()
        history = self.history()
        if len(history) < 2:
            return
        current = len(history) - 1
        baseline = self._baseline(history)
        if self._outage(current):
            health = [t for t in self.store.round_targets() if any(h in t.lower() for h in HEALTH_HINTS)]
            self._bad(history, current, Impact.OUTAGE, health)
            return
        if self.store.get("deploy_verdicts", f"{current}:{history[current]}", DeployVerdict) is None:
            self._judge(history, current, baseline)

    def _sustained(self, now: datetime | None = None) -> None:
        """Once a minute: each endpoint's last minutes against the oldest of the last four hours, across deploys."""
        now = now or utc_now()
        last = self.store.get_value("sustained_checked_at")
        if last and (now - datetime.fromisoformat(last)).total_seconds() < SUSTAINED_EVERY_S:
            return
        self.store.set_value("sustained_checked_at", now.isoformat())
        since = now - SUSTAINED_WINDOW
        for target in self.store.round_targets():
            per_minute: dict[str, list[float]] = {}
            for ts, _, statuses, latencies in self.store.rounds(target):
                if ts < since:
                    continue
                served = [ms for ms, st in zip(latencies, statuses, strict=True) if 200 <= st < 400]
                per_minute.setdefault(ts.strftime("%Y-%m-%dT%H:%M"), []).extend(served)
            minutes = [statistics.median(v) for _, v in sorted(per_minute.items()) if v]
            if len(minutes) < SUSTAINED_MIN_MINUTES:
                continue  # less than two hours seen: no old baseline yet
            found = sustained(minutes[:SUSTAINED_BASELINE_MINUTES], minutes[-SUSTAINED_PERSISTENCE:])
            key = f"sustained_open:{target}"
            if found is None:
                self.store.set_value(key, None)
                continue
            if self.store.get_value(key):
                continue
            self.store.set_value(key, now.isoformat())
            history = self.history()
            payload = {
                "target": target,
                "baseline_median_ms": round(found.baseline_median, 1),
                "recent_median_ms": round(found.recent_median, 1),
                "factor": round(found.factor, 2),
                "criteria": SUSTAINED_CRITERIA,
                "deploys_in_window": len(history),
            }
            self.store.append_event(
                Event(type=EventType.IMPACT_JUDGED, actor="observer", entity_id=f"sustained:{target}", payload=payload)
            )
            self.log(
                f"sustained degradation on {target}: median {found.baseline_median:.1f} -> "
                f"{found.recent_median:.1f} ms against the oldest part of the last "
                f"{SUSTAINED_WINDOW.total_seconds() / 3600:.0f} h"
            )
            first = next((v for ts, v, _, _ in self.store.rounds(target) if ts >= since), None)
            current = history[-1] if history else None
            if (
                first
                and current
                and first != current
                and not first.startswith("unknown")
                and not current.startswith("unknown")
            ):
                from unbidden.contracts.jobs import Job

                self.store.enqueue(
                    Job(
                        type="research.investigate",
                        idempotency_key=f"research.investigate:sustained:{target}:{now:%Y%m%d%H}",
                        priority=15,
                        payload={"good": first, "bad": current, "subject": f"sustained {target}",
                                 "incident": f"{target} sustained slower: {payload}"},
                    )
                )  # fmt: skip
            else:
                self.log(f"{target}: the same code ran the whole window; the cause is data, load or environment")

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

    def _deployment(self, index: int) -> Deployment | None:
        return self.store.get(ledger.COLLECTION, str(index), Deployment)

    def _commit_status(self, index: int) -> str:
        d = self._deployment(index)
        return "no ledger record" if d is None else f"{d.commit_status} ({d.initiated_by})"

    def _scopes(self, targets: list[str]) -> list[dict[str, Any]]:
        """What lies behind each endpoint that went wrong, from the World Model, with what cannot be seen."""
        return [scope(self.world, f"endpoint:{t}").brief() for t in targets]

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
        bad = [e.target for e in endpoints if e.impact in (Impact.DEGRADED, Impact.OUTAGE)]
        record = DeployVerdict(
            id=f"{current}:{version}",
            previous=previous,
            impact=verdict,
            endpoints=[e.as_dict() for e in endpoints],
            criteria=CRITERIA,
            commits={str(i): self._commit_status(i) for i in (baseline, current)},
            scope=self._scopes(bad),
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
            self._bad(history, current, verdict, bad)

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
            base_d, cur_d = self._deployment(baseline), self._deployment(current)
            external = [
                f"deploy {i}"
                for i in range(baseline + 1, current + 1)
                if (d := self._deployment(i)) is not None and d.initiated_by == "external"
            ]
            result, why = classify_outcome(judged, base_d, cur_d, external)
            confounders: list[dict[str, str]] = [
                {
                    "kind": "commits_between",
                    "detail": f"{len(commits)} commit(s) between the two measured versions: " + "; ".join(commits[:5]),
                },
                *(
                    [{"kind": "skipped_deploys", "detail": f"not used as baseline: {', '.join(skipped)}"}]
                    if skipped
                    else []
                ),
                *({"kind": "external_deploy", "detail": e} for e in external),
                {"kind": "synthetic_traffic", "detail": "traffic is unbidden's own probes, not users"},
                {"kind": "state_drift", "detail": "data volume and cache state differ between the two windows"},
            ]
            outcome = {
                "deploy": f"{current}:{version}",
                "baseline": f"{baseline}:{previous}",
                "result": result,
                "why": why,
                "commits": {
                    "baseline": base_d.commit_status if base_d else "no ledger record",
                    "candidate": cur_d.commit_status if cur_d else "no ledger record",
                },
                "impact": [e.as_dict() for e in judged],
                "confounders": confounders,
                "criteria": CRITERIA,
            }
            opp.details = {**opp.details, "outcome": outcome}
            if result == "positive":
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
            self.log(f"{opp.id}: outcome after deploy {current} is {result}: {'; '.join(why)[:300]}")

    def _last_healthy(self, history: list[str], current: int) -> str | None:
        """The most recent earlier deploy judged healthy or improved (the first one served before any change)."""
        for index in range(current - 1, -1, -1):
            if history[index] == history[current]:
                continue
            verdict = self.store.get("deploy_verdicts", f"{index}:{history[index]}", DeployVerdict)
            if index == 0 or (verdict is not None and verdict.impact in (Impact.HEALTHY, Impact.IMPROVED)):
                return history[index]
        return None

    def _bad(self, history: list[str], current: int, impact: Impact, targets: list[str] | None = None) -> None:
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
                        "scope": self._scopes(targets or []),
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
