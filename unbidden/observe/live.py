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
from unbidden.observe import advisories
from unbidden.observe.impact import (
    CRITERIA,
    SUSTAINED_CRITERIA,
    SUSTAINED_PERSISTENCE,
    WARMUP_ROUNDS,
    EndpointImpact,
    Impact,
    Round,
    judge_endpoint,
    judge_errors,
    overall,
    sustained,
)
from unbidden.observe.probe import Prober
from unbidden.operate import ledger
from unbidden.operate.deploy import OperationRefused, deploy
from unbidden.operate.holds import place
from unbidden.publish.proposal import LIVE_LEVELS
from unbidden.store import Store
from unbidden.world.scope import scope

RECHECK_EVERY = timedelta(days=1)

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


OutcomeResult = Literal["positive", "negative", "inconclusive", "invalid", "verified"]

# Level 5 for fixes whose effect the probes cannot measure (0.18.0): what is claimed is that the change runs
# in a healthy, attributable deploy, never that something measured better. Kept apart from the measured criteria
# (`CRITERIA`) in every record: the outcome's result is `verified`, not `positive`, and its criteria say so.
VERIFIED_DEPLOY = "verified-deploy-v1"
VERIFIED_DEPLOY_CLASSES = ("security", "quality", "correctness")
VERIFIED_DEPLOY_CRITERIA: dict[str, float | int | str] = {
    "criteria_version": VERIFIED_DEPLOY,
    "basis": "verified-deploy",
    "claim": LIVE_LEVELS["verified-deploy"],
    "deploy_verdict": "the deploy that first contains the change is judged healthy or improved",
    "errors": "no endpoint's failed share is higher after the deploy (95% Wilson intervals apart)",
    "attribution": "the baseline and candidate deploys are both attributable (verified or observed), none external",
    "security": "the fixed version of the package is installed in a running container of the deploy (docker exec)",
    "classes": ", ".join(VERIFIED_DEPLOY_CLASSES) + " (correctness only without a failing endpoint)",
}


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


