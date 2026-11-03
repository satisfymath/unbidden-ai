"""What an improvement is measured by: a typed metric, and one measurement of it at the base and at the candidate.

Campaign 12 showed the record could say only one kind of improvement in numbers (request latency, in
`samples_*_ms`); a fix or a crash proven gone lived in free-text reasons. Every verdict now carries its measurements:
the metric's name, unit and direction, the threshold and the source, and the values on both sides, so a pull
request, a report and an independent verifier read the same claim (`docs/ROAD-TO-1.0.md` §2)."""

from __future__ import annotations

from typing import Literal

from unbidden.contracts.common import Contract

Direction = Literal["lower", "higher"]
ImprovementClass = Literal["latency", "correctness", "reliability", "security", "quality"]


class Metric(Contract):
    name: str  # "request_ms", "findings", "defect_reproduced", "error_ratio", "advisories", "flaky_failures"
    unit: str  # "ms", "count", "failing rounds", "share", "seconds"
    direction: Direction  # which way is better
    improvement: ImprovementClass
    threshold: str  # the rule a change must meet, in words: "≥ 20% faster, p < 0.05, A/A within ±10%"
    source: str  # who measured it: "perf-v4 sessions in the sandbox", "the team's ruff", "the new test, 3 rounds"


class Measurement(Contract):
    metric: Metric
    base: float
    head: float
    effect: float | None = None  # relative change in the better direction: 0.42 = 42% better; negative is worse
    interval: tuple[float, float] | None = None  # 95% interval of the effect, when the method gives one
    p: float | None = None
    n_base: int | None = None  # samples, sessions or rounds behind each side
    n_head: int | None = None
    met: bool = False  # the threshold was met

    def summary(self) -> str:
        better = "lower" if self.metric.direction == "lower" else "higher"
        effect = f", {self.effect:+.0%}" if self.effect is not None else ""
        p = f", p = {self.p:.2g}" if self.p is not None else ""
        verdict = "met" if self.met else "not met"
        values = f"{self.base:g} → {self.head:g} {self.metric.unit}"
        return f"{self.metric.name}: {values} ({better} is better{effect}{p}); {self.metric.threshold}: {verdict}"


# The metrics each class of improvement is judged by (`docs/bench/campaign13/MEASURES.md` §2).
REQUEST_MS = Metric(name="request_ms", unit="ms (session median)", direction="lower", improvement="latency",
                    threshold="≥ 20% faster, permutation p < 0.05, A/A within ±10%, confirmed in new sessions",
                    source="perf-v4 sessions in the sandbox")  # fmt: skip
FINDINGS = Metric(name="findings", unit="count", direction="lower", improvement="quality",
                  threshold="every targeted finding gone, none new, no test regressed",
                  source="the project's own analyzer in the sandbox")  # fmt: skip
DEFECT_REPRODUCED = Metric(name="defect_reproduced", unit="failing rounds", direction="lower",
                           improvement="correctness",
                           threshold="the new test fails at the base and passes with the change; no regression",
                           source="the reproducing test in the sandbox")  # fmt: skip
ERROR_RATIO = Metric(name="error_ratio", unit="share of requests", direction="lower", improvement="reliability",
                     threshold="lower with non-overlapping 95% Wilson intervals over ≥ 100 requests",
                     source="probes and metrics at each deploy")  # fmt: skip
ADVISORIES = Metric(name="advisories", unit="count", direction="lower", improvement="security",
                    threshold="the targeted advisory gone, none new, no test regressed",
                    source="the vulnerability scanner in the sandbox")  # fmt: skip
FLAKY_FAILURES = Metric(name="flaky_failures", unit="failing reruns", direction="lower", improvement="quality",
                        threshold="0 failures in 10 reruns where the base failed at least once",
                        source="the team's suite rerun in the sandbox")  # fmt: skip


def relative(base: float, head: float, direction: Direction) -> float | None:
    """The relative change in the better direction, or None from a zero base."""
    if base == 0:
        return None
    return (base - head) / base if direction == "lower" else (head - base) / base
