"""Campaign 13, WS4: a deploy's failed requests are judged like its latency, and a fix is judged by them."""

from __future__ import annotations

import pytest

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.opportunity import Opportunity
from unbidden.observe.impact import Impact, Round, judge_errors, wilson
from unbidden.observe.live import classify_outcome, improvement_class

pytestmark = pytest.mark.unit


def _rounds(n: int, failed_every: int | None) -> list[Round]:
    out = []
    for i in range(n):
        statuses = tuple(500 if failed_every and (i * 5 + k) % failed_every == 0 else 200 for k in range(5))
        out.append(Round("v", statuses, tuple(10.0 for _ in statuses)))
    return out


def test_wilson_is_sound_at_zero_and_narrows_with_n() -> None:
    low, high = wilson(0, 100)
    assert low == 0.0 and 0.03 < high < 0.04
    assert wilson(10, 1000)[1] - wilson(10, 1000)[0] < wilson(1, 100)[1] - wilson(1, 100)[0]
    assert wilson(0, 0) == (0.0, 1.0)


def test_failed_requests_fewer_after_the_deploy_is_an_improvement() -> None:
    before, fixed = _rounds(40, failed_every=5), _rounds(42, failed_every=None)  # 20% failing → none
    judged = judge_errors("GET /x", before, fixed)
    assert judged.impact is Impact.IMPROVED and judged.ratio_before == pytest.approx(0.2) and judged.errors_after == 0
    assert judge_errors("GET /x", fixed, before).impact is Impact.DEGRADED
    assert judge_errors("GET /x", before, _rounds(42, failed_every=5)).impact is Impact.HEALTHY
    assert judge_errors("GET /x", _rounds(5, 5), _rounds(7, None)).impact is Impact.INSUFFICIENT


def test_a_fix_is_judged_by_failures_a_speed_up_by_latency() -> None:
    def opp(improvement: str | None) -> Opportunity:
        measurements = [{"metric": {"improvement": improvement}}] if improvement else []
        return Opportunity(source="s", category="bugs", title="t", summary="s", dedup_key="k",
                           evidence=[EvidenceRef(kind="file", locator="a")],
                           details={"verdict": {"measurements": measurements}})  # fmt: skip

    assert improvement_class(opp("correctness")) == "correctness"
    assert improvement_class(opp(None)) == "latency"  # verdicts before typed measurements were latency
    judged = [judge_errors("GET /x", _rounds(40, 5), _rounds(42, None))]
    from types import SimpleNamespace

    from unbidden.operate import ledger

    deploy = SimpleNamespace(commit_status="verified", commit_reason="", initiated_by="unbidden")
    original = ledger.is_attributable
    ledger.is_attributable = lambda d: True  # type: ignore[assignment]
    try:
        result, why = classify_outcome(judged, deploy, deploy, [])  # type: ignore[arg-type]
    finally:
        ledger.is_attributable = original  # type: ignore[assignment]
    assert result == "positive" and "failed 40/200 (20.0%) → 0/200" in why[0]
