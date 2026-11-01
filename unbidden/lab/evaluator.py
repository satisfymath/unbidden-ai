"""Pure judgement of a fix experiment. Criteria are fixed here, before any candidate is measured."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.experiment import (
    INFRA_FAILED,
    NOT_COLLECTED,
    SUITE,
    VALIDATING,
    TestOutcome,
    TestSummary,
)

CRITERIA: dict[str, float | int | str] = {
    "version": "tests-v2",
    "targeted_findings_gone": "all",
    "new_findings_allowed": 0,
    "test_rounds_per_side": 3,
    "regression": "fails in every candidate round and in no baseline round",
    "flakier": "fails in more candidate rounds than baseline rounds",
    "validated": "the suite ran and collected tests on both sides, and nothing fails more often with the change",
}


@dataclass(frozen=True)
class FixJudgement:
    improved: bool
    evidence_level: EvidenceLevel
    tests: TestOutcome
    reasons: list[str]
    caveats: list[str]


def classify_tests(baseline: TestSummary | None, candidate: TestSummary | None) -> tuple[TestOutcome, list[str]]:
    """The one judgement of a suite run on both sides, for every lab. In order: a suite that did not run says
    nothing; a suite that collected nothing says nothing; a test that newly fails in every candidate round is a
    regression; a test that fails more often with the change is flakier; failures no more frequent than before are
    pre-existing; nothing failing is passed. Only the last two validate a change."""
    if baseline is None or candidate is None:
        return TestOutcome.INCONCLUSIVE, ["the test suite did not run on both sides"]
    for side, summary in (("baseline", baseline), ("candidate", candidate)):
        infra = [i + 1 for i in range(summary.rounds) if summary.status(i) == INFRA_FAILED]
        if infra:
            return TestOutcome.INFRA_FAILURE, [
                f"the suite did not run on the {side} (round {', '.join(map(str, infra))})"
            ]
        empty = [i + 1 for i in range(summary.rounds)
                 if summary.status(i) == NOT_COLLECTED or (i < len(summary.collected_per_round)
                                                         and summary.collected_per_round[i] == 0)]  # fmt: skip
        if empty:
            return TestOutcome.NOT_RUN, [
                f"the suite collected no test on the {side} (round {', '.join(map(str, empty))})"
            ]
    base_fail = Counter(name for round_ in baseline.failed_per_round for name in set(round_))
    cand_fail = Counter(name for round_ in candidate.failed_per_round for name in set(round_))
    if base_fail[SUITE] and cand_fail[SUITE]:
        return TestOutcome.INFRA_FAILURE, ["the suite fails on both sides without naming a test: nothing to compare"]
    regressions = sorted(n for n, c in cand_fail.items() if c == candidate.rounds and base_fail[n] == 0)
    if regressions:
        return TestOutcome.REGRESSION, [f"regression: {n}" for n in regressions[:10]]
    worse = sorted(n for n, c in cand_fail.items() if c > base_fail[n])
    if worse:
        return TestOutcome.FLAKIER, [
            f"fails in {cand_fail[n]} of {candidate.rounds} candidate rounds, {base_fail[n]} of {baseline.rounds} "
            f"before: {n}"
            for n in worse[:10]
        ]
    if any(base_fail.values()):
        return TestOutcome.PRE_EXISTING, [f"fails before the change too: {n}" for n in sorted(base_fail)[:10]]
    return TestOutcome.PASSED, []


def validates(tests: TestOutcome) -> bool:
    """Whether a suite outcome lets a change reach functional validation (L4)."""
    return tests in VALIDATING


def level_for(improved: bool, tests: TestOutcome, *, suite_ran: bool) -> EvidenceLevel:
    """The evidence level of a measured change, the same in every lab: shown in the lab (L3) when it improved, and
    functionally validated (L4) only when the repository's suite ran on both sides and validates it."""
    if not improved:
        return EvidenceLevel.REPRODUCTION
    return EvidenceLevel.FUNCTIONAL_VALIDATION if suite_ran and validates(tests) else EvidenceLevel.LAB_IMPROVEMENT


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
    return FixJudgement(improved, level_for(improved, tests, suite_ran=has_test_suite), tests, reasons, caveats)
