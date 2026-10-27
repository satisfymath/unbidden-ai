"""Impact judgement for one deploy, pure: no I/O, no clock but the samples' own.

A *round* is one probe pass over an endpoint: a few requests on one version. Percentiles are taken on the
pooled individual latencies of a window, never on one round (the p95 of five requests is their maximum), and
the test compares round medians, since requests within a round are not independent.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from scipy.stats import mannwhitneyu  # pyright: ignore[reportUnknownVariableType]

ALPHA = 0.01
MIN_EFFECT = 0.20
MIN_DELTA_MS = 10.0  # v1 floor
MIN_DELTA_MS_V2 = 0.2  # practical resolution of a loopback round trip
NOISE_MADS = 3.0
WARMUP_ROUNDS = 2
ERROR_RATE = 0.01
MIN_REQUESTS_FOR_ERRORS = 100
MIN_ERRORS = 3

_SHARED: dict[str, float | int | str] = {
    "test": "one-sided Mann-Whitney U on round medians, each direction",
    "alpha": ALPHA,
    "min_effect": MIN_EFFECT,
    "warmup_rounds_dropped": WARMUP_ROUNDS,
    "error_rate": f"5xx over {ERROR_RATE:.0%} with at least {MIN_REQUESTS_FOR_ERRORS} requests and {MIN_ERRORS} errors",
}
CRITERIA_V1: dict[str, float | int | str] = {"criteria_version": "v1", **_SHARED, "min_delta_ms": MIN_DELTA_MS}
CRITERIA_V2: dict[str, float | int | str] = {
    "criteria_version": "v2",
    **_SHARED,
    "min_delta_ms": f"max({MIN_DELTA_MS_V2} ms, {NOISE_MADS:g} MADs of the baseline's round medians)",
}
# What `judge_endpoint` applies by default, and what every verdict records. Verdicts stored before this record
# `min_delta_ms: 10` without a version, although they were judged under v2 from D-014 on.
CRITERIA = CRITERIA_V2


class Impact(StrEnum):
    IMPROVED = "improved"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OUTAGE = "outage"
    INSUFFICIENT = "insufficient_evidence"


@dataclass(frozen=True)
class Round:
    version: str
    statuses: tuple[int, ...]
    latencies_ms: tuple[float, ...]

    @property
    def served(self) -> list[float]:
        """Latencies of requests the service actually served (not throttled, not failed)."""
        return [ms for ms, st in zip(self.latencies_ms, self.statuses, strict=True) if 200 <= st < 400]


@dataclass(frozen=True)
class EndpointImpact:
    target: str
    impact: Impact
    p50_before: float | None
    p50_after: float | None
    p95_before: float | None
    p95_after: float | None
    p_value: float | None
    rounds_before: int
    rounds_after: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {k: (v.value if isinstance(v, Impact) else v) for k, v in self.__dict__.items()}


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low, high = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _errors(rounds: list[Round]) -> tuple[int, int]:
    statuses = [s for r in rounds for s in r.statuses if s != 429]
    return sum(1 for s in statuses if s >= 500 or s == 0), len(statuses)


def judge_endpoint_v1(target: str, before: list[Round], after: list[Round], min_rounds: int) -> EndpointImpact:
    """Criteria v1 (absolute floor of 10 ms), kept to re-read verdicts recorded under them."""
    return judge_endpoint(target, before, after, min_rounds, floor=lambda _: MIN_DELTA_MS)


def scale_aware_floor(baseline_round_medians: list[float]) -> float:
    """Criteria v2: a change must exceed the baseline's own round-to-round noise (3 MADs), and 0.2 ms."""
    center = statistics.median(baseline_round_medians)
    mad = statistics.median(abs(m - center) for m in baseline_round_medians)
    return max(MIN_DELTA_MS_V2, NOISE_MADS * mad)


