"""Pure judgement of a fix experiment. Criteria are fixed here, before any candidate is measured."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.experiment import TestOutcome, TestSummary

CRITERIA: dict[str, float | int | str] = {
    "targeted_findings_gone": "all",
    "new_findings_allowed": 0,
    "test_rounds_per_side": 3,
    "regression": "fails in every candidate round and in no baseline round",
}


@dataclass(frozen=True)
class FixJudgement:
    improved: bool
    evidence_level: EvidenceLevel
    tests: TestOutcome
    reasons: list[str]
    caveats: list[str]


def classify_tests(baseline: TestSummary | None, candidate: TestSummary | None) -> tuple[TestOutcome, list[str]]:
    """Flaky tests are named for what they are instead of being blamed on the candidate."""
    if baseline is None or candidate is None:
        return TestOutcome.INCONCLUSIVE, ["the test suite did not run on both sides"]
    base_fail = Counter(name for round_ in baseline.failed_per_round for name in set(round_))
    cand_fail = Counter(name for round_ in candidate.failed_per_round for name in set(round_))
    regressions = sorted(n for n, c in cand_fail.items() if c == candidate.rounds and base_fail[n] == 0)
    if regressions:
        return TestOutcome.REGRESSION, [f"regression: {n}" for n in regressions[:10]]
    flaky = sorted(n for n, c in cand_fail.items() if base_fail[n] == 0 and c < candidate.rounds)
    if flaky:
        return TestOutcome.INCONCLUSIVE, [f"failed in some candidate rounds only: {n}" for n in flaky[:10]]
    if any(base_fail.values()):
        return TestOutcome.PRE_EXISTING, [f"fails before the change too: {n}" for n in sorted(base_fail)[:10]]
    return TestOutcome.PASSED, []


def evaluate_fix(
    *,
    targeted: list[str],
    before: list[str],
    after: list[str],
    baseline_tests: TestSummary | None,
    candidate_tests: TestSummary | None,
    has_test_suite: bool,
) -> FixJudgement:
    """`targeted`, `before` and `after` are finding fingerprints as multisets (repeats count)."""
    reasons: list[str] = []
    caveats: list[str] = []
    after_count = Counter(after)
    still = sorted(fp for fp in set(targeted) if after_count[fp] > 0)
    if still:
        reasons.append(f"{len(still)} targeted finding(s) remain")
    new = after_count - Counter(before)
    if new:
        reasons.append(f"{sum(new.values())} new finding(s) appeared")
    tests, notes = classify_tests(baseline_tests, candidate_tests) if has_test_suite else (TestOutcome.INCONCLUSIVE, [])
    if tests is TestOutcome.REGRESSION:
        reasons.extend(notes)
    else:
        caveats.extend(notes)
    if not has_test_suite:
        caveats.append("the repository has no test suite unbidden can run; behavior was not checked")
    improved = not reasons
    if not improved:
        level = EvidenceLevel.REPRODUCTION
    elif has_test_suite and tests in (TestOutcome.PASSED, TestOutcome.PRE_EXISTING):
        level = EvidenceLevel.FUNCTIONAL_VALIDATION
    else:
        level = EvidenceLevel.LAB_IMPROVEMENT
    return FixJudgement(improved, level, tests, reasons, caveats)
