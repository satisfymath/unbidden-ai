"""Campaign 13, WS2: the claim is typed, the pull request says what the mode will do, priorities count by their
words, and a perf-v4 verdict is current."""

from __future__ import annotations

import pytest

from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.experiment import Experiment, TestOutcome, Verdict
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.metric import FINDINGS, REQUEST_MS, Measurement, relative
from unbidden.contracts.opportunity import Opportunity
from unbidden.director.decide import category_value
from unbidden.lab.revoke import pending
from unbidden.publish.proposal import build_body

pytestmark = pytest.mark.unit


def test_a_measurement_says_its_metric_values_and_threshold() -> None:
    m = Measurement(metric=REQUEST_MS, base=14.69, head=2.77, effect=relative(14.69, 2.77, "lower"), p=0.008, met=True)
    text = m.summary()
    assert text.startswith("request_ms: 14.69 → 2.77 ms") and "+81%" in text and "p = 0.008" in text
    assert text.endswith(": met")
    assert relative(0, 1, "lower") is None and relative(2, 3, "higher") == 0.5


def _opp() -> Opportunity:
    return Opportunity(id="opp_1", source="ruff", category="lint", title="F401 in pkg/", summary="s", dedup_key="k",
                       evidence=[EvidenceRef(kind="file", locator="a")],
                       details={"findings": [], "fingerprints": ["f1"]})  # fmt: skip


def test_the_pull_request_carries_the_claim_and_says_what_the_mode_will_do() -> None:
    experiment = Experiment(opportunity_id="opp_1", base_sha="a" * 40, candidate_patch_sha256="x",
                            findings_before=["f1", "f2"], findings_after=["f2"])  # fmt: skip
    verdict = Verdict(experiment_id=experiment.id, improved=True, evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
                      criteria={}, tests=TestOutcome.PASSED, reasons=["gone"],
                      measurements=[Measurement(metric=FINDINGS, base=2, head=1, met=True)])  # fmt: skip
    person = build_body(_opp(), experiment, verdict, "model")
    assert "### Claim\n- findings: 2 → 1 count" in person and "a person decides" in person
    product = build_body(_opp(), experiment, verdict, "model", merges=True)
    assert "Unbidden merges it once the team's CI is green on this exact commit" in product
    assert "a person decides" not in product


def test_priorities_count_by_the_words_they_use() -> None:
    plain = Mandate(workspace="w", priorities=[])
    worded = Mandate(workspace="w", priorities=["performance of reads as data grows", "consistency"])
    assert category_value("performance", worded) == pytest.approx(category_value("performance", plain) * 1.5)
    assert category_value("bugs", worded) == pytest.approx(category_value("bugs", plain) * 1.5)
    assert category_value("reliability", plain) > 0 and category_value("dependencies", plain) > 0


def test_a_perf_v4_verdict_is_current_not_pending_revalidation() -> None:
    opp = _opp()
    opp.evidence_level = EvidenceLevel.FUNCTIONAL_VALIDATION
    opp.details = {"verdict": {"criteria": {"min_median_improvement": 0.2, "version": "perf-v4"}}}
    assert pending(opp) is None
    opp.details = {"verdict": {"criteria": {"min_median_improvement": 0.2, "version": "perf-v1"}}}
    assert pending(opp) is not None
