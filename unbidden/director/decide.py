"""Expected-utility choice per opportunity and evidence level. Pure: no I/O, no model.

value      what a resolved opportunity is worth, by category, from the mandate's priorities
p_success  chance the action reaches its goal, from what the lab has already seen
cost       the action's expected spend, local compute included
risk       what a person would have to undo if it went wrong
"""

from __future__ import annotations

from dataclasses import dataclass

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, CandidateAction, Decision, Opportunity, OpportunityStatus
from unbidden.observe.ci import analyzer_tool
from unbidden.store import Store

CATEGORY_VALUE = {
    "bugs": 1.5,
    "performance": 1.3,
    "types": 1.0,
    "security": 1.2,
    "lint": 0.5,
    "format": 0.2,
    "tests": 1.0,
}
PRIORITY_BOOST = {
    "correctness": {"bugs", "types", "tests"},
    "maintainability": {"lint", "format"},
    "security": {"security"},
}
EXPERIMENT_COST_USD = 0.02  # local compute of one experiment, measured order of magnitude
RISK_WEIGHT = 0.5
MAX_LAB_ATTEMPTS = 2


LOW_VALUE = {"lint", "format"}


@dataclass(frozen=True)
class Context:
    open_pull_requests: int
    attempts: int  # experiments already run on this opportunity without an improvement
    checked_dirs: tuple[str, ...] = ()  # where the team's CI works; empty means the whole repository
    ci_commands: str | None = ""  # what the team's workflows run, lowercased; None when no workflow could be read
    ci_status: str | None = None  # "green" / "red": the team's own checks on this commit, when GitHub could be read
    tool_status: dict[str, str] | None = None  # tool -> "green" / "red": the jobs that run that tool, on this commit


def outside_checked_scope(opp: Opportunity, checked_dirs: tuple[str, ...]) -> bool:
    """Style findings in code the team's own CI never looks at are not worth a person's review."""
    if opp.category not in LOW_VALUE or not checked_dirs or "." in checked_dirs:
        return False
    paths: list[str] = opp.details.get("paths", [])
    return bool(paths) and not any(p.startswith(f"{d.rstrip('/')}/") for p in paths for d in checked_dirs)


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
    if "@" in str(opp.details.get("tool", "")):
        reason = "found in a service analyzed in isolation: the lab cannot reproduce it inside the repository yet"
        add(ActionKind.WAIT, 0.0, 0.0, 0.0, reason)
        return _choose(opp, candidates, ActionKind.WAIT)
    if opp.category in LOW_VALUE and ctx.ci_commands is None:
        add(
            ActionKind.WAIT,
            0.0,
            0.0,
            0.0,
            "the team's CI is not understood: style findings wait until its checks are known",
        )
        return _choose(opp, candidates, ActionKind.WAIT)
    tool = analyzer_tool(opp.details)
    if opp.category in LOW_VALUE and ctx.ci_commands and tool and tool not in ctx.ci_commands:
        add(
            ActionKind.DECLINE,
            1.0,
            0.0,
            0.0,
            f"the team's CI does not run {tool}: its style is not the team's standard",
        )
        return _choose(opp, candidates, ActionKind.DECLINE)
    # The jobs that run this very tool, when known; the whole commit otherwise.
    green = (ctx.tool_status or {}).get(tool, ctx.ci_status) == "green"
    if green and tool and ctx.ci_commands and tool in ctx.ci_commands:
        # Whatever the category: a type error the team's own green job does not report is an environment difference
        # (another version of the tool or of Python), and a fix for it would turn their CI red.
        reason = f"the team's CI runs {tool} and passes on this commit: these findings come from Unbidden's environment"
        add(ActionKind.DECLINE, 1.0, 0.0, 0.0, reason)
        return _choose(opp, candidates, ActionKind.DECLINE)
    if outside_checked_scope(opp, ctx.checked_dirs):
        reason = f"{opp.category} findings outside what the team's CI checks ({', '.join(ctx.checked_dirs)})"
        add(ActionKind.DECLINE, 1.0, 0.0, 0.0, reason)
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
    elif (blocked := opp.details.get("blocked")) and blocked.get("rev") == opp.details.get("rev"):
        add(ActionKind.WAIT, 0.0, 0.0, 0.0, f"not measurable at this commit: {str(blocked.get('why', ''))[:200]}")
        return _choose(opp, candidates, ActionKind.WAIT)
    elif ctx.attempts >= MAX_LAB_ATTEMPTS:
        add(ActionKind.DECLINE, 0.0, 0.0, 0.0, f"{ctx.attempts} experiments found no proven fix")
        return _choose(opp, candidates, ActionKind.DECLINE)
    elif opp.status is OpportunityStatus.OPEN:
        p = 0.6 / (1 + ctx.attempts)
        add(ActionKind.RUN_EXPERIMENT, p, EXPERIMENT_COST_USD, 0.0, "reproduce it and measure a candidate offline")
    best = max(candidates, key=lambda c: c.utility)
    return _choose(opp, candidates, best.kind)


def _choose(opp: Opportunity, candidates: list[CandidateAction], chosen: ActionKind) -> Decision:
    # The last candidate of that kind: a specific reason (a full PR cap, a blocked lab) follows the default "wait".
    reason = next((c.reason for c in reversed(candidates) if c.kind is chosen), "")
    return Decision(
        opportunity_id=opp.id, evidence_level=opp.evidence_level, candidates=candidates, chosen=chosen, reason=reason
    )


def reopen(store: Store, opp: Opportunity, reason: str, actor: str = "operator") -> Opportunity:
    """Give an opportunity its experiments back, when what consumed them was Unbidden's own fault (a lab bug fixed
    since). Its history stays: the reopening is counted, recorded with its reason, and keys new experiment jobs."""
    opp.details = {
        **{k: v for k, v in opp.details.items() if k not in ("attempts", "decision", "blocked")},
        "reopened": int(opp.details.get("reopened", 0)) + 1,
    }
    opp.status = OpportunityStatus.OPEN
    store.put("opportunities", opp)
    store.append_event(
        Event(
            type=EventType.OPPORTUNITY_OPENED,
            actor=actor,
            entity_id=opp.id,
            correlation_id=opp.id,
            payload={"reopened": opp.details["reopened"], "reason": reason},
        )
    )
    return opp
