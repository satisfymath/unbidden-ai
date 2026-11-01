"""A lab verdict that does not hold is withdrawn, not erased; older performance verdicts await revalidation."""

from __future__ import annotations

from typing import Any

import pytest

from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.events import EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.director.activity import build
from unbidden.lab.perfstats import PERF_CRITERIA, SESSION_CRITERIA
from unbidden.lab.revoke import pending, revoke
from unbidden.store import Store

pytestmark = pytest.mark.unit


def proven(store: Store, criteria: dict[str, Any]) -> Opportunity:
    opp = Opportunity(source="world", category="performance", title="t", summary="s", dedup_key="k",
                      evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION, status=OpportunityStatus.EXPERIMENTING,
                      evidence=[EvidenceRef(kind="experiment", locator="exp_1")],
                      details={"verdict": {"criteria": criteria, "experiment_id": "exp_1"}})  # fmt: skip
    store.put("opportunities", opp)
    return opp


def test_a_revoked_l4_keeps_its_verdict_history_and_reason(store: Store) -> None:
    opp = proven(store, PERF_CRITERIA)
    sha = "a" * 40
    store.put("proposals", Proposal(opportunity_id=opp.id, experiment_id="exp_1", branch="b", base_sha=sha,
                                    commit_sha=sha, title="index", body_md="",
                                    evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION))  # fmt: skip
    revoke(store, opp.id, "the index is never used by the measured query", criteria="perf-v3",
           evidence="docs/bench/stage9-revalidation/commentaries-author_id.json", by="person")  # fmt: skip
    after = store.get("opportunities", opp.id, Opportunity)
    assert after is not None and after.evidence_level is EvidenceLevel.REPRODUCTION
    assert after.details["verdict"]["experiment_id"] == "exp_1"  # the original verdict is kept
    (entry,) = after.details["revocations"]
    assert entry["previous_level"] == 4 and "never used" in entry["why"] and entry["criteria"] == "perf-v3"
    assert [p.status for p in store.list("proposals", Proposal)] == [ProposalStatus.STALE]
    assert any(e.type is EventType.VERDICT_REVOKED for e in store.events())
    assert build(store, "w")["revoked"][0]["was"] == 4


def test_verdicts_under_older_criteria_are_pending_revalidation(store: Store) -> None:
    assert "pending revalidation" in str(pending(proven(store, PERF_CRITERIA)))
    assert pending(proven(store, SESSION_CRITERIA)) is None


def test_the_text_activity_shows_the_projects_own_checks_and_revocations(store: Store) -> None:
    """Stage 9 walk: RELEASE promises the base checks in `unbidden activity`; only the JSON had them."""
    from unbidden.director.activity import render_text

    store.set_value("baseline_checks", {"rev": "a" * 40, "status": "passed", "collected": 90, "failed": []})
    opp = proven(store, PERF_CRITERIA)
    revoke(store, opp.id, "an artifact", criteria="perf-v3", evidence="x", by="person")
    text = "\n".join(render_text(build(store, "w")))
    assert "the project's own checks at aaaaaaaaaaaa: passed (90 collected, 0 failed)" in text
    assert "revoked" in text and "an artifact" in text
