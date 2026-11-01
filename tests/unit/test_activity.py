"""The activity report reads the workspace's state and says what was decided and why, proven, built and spent."""

from __future__ import annotations

import pytest

from unbidden.contracts.capability import CapabilityNeed, NeedStatus
from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.experiment import Experiment, TestSummary
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.director.activity import build, render_html, render_text
from unbidden.store import Store

pytestmark = pytest.mark.unit


def opp(title: str, **kw: object) -> Opportunity:
    return Opportunity(
        source="mypy", category="types", title=title, summary="s", dedup_key=title,
        evidence=[EvidenceRef(kind="file", locator="a.py")], **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def test_it_reports_decisions_proofs_capabilities_and_spend(store: Store) -> None:
    store.put(
        "opportunities", opp("d1", status=OpportunityStatus.DECLINED, details={"decision": {"reason": "same CI"}})
    )
    store.put(
        "opportunities", opp("d2", status=OpportunityStatus.DECLINED, details={"decision": {"reason": "same CI"}})
    )
    store.put("opportunities", opp("w", details={"decision": {"chosen": "wait", "reason": "CI still running"}}))
    store.put("opportunities", opp("held", evidence_level=EvidenceLevel.PERSISTENCE, status=OpportunityStatus.VERIFIED,
                                   details={"outcome": {"result": "positive"}, "rechecks": [{}, {}]}))  # fmt: skip
    store.put("needs", CapabilityNeed(id="need_1", kind="log_adapter", source="compose:api", why="x",
                                      status=NeedStatus.AWAITING_APPROVAL, capability_id="cap_1"))  # fmt: skip
    rows = [{"workspace": "shop", "charged": 0.01}, {"workspace": "elsewhere", "charged": 5.0}]
    data = build(store, "shop", rows)
    assert data["declined_because"] == [("same CI", 2)] and data["waiting_because"] == [("CI still running", 1)]
    (held,) = data["proven"]
    assert held["level"] == 6 and held["held_checks"] == 2 and held["current_rules"] is None
    assert data["capabilities"]["awaiting_approval"][0]["capability"] == "cap_1"
    assert data["spent"] == {"calls": 1, "usd": 0.01, "basis": data["spent"]["basis"]}  # this workspace only
    page = render_html(data)
    assert "<script" not in page and "http" not in page.replace("http-equiv", "")  # self-contained
    assert any("forge approve cap_1" in line for line in render_text(data))


def test_a_level_recorded_under_older_test_rules_is_flagged(store: Store) -> None:
    # mealie (D-035): recorded L4, but its base suite never ran (D-040).
    never_ran = TestSummary(rounds=1, failed_per_round=[["<suite>"]])
    ran = TestSummary(rounds=1, failed_per_round=[[]], round_status=["ran"], collected_per_round=[10])
    experiment = Experiment(
        opportunity_id="o", base_sha="a" * 40, candidate_patch_sha256="x", baseline_tests=never_ran, candidate_tests=ran
    )
    store.put("experiments", experiment)
    verdict = {"experiment_id": experiment.id, "improved": True}
    store.put(
        "opportunities", opp("idx", evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION, details={"verdict": verdict})
    )
    (proven,) = build(store, "shop")["proven"]
    assert proven["current_rules"] == "not L4 under today's test rules (infra_failure)"
