"""Perception is scored by what was named, against the checker's rows (stage 6, fix C).

Found by review on c804aaf: `score_found` said `detected: true` whenever any row was named on a defective state,
even if none of the named rows was wrong."""

from __future__ import annotations

import pytest

from bench.ecosystem.board_eval import score_found

pytestmark = pytest.mark.unit
WRONG = ["B01", "B02"]


def named(*keys: str) -> list[dict[str, str]]:
    return [{"key": k, "kind": "not_flagged", "evidence": "x"} for k in keys]


def test_a_report_naming_only_healthy_rows_hits_nothing() -> None:
    s = score_found(named("B09"), WRONG)
    assert s["alerted"] is True and s["hit_any"] is False and s["hit_all"] is False
    assert s["false_rows"] == ["B09"] and s["precision"] == 0.0 and s["recall"] == 0.0


def test_right_mixed_and_partial_reports() -> None:
    right = score_found(named("B01", "B02"), WRONG)
    assert right["hit_any"] and right["hit_all"] and right["precision"] == 1.0 and right["recall"] == 1.0
    mixed = score_found(named("B01", "B09"), WRONG)
    assert mixed["hit_any"] and not mixed["hit_all"] and mixed["precision"] == 0.5 and mixed["recall"] == 0.5
    assert mixed["false_rows"] == ["B09"] and mixed["missed_rows"] == ["B02"]


def test_absent_reports_and_healthy_states() -> None:
    silent = score_found([], WRONG)
    assert silent["alerted"] is False and silent["hit_any"] is False and silent["recall"] == 0.0
    healthy_quiet, healthy_loud = score_found([], []), score_found(named("B03"), [])
    assert healthy_quiet["false_alarm"] is False and healthy_quiet["hit_any"] is None
    assert healthy_loud["false_alarm"] is True and healthy_loud["false_rows"] == ["B03"]


def test_an_inconclusive_answer_is_none_of_the_others() -> None:
    s = score_found([], WRONG, conclusive=False)
    assert s["inconclusive"] and s["alerted"] is None and s["hit_any"] is None and s["false_alarm"] is None