def judge_endpoint(
    target: str,
    before: list[Round],
    after: list[Round],
    min_rounds: int,
    floor: Callable[[list[float]], float] = scale_aware_floor,
) -> EndpointImpact:
    before = before[-min_rounds * 2 :]
    after = after[WARMUP_ROUNDS:]
    errors, total = _errors(after)
    if total >= MIN_REQUESTS_FOR_ERRORS and errors >= MIN_ERRORS and errors / total > ERROR_RATE:
        return EndpointImpact(
            target,
            Impact.OUTAGE,
            None,
            None,
            None,
            None,
            None,
            len(before),
            len(after),
            (f"{errors} of {total} requests failed after the deploy",),
        )
    b_medians = [statistics.median(r.served) for r in before if r.served]
    a_medians = [statistics.median(r.served) for r in after if r.served]
    if len(b_medians) < min_rounds or len(a_medians) < min_rounds:
        return EndpointImpact(
            target,
            Impact.INSUFFICIENT,
            None,
            None,
            None,
            None,
            None,
            len(b_medians),
            len(a_medians),
            (f"need {min_rounds} judged rounds per side",),
        )
    pooled_b = [ms for r in before for ms in r.served]
    pooled_a = [ms for r in after for ms in r.served]
    p50_b, p50_a = statistics.median(pooled_b), statistics.median(pooled_a)
    min_delta = floor(b_medians)
    slower: Any = mannwhitneyu(a_medians, b_medians, alternative="greater")
    faster: Any = mannwhitneyu(b_medians, a_medians, alternative="greater")
    delta = p50_a - p50_b
    impact, p_value, reasons = Impact.HEALTHY, None, []
    if float(slower.pvalue) < ALPHA and delta >= min_delta and delta / p50_b >= MIN_EFFECT:
        impact, p_value = Impact.DEGRADED, float(slower.pvalue)
        reasons.append(f"median {p50_b:.1f} → {p50_a:.1f} ms ({delta / p50_b:+.0%}), p = {p_value:.2g}")
    elif float(faster.pvalue) < ALPHA and -delta >= min_delta and -delta / p50_b >= MIN_EFFECT:
        impact, p_value = Impact.IMPROVED, float(faster.pvalue)
        reasons.append(f"median {p50_b:.1f} → {p50_a:.1f} ms ({delta / p50_b:+.0%}), p = {p_value:.2g}")
    else:
        reasons.append(f"median {p50_b:.1f} → {p50_a:.1f} ms: within the criteria, no change claimed")
    return EndpointImpact(
        target,
        impact,
        p50_b,
        p50_a,
        _quantile(pooled_b, 0.95),
        _quantile(pooled_a, 0.95),
        p_value,
        len(b_medians),
        len(a_medians),
        tuple(reasons),
    )


def overall(endpoints: list[EndpointImpact]) -> Impact:
    """One verdict per deploy. Any outage or degradation wins; HEALTHY needs every endpoint judged."""
    kinds = {e.impact for e in endpoints}
    for bad in (Impact.OUTAGE, Impact.DEGRADED):
        if bad in kinds:
            return bad
    if not endpoints or Impact.INSUFFICIENT in kinds:
        return Impact.INSUFFICIENT
    return Impact.IMPROVED if Impact.IMPROVED in kinds else Impact.HEALTHY


# Sustained degradation (ported from the prototype's observer, D-062 there): a deploy every twenty minutes reset the
# baseline to already-degraded samples and a p95 of 2.5 s went unnoticed for four hours. The oldest part of a long
# window is a baseline no deploy can reset.
SUSTAINED_REL, SUSTAINED_ABS_MS, SUSTAINED_MAD_K, SUSTAINED_PERSISTENCE = 1.5, 50.0, 4.0, 3
SUSTAINED_CRITERIA: dict[str, float | int | str] = {
    "criteria_version": "sustained-v1",
    "baseline": "the oldest samples of the window, whatever deploys happened since",
    "threshold": f"max({SUSTAINED_REL}x median, median + {SUSTAINED_ABS_MS} ms, "
    f"median + {SUSTAINED_MAD_K} x 1.4826 MAD)",
    "persistence": f"the newest {SUSTAINED_PERSISTENCE} samples all above it",
}


@dataclass(frozen=True)
class Sustained:
    baseline_median: float
    threshold: float
    recent_median: float

    @property
    def factor(self) -> float:
        return self.recent_median / self.baseline_median if self.baseline_median else float("inf")


def sustained(baseline: list[float], recent: list[float], *, min_baseline: int = 6) -> Sustained | None:
    """Pure: whether the newest samples all sit above a threshold set by the oldest ones."""
    if len(baseline) < min_baseline or len(recent) < SUSTAINED_PERSISTENCE:
        return None
    median = statistics.median(baseline)
    mad = statistics.median(abs(v - median) for v in baseline)
    threshold = max(median * SUSTAINED_REL, median + SUSTAINED_ABS_MS, median + SUSTAINED_MAD_K * 1.4826 * mad)
    newest = recent[-SUSTAINED_PERSISTENCE:]
    if not all(v > threshold for v in newest):
        return None
    return Sustained(median, threshold, statistics.median(newest))
