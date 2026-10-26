"""Impact judgement for one deploy, pure: no I/O, no clock but the samples' own.

A *round* is one probe pass over an endpoint: a few requests on one version. Percentiles are taken on the
pooled individual latencies of a window, never on one round (the p95 of five requests is their maximum), and
the test compares round medians, since requests within a round are not independent.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from scipy.stats import mannwhitneyu  # pyright: ignore[reportUnknownVariableType]

ALPHA = 0.01
MIN_EFFECT = 0.20
MIN_DELTA_MS = 10.0
WARMUP_ROUNDS = 2
ERROR_RATE = 0.01
MIN_REQUESTS_FOR_ERRORS = 100
MIN_ERRORS = 3

CRITERIA: dict[str, float | int | str] = {
    "test": "one-sided Mann-Whitney U on round medians, each direction",
    "alpha": ALPHA,
    "min_effect": MIN_EFFECT,
    "min_delta_ms": MIN_DELTA_MS,
    "warmup_rounds_dropped": WARMUP_ROUNDS,
    "error_rate": f"5xx over {ERROR_RATE:.0%} with at least {MIN_REQUESTS_FOR_ERRORS} requests and {MIN_ERRORS} errors",
}


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
        return [ms for ms, st in zip(self.latencies_ms, self.statuses, strict=True) if 200 <= st < 500 and st != 429]


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


def judge_endpoint(target: str, before: list[Round], after: list[Round], min_rounds: int) -> EndpointImpact:
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
    slower: Any = mannwhitneyu(a_medians, b_medians, alternative="greater")
    faster: Any = mannwhitneyu(b_medians, a_medians, alternative="greater")
    delta = p50_a - p50_b
    impact, p_value, reasons = Impact.HEALTHY, None, []
    if float(slower.pvalue) < ALPHA and delta >= MIN_DELTA_MS and delta / p50_b >= MIN_EFFECT:
        impact, p_value = Impact.DEGRADED, float(slower.pvalue)
        reasons.append(f"median {p50_b:.1f} → {p50_a:.1f} ms ({delta / p50_b:+.0%}), p = {p_value:.2g}")
    elif float(faster.pvalue) < ALPHA and -delta >= MIN_DELTA_MS and -delta / p50_b >= MIN_EFFECT:
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
