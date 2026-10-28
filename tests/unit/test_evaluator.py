from __future__ import annotations

import pytest

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.experiment import TestOutcome, TestSummary
from unbidden.lab.evaluator import classify_tests, evaluate_fix

pytestmark = pytest.mark.unit


def summary(*rounds: list[str]) -> TestSummary:
    return TestSummary(rounds=len(rounds), failed_per_round=list(rounds))


GREEN = summary([], [], [])


@pytest.mark.parametrize(
    ("baseline", "candidate", "expected"),
    [
        (GREEN, GREEN, TestOutcome.PASSED),
        (GREEN, summary(["t"], ["t"], ["t"]), TestOutcome.REGRESSION),
        # A test that newly fails in some candidate rounds fails more often with the change: not validated.
        (GREEN, summary(["t"], [], []), TestOutcome.FLAKIER),
        # Was pre_existing (and L4) before tests-v2: failing 1 of 3 rounds before and 3 of 3 after is worse (A2).
        (summary(["t"], [], []), summary(["t"], ["t"], ["t"]), TestOutcome.FLAKIER),
        # Failures no more frequent than before are pre-existing, also when the change makes one rarer.
        (summary(["t"], ["t"], ["t"]), summary(["t"], ["t"], ["t"]), TestOutcome.PRE_EXISTING),
        (summary(["t"], ["t"], ["t"]), summary(["t"], [], []), TestOutcome.PRE_EXISTING),
        (None, GREEN, TestOutcome.INCONCLUSIVE),
    ],
)
def test_classify(baseline: TestSummary | None, candidate: TestSummary, expected: TestOutcome) -> None:
    assert classify_tests(baseline, candidate)[0] is expected


def test_fix_with_green_suite_is_level_4() -> None:
    j = evaluate_fix(
        targeted=["a", "a"], before=["a", "a", "b"], after=["b"], baseline_tests=GREEN, candidate_tests=GREEN,
        has_test_suite=True,
    )  # fmt: skip
    assert j.improved and j.evidence_level is EvidenceLevel.FUNCTIONAL_VALIDATION


def test_new_finding_or_remaining_target_is_no_improvement() -> None:
    j = evaluate_fix(
        targeted=["a"], before=["a", "b"], after=["b", "b"], baseline_tests=GREEN, candidate_tests=GREEN,
        has_test_suite=True,
    )  # fmt: skip
    assert not j.improved and "1 new finding(s) appeared" in j.reasons
    j = evaluate_fix(
        targeted=["a"], before=["a"], after=["a"], baseline_tests=GREEN, candidate_tests=GREEN, has_test_suite=True
    )
    assert not j.improved


def test_without_tests_the_ceiling_is_level_3() -> None:
    j = evaluate_fix(
        targeted=["a"], before=["a"], after=[], baseline_tests=None, candidate_tests=None, has_test_suite=False
    )
    assert j.improved and j.evidence_level is EvidenceLevel.LAB_IMPROVEMENT
    assert any("no test suite" in c for c in j.caveats)


def test_regression_blocks() -> None:
    j = evaluate_fix(
        targeted=["a"], before=["a"], after=[], baseline_tests=GREEN, candidate_tests=summary(["t"], ["t"], ["t"]),
        has_test_suite=True,
    )  # fmt: skip
    assert not j.improved and j.tests is TestOutcome.REGRESSION


SUITE_DOWN = TestSummary(rounds=3, failed_per_round=[["<suite>"]] * 3, round_status=["infra_failed"] * 3)


def test_a_suite_that_did_not_run_validates_nothing() -> None:
    # A1: both sides' suite failing to start was "pre_existing" and L4 before tests-v2.
    j = evaluate_fix(targeted=["a"], before=["a"], after=[], baseline_tests=SUITE_DOWN, candidate_tests=SUITE_DOWN,
                     has_test_suite=True)  # fmt: skip
    assert j.tests is TestOutcome.INFRA_FAILURE and j.evidence_level is EvidenceLevel.LAB_IMPROVEMENT
    assert any("did not run" in c for c in j.caveats)


def test_an_older_record_with_an_unattributed_failure_on_both_sides_is_not_validated() -> None:
    legacy = summary(["<suite>"], ["<suite>"], ["<suite>"])  # written before round statuses were kept
    assert classify_tests(legacy, legacy)[0] is TestOutcome.INFRA_FAILURE


def test_a_suite_that_collected_nothing_validates_nothing() -> None:
    # A4: pytest's exit 5 used to count as a clean pass.
    empty = TestSummary(rounds=3, failed_per_round=[[], [], []], round_status=["not_collected"] * 3,
                        collected_per_round=[0, 0, 0])  # fmt: skip
    ran = TestSummary(rounds=3, failed_per_round=[[], [], []], round_status=["ran"] * 3, collected_per_round=[12] * 3)
    assert classify_tests(ran, empty)[0] is TestOutcome.NOT_RUN
    assert classify_tests(empty, ran)[0] is TestOutcome.NOT_RUN
    assert classify_tests(ran, ran)[0] is TestOutcome.PASSED


def test_every_lab_takes_its_level_from_one_rule() -> None:
    from unbidden.lab.evaluator import level_for

    # A3: RobustLab gave L4 to anything that was not a regression, inconclusive included.
    for outcome in (TestOutcome.FLAKIER, TestOutcome.INCONCLUSIVE, TestOutcome.NOT_RUN, TestOutcome.INFRA_FAILURE):
        assert level_for(True, outcome, suite_ran=True) is EvidenceLevel.LAB_IMPROVEMENT
    for outcome in (TestOutcome.PASSED, TestOutcome.PRE_EXISTING):
        assert level_for(True, outcome, suite_ran=True) is EvidenceLevel.FUNCTIONAL_VALIDATION
        assert level_for(True, outcome, suite_ran=False) is EvidenceLevel.LAB_IMPROVEMENT
    assert level_for(False, TestOutcome.PASSED, suite_ran=True) is EvidenceLevel.REPRODUCTION
