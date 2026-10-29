"""Criteria v3 for performance experiments (stage 9): the session is the unit, base and candidate alternate, and an
index must be seen at work. Development fixtures: session-to-session noise, small irrelevant improvements,
regressions, real improvements, and a speed-up without its mechanism. Plus the B-7 false L4, reproduced."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from unbidden.lab.perfstats import judge, judge_sessions

pytestmark = pytest.mark.unit
B7 = json.loads((Path(__file__).parent.parent / "fixtures" / "stage8_b7_samples.json").read_text())


def sessions(rng: random.Random, base_ms: float, factor: float, noise: float, k: int = 4) -> list[float]:
    """Session medians: each session has its own offset (state, placement, seeded data), as real sessions do."""
    return [base_ms * factor * (1 + rng.gauss(0, noise)) for _ in range(k)]


def test_the_b7_false_l4_is_reproduced_by_the_old_criteria_and_not_promoted_by_the_new() -> None:
    old = judge(B7["opp_7ec51834490b40ca"]["samples_before_ms"], B7["opp_7ec51834490b40ca"]["samples_after_ms"])
    assert old.improved and 0.20 <= old.effect < 0.25  # 2.5 -> 2.0 ms passed: one session each, per-sample test
    # Under v3, one session per side cannot decide anything.
    one_each = judge_sessions([2.5], [2.0])
    assert one_each.outcome == "blocked"
    # And with sessions that all agree it is faster, the index it adds was never used: not attributed to it.
    absent = judge_sessions([2.5, 2.6, 2.4, 2.5], [2.0, 1.9, 2.0, 2.1], mechanism=False, mechanism_note="0 scans")
    assert absent.outcome == "inconclusive" and "not attributed" in absent.reasons[-1]


def test_session_noise_alone_is_almost_never_an_improvement() -> None:
    rng = random.Random(1)
    promoted = sum(judge_sessions(sessions(rng, 10, 1, 0.12), sessions(rng, 10, 1, 0.12)).improved for _ in range(300))
    assert promoted / 300 <= 0.02  # an A/A control: the same code on both sides


def test_a_small_irrelevant_improvement_is_never_promoted() -> None:
    rng = random.Random(2)
    outcomes = [judge_sessions(sessions(rng, 10, 1, 0.03), sessions(rng, 10, 0.95, 0.03)).outcome for _ in range(200)]
    assert "improved" not in outcomes and outcomes.count("no_relevant_change") >= 150


def test_a_real_improvement_is_found_and_a_regression_is_called_one() -> None:
    rng = random.Random(3)
    better = [judge_sessions(sessions(rng, 26, 1, 0.05), sessions(rng, 26, 0.7, 0.05)) for _ in range(100)]
    assert sum(j.improved for j in better) >= 95
    worse = [judge_sessions(sessions(rng, 10, 1, 0.05), sessions(rng, 10, 1.3, 0.05)) for _ in range(100)]
    assert sum(j.outcome == "regression" for j in worse) >= 95 and not any(j.improved for j in worse)


def test_a_mechanism_seen_at_work_is_recorded_with_the_promotion() -> None:
    j = judge_sessions([8.4, 8.3, 8.6, 8.2], [1.1, 1.2, 1.0, 1.1], mechanism=True, mechanism_note="120 index scans")
    assert j.improved and "120 index scans" in j.reasons[-1]
