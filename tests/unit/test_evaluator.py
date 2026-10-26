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
        (GREEN, summary(["t"], [], []), TestOutcome.INCONCLUSIVE),
        (summary(["t"], [], []), summary(["t"], ["t"], ["t"]), TestOutcome.PRE_EXISTING),
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