def improvement_class(opp: Opportunity) -> str:
    """The class of improvement an opportunity's verdict claims (its first measurement's metric); latency when the
    verdict carries no typed measurement (verdicts recorded before 0.13.0 were all latency at L5)."""
    measurements = (opp.details.get("verdict") or {}).get("measurements") or []
    return str(((measurements[0] if measurements else {}).get("metric") or {}).get("improvement") or "latency")


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
        self._recheck(history)

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
        errors = [judge_errors(t, self._rounds(t, baseline), self._rounds(t, current)) for t in judgeable]
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
        self._outcomes(history, current, baseline, endpoints, errors)
        if verdict in (Impact.DEGRADED, Impact.OUTAGE):
            self._bad(history, current, verdict, bad)

    def _outcomes(
        self, history: list[str], current: int, baseline: int, endpoints: list[Any], errors: list[Any] | None = None
    ) -> None:
        """Level 5 for each proposal whose first deploy this is, with what else could explain the change. What counts
        is that its commit is in the deployed version, merged on GitHub or deployed from its local branch (a proposal
        that cannot be published yet). A proposal already present in any earlier deploy was judged there."""
        version, previous = history[current], history[baseline]
        by_target = {e.target: e for e in endpoints}
        commits = _git(self.repo, "log", "--format=%h %s", f"{previous}..{version}").splitlines()
        skipped = [history[i][:12] for i in range(baseline + 1, current)]
        shippable = (ProposalStatus.MERGED, ProposalStatus.READY, ProposalStatus.PR_OPENED, ProposalStatus.PUBLISHING)
        for proposal in (p for p in self.store.list("proposals", Proposal) if p.status in shippable):
            shipped = proposal.merge_sha or proposal.commit_sha
            if not contains(self.repo, version, shipped):
                continue
            if any(contains(self.repo, history[i], shipped) for i in range(current)):
                continue  # not this deploy's change
            opp = self.store.get("opportunities", proposal.opportunity_id, Opportunity)
            if opp is None or opp.details.get("outcome"):
                continue
            judged = [by_target[e] for e in opp.details.get("endpoints", []) if e in by_target]
            if improvement_class(opp) in ("correctness", "reliability"):
                # A fix is judged by the failures it was meant to remove, not by latency (campaign 13, WS4).
                failing = {e.target: e for e in errors or []}
                targets = opp.details.get("endpoints") or [t for t, e in failing.items() if e.errors_before]
                judged = [failing[e] for e in targets if e in failing]
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
                "at": utc_now().isoformat(),
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
                "basis": "measured-effect",
            }
            cls = improvement_class(opp)
            if result == "inconclusive" and cls in VERIFIED_DEPLOY_CLASSES and not (cls == "correctness" and judged):
                conditions = self._verified_deploy(opp, cls, current, errors)
                met = all(c["met"] for c in conditions)
                outcome["verified_deploy"] = {"criteria_version": VERIFIED_DEPLOY, "met": met, "conditions": conditions}
                if met:
                    measured = {"result": "inconclusive", "why": why, "criteria": CRITERIA}
                    result, why = "verified", [c["detail"] for c in conditions]
                    outcome.update(
                        result=result,
                        why=why,
                        criteria=VERIFIED_DEPLOY_CRITERIA,
                        basis="verified-deploy",
                        measured=measured,
                    )
                else:
                    why = [*why, *(f"no verified deploy: {c['detail']}" for c in conditions if not c["met"])]
                    outcome["why"] = why
            promotes = result in ("positive", "verified")
            if promotes and opp.evidence_level < EvidenceLevel.FUNCTIONAL_VALIDATION:
                # A live result is level 5 on top of a validated change, never in its place.
                why = [*why, f"the lab evidence is L{int(opp.evidence_level)}, below L4: no promotion to L5"]
                outcome["why"] = why
                outcome["promoted"] = False
            opp.details = {**opp.details, "outcome": outcome}
            if promotes and opp.evidence_level >= EvidenceLevel.FUNCTIONAL_VALIDATION:
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

    def _verified_deploy(
        self, opp: Opportunity, cls: str, current: int, errors: list[Any] | None
    ) -> list[dict[str, Any]]:
        """Each condition of `verified-deploy-v1` beyond attribution (which `classify_outcome` already required for an
        inconclusive result), met or not, with what was seen. Nothing unread counts as met."""
        verdict = self.store.get_value(f"verdict_of:{current}")
        healthy = verdict in (Impact.HEALTHY.value, Impact.IMPROVED.value)
        conditions: list[dict[str, Any]] = [
            {"name": "attribution", "met": True,
             "detail": f"deploys attributable: {self._commit_status(current)}, none external in between"},
            {"name": "deploy_verdict", "met": healthy,
             "detail": f"deploy {current} judged {verdict or 'not yet'}" + ("" if healthy else ", not healthy")},
        ]  # fmt: skip
        if errors is None:
            conditions.append({"name": "errors", "met": False, "detail": "failed requests were not judged"})
        else:
            worse = [e for e in errors if e.impact is Impact.DEGRADED]
            short = sum(1 for e in errors if e.impact is Impact.INSUFFICIENT)
            detail = (
                "more failed requests after the deploy: " + "; ".join(f"{e.target} {e.reasons[0]}" for e in worse)
                if worse
                else f"no endpoint fails more after the deploy ({len(errors)} judged"
                + (f", {short} with too few requests to tell" if short else "")
                + ")"
            )
            conditions.append({"name": "errors", "met": not worse, "detail": detail})
        if cls == "security":
            met, detail = self._fix_installed(opp, current)
            conditions.append({"name": "installed", "met": met, "detail": detail})
        return conditions

    def _fix_installed(self, opp: Opportunity, current: int) -> tuple[bool, str]:
        """The bumped package at its fixed version inside the deploy's running containers (the ledger's record of
        this compose project's containers), read with `docker exec`; a container that cannot be read is said so."""
        extra = ((opp.details.get("findings") or [{}])[0] or {}).get("extra") or {}
        package, fix = extra.get("package"), extra.get("lowest_fix")
        if not package or not fix:
            return False, "the opportunity names no package and fixed version to look for"
        deployment = self._deployment(current)
        containers = deployment.containers if deployment else []
        if not containers:
            return False, f"deploy {current} has no containers on record: the installed {package} cannot be read"
        unread: list[str] = []
        held: list[tuple[str, str]] = []
        for c in containers:
            rows = advisories.installed_in_container(c.container_id or c.name)
            if rows is None:
                unread.append(c.service)
            elif (version := advisories.version_of(rows, package)) is not None:
                held.append((c.service, version))
        if not held:
            seen = f"; unreadable: {', '.join(unread)}" if unread else ""
            return False, f"{package} could not be read in any running container of deploy {current}{seen}"
        for service, version in held:
            fixed = advisories.at_least(version, fix)
            if fixed is None:
                return False, f"{service} runs {package} {version}, which cannot be compared with the fix {fix}"
            if not fixed:
                return False, f"{service} still runs {package} {version}, below the fix {fix}"
        return True, f"{package} " + ", ".join(f"{v} in {s}" for s, v in held) + f" (fixed in {fix})"

    def _recheck(self, history: list[str], now: datetime | None = None) -> None:
        """Each positive live result, checked again about once a day against the same baseline and criteria: it holds,
        or it is invalidated (the change is no longer deployed, or its effect is gone) and its level goes back to L4.
        Held through the mandate's persistence period, with at least two checks, it is persistent (L6)."""
        now = now or utc_now()
        need = self.mandate.operations.guard_samples
        current = len(history) - 1
        for opp in self.store.list("opportunities", Opportunity, status=OpportunityStatus.VERIFIED.value):
            outcome: dict[str, Any] = opp.details.get("outcome") or {}
            if outcome.get("result") not in ("positive", "verified") or opp.evidence_level >= EvidenceLevel.PERSISTENCE:
                continue
            checks: list[dict[str, Any]] = opp.details.get("rechecks", [])
            recorded = datetime.fromisoformat(outcome.get("at") or opp.updated_at.isoformat())
            last = datetime.fromisoformat(checks[-1]["at"]) if checks else recorded
            if now - last < RECHECK_EVERY:
                continue
            proposal = next((p for p in self.store.list("proposals", Proposal) if p.opportunity_id == opp.id), None)
            shipped = (proposal.merge_sha or proposal.commit_sha) if proposal else None
            if shipped is None or current < 0 or not contains(self.repo, history[current], shipped):
                self._invalidate(opp, f"no longer deployed: deploy {current} runs {history[current][:12]}", now)
                continue
            if outcome.get("result") == "verified":
                continue  # a verified deploy claims no effect: there is nothing to measure again, and no L6
            baseline = int(str(outcome["baseline"]).split(":")[0])
            judged = []
            for target in opp.details.get("endpoints", []):
                after = self._rounds(target, current)[-(need + WARMUP_ROUNDS) :]  # the judge drops the warm-up
                judged.append(judge_endpoint(target, self._rounds(target, baseline), after, need))
            if not judged or any(e.impact is Impact.INSUFFICIENT for e in judged):
                continue  # not enough recent rounds yet: checked again at the next tick
            if any(e.impact is not Impact.IMPROVED for e in judged):
                gone = [f"{e.target}: {e.reasons[0] if e.reasons else e.impact.value}" for e in judged]
                self._invalidate(opp, "the effect is no longer measured: " + "; ".join(gone), now)
                continue
            checks = [*checks, {"at": now.isoformat(), "deploy": f"{current}:{history[current]}", "held": True}]
            opp.details = {**opp.details, "rechecks": checks}
            persistent = now - recorded >= timedelta(days=self.mandate.evaluation.persistence_days) and len(checks) >= 2
            if persistent:
                opp.evidence_level = EvidenceLevel.PERSISTENCE
            self.store.put("opportunities", opp)
            self.store.append_event(
                Event(type=EventType.OUTCOME_HELD, actor="observer", entity_id=opp.id, correlation_id=opp.id,
                      payload={"checks": len(checks), "persistent": persistent, "deploy": checks[-1]["deploy"]})
            )  # fmt: skip
            self.log(f"{opp.id}: live result held ({len(checks)} check(s)){'; persistent (L6)' if persistent else ''}")

    def _invalidate(self, opp: Opportunity, why: str, now: datetime) -> None:
        """A live result that no longer holds: back to what the lab showed (L4), the reason kept with the outcome."""
        outcome = {**opp.details.get("outcome", {}), "invalidated": {"at": now.isoformat(), "why": why}}
        opp.details = {**opp.details, "outcome": outcome}
        opp.evidence_level = EvidenceLevel.FUNCTIONAL_VALIDATION
        opp.status = OpportunityStatus.PROPOSED
        self.store.put("opportunities", opp)
        self.store.append_event(
            Event(type=EventType.OUTCOME_INVALIDATED, actor="observer", entity_id=opp.id, correlation_id=opp.id,
                  payload={"why": why})
        )  # fmt: skip
        self.log(f"{opp.id}: live result invalidated: {why}")

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
        hold = place(self.store, reason)
        from unbidden.director.asks import for_hold, open_ask

        open_ask(self.store, for_hold(hold))
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
