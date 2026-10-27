from __future__ import annotations

import random

import pytest

from unbidden.lab.perfstats import judge

pytestmark = pytest.mark.unit


def samples(center: float, n: int = 20, seed: int = 1) -> list[float]:
    rng = random.Random(seed)
    return [center * rng.uniform(0.9, 1.1) for _ in range(n)]


def test_clear_improvement() -> None:
    j = judge(samples(40.0), samples(5.0, seed=2))
    assert j.improved and j.p_value < 1e-6 and j.effect > 0.8 and j.ci_low > 0


def test_same_distribution_is_not_an_improvement() -> None:
    j = judge(samples(10.0), samples(10.0, seed=3))
    assert not j.improved


def test_small_effect_is_rejected_even_if_significant() -> None:
    j = judge(samples(10.0, n=200), samples(9.0, n=200, seed=4))
    assert not j.improved and any("below 20%" in r for r in j.reasons)


def test_too_few_samples() -> None:
    assert not judge([1.0] * 5, [0.5] * 5).improved
