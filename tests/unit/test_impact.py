from __future__ import annotations

import random

import pytest

from unbidden.observe.impact import Impact, Round, judge_endpoint, judge_endpoint_v1, overall

pytestmark = pytest.mark.unit


def rounds(center: float, n: int, seed: int, status: int = 200, version: str = "v") -> list[Round]:
    rng = random.Random(seed)
    return [Round(version, (status,) * 5, tuple(center * rng.uniform(0.85, 1.15) for _ in range(5))) for _ in range(n)]


def test_degradation_and_improvement_are_both_detected() -> None:
    assert judge_endpoint("GET /x", rounds(20, 15, 1), rounds(60, 17, 2), 15).impact is Impact.DEGRADED
    assert judge_endpoint("GET /x", rounds(60, 15, 1), rounds(20, 17, 2), 15).impact is Impact.IMPROVED


def test_same_build_twice_is_healthy_and_small_shifts_are_not_claimed() -> None:
    assert judge_endpoint("GET /x", rounds(20, 15, 1), rounds(20, 17, 2), 15).impact is Impact.HEALTHY
    # v1's absolute 10 ms floor ignored +6 ms on a 20 ms endpoint; v2 scales the floor to the endpoint's noise.
    assert judge_endpoint_v1("GET /x", rounds(20, 15, 1), rounds(26, 17, 2), 15).impact is Impact.HEALTHY
    assert judge_endpoint("GET /x", rounds(20, 15, 1), rounds(26, 17, 2), 15).impact is Impact.DEGRADED
    assert judge_endpoint("GET /x", rounds(20, 15, 1), rounds(22, 17, 2), 15).impact is Impact.HEALTHY  # +10%


def test_not_enough_rounds_is_never_healthy() -> None:
    result = judge_endpoint("GET /x", rounds(20, 15, 1), rounds(20, 5, 2), 15)
    assert result.impact is Impact.INSUFFICIENT
    assert overall([result]) is Impact.INSUFFICIENT


def test_errors_after_a_deploy_are_an_outage_and_throttling_is_not() -> None:
    assert judge_endpoint("GET /x", rounds(20, 15, 1), rounds(20, 25, 2, status=502), 15).impact is Impact.OUTAGE
    throttled = judge_endpoint("GET /x", rounds(20, 15, 1), rounds(20, 25, 2, status=429), 15)
    assert throttled.impact is Impact.INSUFFICIENT


def test_overall_verdict() -> None:
    healthy = judge_endpoint("a", rounds(20, 15, 1), rounds(20, 17, 2), 15)
    degraded = judge_endpoint("b", rounds(20, 15, 1), rounds(60, 17, 2), 15)
    assert overall([healthy, degraded]) is Impact.DEGRADED
    assert overall([healthy]) is Impact.HEALTHY


def test_a_degradation_that_outlives_its_deploys_is_found_against_the_oldest_samples() -> None:
    from unbidden.observe.impact import sustained

    baseline = [40.0, 42.0, 38.0, 41.0, 39.0, 43.0, 40.0, 41.0]
    assert sustained(baseline, [2500.0, 2480.0, 2510.0]) is not None  # raciona: 2.5 s for hours
    assert sustained(baseline, [2500.0, 41.0, 2510.0]) is None  # not persistent
    assert sustained(baseline, [70.0, 72.0, 71.0]) is None  # +30 ms: under the absolute floor
    assert sustained(baseline[:3], [2500.0] * 3) is None  # too little history to judge
