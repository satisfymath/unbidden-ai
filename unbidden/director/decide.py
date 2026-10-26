"""Expected-utility choice per opportunity and evidence level. Pure: no I/O, no model.

value      what a resolved opportunity is worth, by category, from the mandate's priorities
p_success  chance the action reaches its goal, from what the lab has already seen
cost       the action's expected spend, local compute included
risk       what a person would have to undo if it went wrong
"""

from __future__ import annotations

from dataclasses import dataclass

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, CandidateAction, Decision, Opportunity, OpportunityStatus

CATEGORY_VALUE = {"types": 1.0, "security": 1.2, "lint": 0.5, "format": 0.2, "tests": 1.0}
PRIORITY_BOOST = {"correctness": {"types", "tests"}, "maintainability": {"lint", "format"}, "security": {"security"}}
EXPERIMENT_COST_USD = 0.02  # local compute of one experiment, measured order of magnitude
RISK_WEIGHT = 0.5
MAX_LAB_ATTEMPTS = 2


@dataclass(frozen=True)
class Context:
    open_pull_requests: int
    attempts: int  # experiments already run on this opportunity without an improvement


def category_value(category: str, mandate: Mandate) -> float:
    base = CATEGORY_VALUE.get(category)
    if base is None:
        return 0.0
    boosted = any(category in PRIORITY_BOOST.get(p, set()) for p in mandate.priorities)
    return base * (1.5 if boosted else 1.0)


def _utility(p: float, value: float, cost: float, risk: float) -> float:
    return p * value - cost - RISK_WEIGHT * risk


def decide(opp: Opportunity, mandate: Mandate, ctx: Context) -> Decision:
    value = category_value(opp.category, mandate)
    candidates: list[CandidateAction] = []

    def add(kind: ActionKind, p: float, cost: float, risk: float, reason: str) -> None:
        candidates.append(
            CandidateAction(kind=kind, p_success=p, value=value, cost_usd=cost, risk=risk,
                            utility=_utility(p, value, cost, risk), reason=reason)
        )  # fmt: skip

    add(ActionKind.WAIT, 0.0, 0.0, 0.0, "doing nothing costs nothing")
    if value == 0.0:
        add(ActionKind.DECLINE, 1.0, 0.0, 0.0, f"category {opp.category!r} has no value under this mandate")
        return _choose(opp, candidates, ActionKind.DECLINE)

    level = opp.evidence_level
    minimum = EvidenceLevel(mandate.evaluation.minimum_evidence_for_proposal)
    proven = opp.details.get("verdict", {}).get("improved") is True
    if proven and level >= minimum:
        cap = mandate.egress.github.max_open_pull_requests
        if ctx.open_pull_requests >= cap:
            add(ActionKind.WAIT, 0.5, 0.0, 0.0, f"{ctx.open_pull_requests} pull requests already open (cap {cap})")
            return _choose(opp, candidates, ActionKind.WAIT)
        add(ActionKind.PROPOSE_CHANGE, 0.8, 0.0, 0.1, f"evidence L{int(level)} meets the mandate's L{int(minimum)}")
    elif proven:
        reason = f"proven only to L{int(level)}; the mandate asks L{int(minimum)} before proposing"
        add(ActionKind.DECLINE, 0.0, 0.0, 0.0, reason)
        return _choose(opp, candidates, ActionKind.DECLINE)
    elif ctx.attempts >= MAX_LAB_ATTEMPTS:
        add(ActionKind.DECLINE, 0.0, 0.0, 0.0, f"{ctx.attempts} experiments found no proven fix")
        return _choose(opp, candidates, ActionKind.DECLINE)
    elif opp.status is OpportunityStatus.OPEN:
        p = 0.6 / (1 + ctx.attempts)
        add(ActionKind.RUN_EXPERIMENT, p, EXPERIMENT_COST_USD, 0.0, "reproduce it and measure a candidate offline")
    best = max(candidates, key=lambda c: c.utility)
    return _choose(opp, candidates, best.kind)


def _choose(opp: Opportunity, candidates: list[CandidateAction], chosen: ActionKind) -> Decision:
    reason = next((c.reason for c in candidates if c.kind is chosen), "")
    return Decision(
        opportunity_id=opp.id, evidence_level=opp.evidence_level, candidates=candidates, chosen=chosen, reason=reason
    )
