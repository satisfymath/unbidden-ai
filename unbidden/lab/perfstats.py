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


# Criteria v3 (stage 9), fixed before any measurement under them. The unit is the session: one sandbox run with its
# own fresh database, the same image, data and resources, warm-up and samples; base and candidate sessions alternate
# in an order drawn from a seed. Samples inside one session share that session's state (caches, placement, the
# data its workload seeded) and are not independent; the B-7 false L4 on Conduit came from comparing one session of
# each (a 0.5 ms difference between two sessions passed a per-sample test).
SESSIONS_PER_ARM = 4
SESSION_ALPHA = 0.05  # with 4 sessions per arm, only a near-complete separation reaches it (exact p >= 1/70)
REGRESSION_EFFECT = 0.10  # slower by 10% or more, with the same test, is a regression
OUTCOMES = ("improved", "no_relevant_change", "regression", "inconclusive", "blocked")

SESSION_CRITERIA: dict[str, float | int | str] = {
    "version": "perf-v3",
    "unit": "session median (each session: a fresh database, the same data, warm-up then samples)",
    "sessions_per_arm": SESSIONS_PER_ARM,
    "order": "alternating base and candidate, which goes first drawn from a seed",
    "test": "exact one-sided permutation test on session medians",
    "alpha": SESSION_ALPHA,
    "min_median_improvement": MIN_EFFECT,
    "regression_if_slower_by": REGRESSION_EFFECT,
    "no_relevant_change": "the 95% bootstrap interval of the relative effect over sessions lies inside +-20%",
    "mechanism": "when the change declares one (an index), the engine must show it used during the measured calls",
}


@dataclass(frozen=True)
class SessionJudgement:
    outcome: str  # one of OUTCOMES
    p_faster: float
    p_slower: float
    median_before: float  # median of the base sessions' medians
    median_after: float
    effect: float  # relative improvement, 0.42 = 42% faster; negative is slower
    effect_low: float  # 95% bootstrap interval of the effect, resampling sessions
    effect_high: float
    reasons: list[str]

    @property
    def improved(self) -> bool:
        return self.outcome == "improved"


def _permutation_p(before: list[float], after: list[float]) -> tuple[float, float]:
    """Exact one-sided p-values that the candidate's sessions are faster, and slower, than the base's."""
    from itertools import combinations

    pooled, k = before + after, len(before)
    observed = statistics.median(before) - statistics.median(after)
    faster = slower = total = 0
    for chosen in combinations(range(len(pooled)), k):
        a = [pooled[i] for i in chosen]
        b = [pooled[i] for i in range(len(pooled)) if i not in chosen]
        diff = statistics.median(a) - statistics.median(b)
        faster += diff >= observed - 1e-12
        slower += diff <= observed + 1e-12
        total += 1
    return faster / total, slower / total


def judge_sessions(
    before: list[float], after: list[float], *, mechanism: bool | None = None, mechanism_note: str = ""
) -> SessionJudgement:
    """`before` and `after`: one median per session. `mechanism`: None when the change declares none (or it cannot be
    observed on this engine), else whether the engine showed it at work during the candidate's measured calls."""
    if len(before) < 2 or len(after) < 2:
        return SessionJudgement("blocked", 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                [f"fewer than 2 sessions per side ({len(before)}, {len(after)})"])  # fmt: skip
    p_faster, p_slower = _permutation_p(before, after)
    m_before, m_after = statistics.median(before), statistics.median(after)
    effect = (m_before - m_after) / m_before if m_before > 0 else 0.0
    rng = random.Random(SEED)
    effects = sorted(
        (lambda b, a: (statistics.median(b) - statistics.median(a)) / statistics.median(b))(
            rng.choices(before, k=len(before)), rng.choices(after, k=len(after))
        )
        for _ in range(BOOTSTRAP)
    )
    low, high = effects[int(0.025 * BOOTSTRAP)], effects[int(0.975 * BOOTSTRAP) - 1]
    reasons = [
        f"session medians {m_before:.2f} -> {m_after:.2f} ms ({effect:+.0%} faster), permutation p = {p_faster:.3g} "
        f"(slower: {p_slower:.3g}), 95% interval of the effect [{low:+.0%}, {high:+.0%}]"
    ]
    if p_slower < SESSION_ALPHA and -effect >= REGRESSION_EFFECT:
        return SessionJudgement("regression", p_faster, p_slower, m_before, m_after, effect, low, high,
                                [*reasons, f"the candidate is slower by {-effect:.0%}"])  # fmt: skip
    if p_faster < SESSION_ALPHA and effect >= MIN_EFFECT:
        if mechanism is False:
            reasons.append(
                "faster, but the change's mechanism was not seen at work during the measured calls "
                f"({mechanism_note or 'not observed'}): the difference is not attributed to it"
            )
            return SessionJudgement("inconclusive", p_faster, p_slower, m_before, m_after, effect, low, high, reasons)
        if mechanism is True:
            reasons.append(f"mechanism observed: {mechanism_note}")
        return SessionJudgement("improved", p_faster, p_slower, m_before, m_after, effect, low, high, reasons)
    if low > -MIN_EFFECT and high < MIN_EFFECT:
        return SessionJudgement("no_relevant_change", p_faster, p_slower, m_before, m_after, effect, low, high,
                                [*reasons, f"no change of {MIN_EFFECT:.0%} or more either way"])  # fmt: skip
    if p_faster >= SESSION_ALPHA:
        reasons.append(f"p = {p_faster:.3g} is not below {SESSION_ALPHA}")
    if effect < MIN_EFFECT:
        reasons.append(f"median improvement {effect:.0%} is below {MIN_EFFECT:.0%}")
    return SessionJudgement("inconclusive", p_faster, p_slower, m_before, m_after, effect, low, high, reasons)
