from __future__ import annotations

import pytest

from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, Opportunity, OpportunityStatus
from unbidden.director.decide import Context, decide

pytestmark = pytest.mark.unit


def opp(category: str = "types", level: int = 1, improved: bool | None = None, **kw: object) -> Opportunity:
    details: dict[str, object] = {}
    if improved is not None:
        details["verdict"] = {"improved": improved}
    return Opportunity(
        source="tsc", category=category, title="t", summary="s", dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="a")], evidence_level=EvidenceLevel(level), details=details,
        **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def test_new_opportunity_runs_an_experiment(mandate: Mandate) -> None:
    assert decide(opp(), mandate, Context(0, 0)).chosen is ActionKind.RUN_EXPERIMENT


def test_unknown_category_is_declined_with_reason(mandate: Mandate) -> None:
    decision = decide(opp(category="vibes"), mandate, Context(0, 0))
    assert decision.chosen is ActionKind.DECLINE and "vibes" in decision.reason


def test_proven_l4_is_proposed_unless_the_cap_is_full(mandate: Mandate) -> None:
    proven = opp(level=4, improved=True, status=OpportunityStatus.EXPERIMENTING)
    assert decide(proven, mandate, Context(0, 0)).chosen is ActionKind.PROPOSE_CHANGE
    assert decide(proven, mandate, Context(3, 0)).chosen is ActionKind.WAIT


def test_l3_is_not_enough_for_the_default_mandate(mandate: Mandate) -> None:
    decision = decide(opp(level=3, improved=True), mandate, Context(0, 0))
    assert decision.chosen is ActionKind.DECLINE and "L4" in decision.reason


def test_gives_up_after_repeated_failures(mandate: Mandate) -> None:
    assert decide(opp(level=2), mandate, Context(0, 2)).chosen is ActionKind.DECLINE


def test_style_findings_outside_the_ci_scope_are_declined(mandate: Mandate) -> None:
    lint = opp(category="lint")
    lint.details = {"paths": ["scripts/release.py"]}
    decision = decide(lint, mandate, Context(0, 0, checked_dirs=("backend",)))
    assert decision.chosen is ActionKind.DECLINE and "backend" in decision.reason
    lint.details = {"paths": ["backend/app/main.py"]}
    assert decide(lint, mandate, Context(0, 0, checked_dirs=("backend",))).chosen is ActionKind.RUN_EXPERIMENT
    bug = opp(category="bugs")
    bug.details = {"paths": ["scripts/release.py"]}
    assert decide(bug, mandate, Context(0, 0, checked_dirs=("backend",))).chosen is ActionKind.RUN_EXPERIMENT
