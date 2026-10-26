"""Pure judgement of a performance experiment. The criteria are fixed here, before any sample exists."""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from typing import Any

from scipy.stats import mannwhitneyu  # pyright: ignore[reportUnknownVariableType]

ALPHA = 0.01
MIN_EFFECT = 0.20
MIN_SAMPLES = 10
BOOTSTRAP = 2000
SEED = 7

PERF_CRITERIA: dict[str, float | int | str] = {
    "test": "one-sided Mann-Whitney U, candidate faster",
    "alpha": ALPHA,
    "min_median_improvement": MIN_EFFECT,
    "min_samples_per_side": MIN_SAMPLES,
    "bootstrap_resamples": BOOTSTRAP,
    "ci": "95% bootstrap interval of the median difference must exclude 0",
}


@dataclass(frozen=True)
class PerfJudgement:
    improved: bool
    p_value: float
    median_before: float
    median_after: float
    effect: float  # relative median improvement, 0.42 = 42% faster
    ci_low: float
    ci_high: float
    reasons: list[str]


def judge(before: list[float], after: list[float]) -> PerfJudgement:
    reasons: list[str] = []
    if len(before) < MIN_SAMPLES or len(after) < MIN_SAMPLES:
        return PerfJudgement(False, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, [f"fewer than {MIN_SAMPLES} samples per side"])
    result: Any = mannwhitneyu(before, after, alternative="greater")
    p = float(result.pvalue)
    m_before, m_after = statistics.median(before), statistics.median(after)
    effect = (m_before - m_after) / m_before if m_before > 0 else 0.0
    rng = random.Random(SEED)
    diffs = sorted(
        statistics.median(rng.choices(before, k=len(before))) - statistics.median(rng.choices(after, k=len(after)))
        for _ in range(BOOTSTRAP)
    )
    low, high = diffs[int(0.025 * BOOTSTRAP)], diffs[int(0.975 * BOOTSTRAP) - 1]
    if p >= ALPHA:
        reasons.append(f"p = {p:.2g} is not below {ALPHA}")
    if effect < MIN_EFFECT:
        reasons.append(f"median improvement {effect:.0%} is below {MIN_EFFECT:.0%}")
    if low <= 0:
        reasons.append("the 95% interval of the median difference includes 0")
    return PerfJudgement(not reasons, p, m_before, m_after, effect, low, high, reasons)
