"""Criteria v4 (stage 10): what a promotion to L4 needs, on the seven cases the stage asks for."""

from __future__ import annotations

import pytest

from unbidden.lab.perfstats import judge_promotion

pytestmark = pytest.mark.unit

BASE = [10.0, 10.2, 9.9, 10.1]
QUIET = ([10.0, 10.1], [10.05, 9.95])  # A/A: well inside 10%
FAST = [7.0, 7.1, 6.9, 7.05]  # 30% faster


def test_a_real_improvement_with_its_mechanism_function_control_and_confirmation_is_promoted() -> None:
    p = judge_promotion((BASE, FAST), mechanism=True, functional_same=True, control=QUIET,
                        confirmation=(BASE, FAST), confirmation_mechanism=True)  # fmt: skip
    assert p.outcome == "improved"


def test_the_unchanged_candidate_is_no_relevant_change() -> None:
    p = judge_promotion((BASE, [10.05, 9.95, 10.1, 10.0]), functional_same=True)
    assert p.outcome == "no_relevant_change"


def test_an_irrelevant_index_is_not_promoted_even_if_faster() -> None:
    # the index is never used during the measured calls: the speed-up is not attributed to it
    p = judge_promotion((BASE, FAST), mechanism=False, mechanism_note="0 scans", functional_same=True, control=QUIET,
                        confirmation=(BASE, FAST), confirmation_mechanism=False)  # fmt: skip
    assert p.outcome == "inconclusive"


def test_a_workload_that_does_not_use_the_column_shows_no_mechanism() -> None:
    # the same as above from the measurement's side; the workload itself is refused earlier (validation)
    p = judge_promotion((BASE, BASE[::-1]), mechanism=False, functional_same=True)
    assert p.outcome in ("no_relevant_change", "inconclusive") and not p.improved


def test_a_slower_candidate_is_a_regression() -> None:
    p = judge_promotion((BASE, [12.0, 12.2, 11.9, 12.1]), functional_same=True)
    assert p.outcome == "regression"


def test_near_the_threshold_a_first_pass_is_not_enough() -> None:
    near = [7.9, 7.95, 7.85, 7.9]  # 21% faster in the first sessions
    unconfirmed = [8.3, 8.25, 8.35, 8.3]  # 17% in the confirmation
    p = judge_promotion((BASE, near), mechanism=True, functional_same=True, control=QUIET,
                        confirmation=(BASE, unconfirmed), confirmation_mechanism=True)  # fmt: skip
    assert p.outcome == "inconclusive" and any("not confirmed" in r for r in p.reasons)


def test_a_faster_wrong_answer_is_a_regression() -> None:
    p = judge_promotion((BASE, FAST), mechanism=True, functional_same=False,
                        functional_note="3 of 23 responses differ")  # fmt: skip
    assert p.outcome == "regression" and "differs" in p.reasons[-1]


def test_a_noisy_control_or_a_missing_stage_never_promotes() -> None:
    noisy = ([10.0, 10.1], [8.6, 8.7])  # the environment alone moved 14%
    assert judge_promotion((BASE, FAST), mechanism=True, functional_same=True, control=noisy,
                           confirmation=(BASE, FAST)).outcome == "inconclusive"  # fmt: skip
    assert judge_promotion((BASE, FAST), mechanism=True, functional_same=None, control=QUIET,
                           confirmation=(BASE, FAST)).outcome == "inconclusive"  # fmt: skip
    assert judge_promotion((BASE, FAST), mechanism=True, functional_same=True, control=QUIET).outcome == "inconclusive"


def test_many_candidates_at_one_commit_raise_the_bar() -> None:
    # 4 sessions per arm: the smallest exact p is 1/70 (0.014); with four candidates confirmed at the commit the
    # alpha is 0.0125, out of reach: the fourth best of several tries is not promoted on a lucky draw
    p = judge_promotion((BASE, FAST), mechanism=True, functional_same=True, control=QUIET,
                        confirmation=(BASE, FAST), confirmation_mechanism=True, family=4)  # fmt: skip
    assert p.outcome == "inconclusive"
