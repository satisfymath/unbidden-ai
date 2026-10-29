"""Checker v2 (objective amendment 2): a flag is judged on the row that owns it and on the row it is painted on."""

from __future__ import annotations

from typing import Any

import pytest

from bench.ecosystem.board_check import judge_v2, shares, wrong_rows_v2

pytestmark = pytest.mark.unit
TRUE = {"B01": {"supply": 9, "picks": 3, "shortfall": 0}, "B02": {"supply": 5, "picks": 9, "shortfall": 4},
        "B03": {"supply": 9, "picks": 1, "shortfall": 0}}  # fmt: skip
RED, GREEN = "rgb(198, 40, 40)", "rgb(227, 241, 229)"


def row(i: int, name: str, states: list[dict[str, Any]], true: dict[str, Any] = TRUE) -> dict[str, Any]:
    t = true.get(name, {"supply": 0, "picks": 0})
    cells = [name, str(t["supply"]), str(t["picks"]), "x"]
    return {"index": i, "cells": cells, "box": {"x": 0, "y": 50 * i, "w": 1200, "h": 50}, "states": states}


def flag(sid: str, text: str, y: float, bg: str = RED, h: float = 26) -> dict[str, Any]:
    style = {"color": "rgb(255, 255, 255)" if bg == RED else "rgb(31, 95, 44)", "font_px": 14, "opacity": 1,
             "visibility": "visible", "display": "inline-block"}  # fmt: skip
    return {"id": sid, "text": text, "background": bg, **style, "box": {"x": 900, "y": y, "w": 80, "h": h}}


def page(
    flags_by_row: dict[int, list[dict[str, Any]]], seen: dict[str, Any] | None = None, true: dict[str, Any] = TRUE
) -> dict[str, Any]:
    rows = [row(i, n, flags_by_row.get(i, []), true) for i, n in enumerate(["B01", "B02", "B03"])]
    ids = [f["id"] for fs in flags_by_row.values() for f in fs]
    default = {i: [{"visible": 1.0, "rgb": [198, 40, 40] if "SHORT" in str(i) else [227, 241, 229]}] for i in ids}
    return {"rows": rows, "seen": seen if seen is not None else default}


def ok(i: int) -> dict[str, Any]:
    return flag(f"ok{i}", "OK", 50 * i + 12, GREEN)


def test_a_healthy_board_is_verified() -> None:
    judged = judge_v2(page({0: [ok(0)], 1: [flag("SHORT1", "SHORT 4", 62)], 2: [ok(2)]}), TRUE)
    assert judged["problems"] == [] and judged["bins"]["B02"]["flagged"]


def test_a_badge_drawn_over_the_row_above_flags_that_row_falsely_and_leaves_its_own_unsignalled() -> None:
    # B02 owns it; it is painted at y 12..38, on B01's row: what `e-shifted` did, and v1 could not see.
    judged = judge_v2(page({0: [ok(0)], 1: [flag("SHORT1", "SHORT 4", 12)], 2: [ok(2)]}), TRUE)
    assert judged["bins"]["B01"]["false_signal"] and judged["bins"]["B01"]["signalled_by"] == ["B02"]
    assert judged["bins"]["B02"]["unsignalled"] and not judged["bins"]["B02"]["flagged"]
    assert wrong_rows_v2(judged) == ["B01", "B02"]


def test_straddling_touching_and_the_share_rule() -> None:
    assert shares({"x": 900, "y": 37, "w": 80, "h": 26}, [row(0, "B01", []), row(1, "B02", [])]) == {0: 0.5, 1: 0.5}
    # half on each row: signals both (at least 0.5); a third on the next row only touches it
    judged = judge_v2(page({1: [flag("SHORT1", "SHORT 4", 83)]}), TRUE)  # 83..109: 17 px on B02, 9 on B03
    assert judged["bins"]["B02"]["flagged"] and not judged["bins"]["B03"]["false_signal"]
    assert judged["flags"][0]["touched"] == [2]
    tall = judge_v2(page({1: [flag("SHORT1", "SHORT 4", 30, h=60)]}), TRUE)  # 30..90: 20, 40 px: on B02 only
    assert tall["bins"]["B02"]["flagged"] and not tall["bins"]["B01"]["false_signal"]
    split = judge_v2(page({1: [flag("SHORT1", "SHORT 4", 40, h=120)]}), TRUE)  # 40..160: 10, 50, 50 px of 120
    assert split["flags"][0]["straddling"] and split["bins"]["B02"]["unsignalled"]


def test_a_flag_never_in_view_or_not_red_does_not_signal() -> None:
    unseen = judge_v2(page({1: [flag("SHORT1", "SHORT 4", 62)]}, seen={}), TRUE)
    assert unseen["bins"]["B02"]["unsignalled"]
    green = judge_v2(
        page({1: [flag("SHORT1", "SHORT 4", 62, GREEN)]}, seen={"SHORT1": [{"visible": 1, "rgb": [227, 241, 229]}]}),
        TRUE,
    )
    assert green["bins"]["B02"]["unsignalled"]


def test_a_short_row_lit_only_by_another_rows_flag_is_not_flagged() -> None:
    true = {**TRUE, "B03": {"supply": 1, "picks": 9, "shortfall": 8}}
    # B03 is short and has no flag of its own; B02's flag is painted on B03's row.
    judged = judge_v2(page({1: [flag("SHORT1", "SHORT 4", 112)]}, true=true), true)
    assert judged["bins"]["B03"]["borrowed_signal"] and not judged["bins"]["B03"]["flagged"]
    assert judged["bins"]["B02"]["unsignalled"]


def test_wrong_numbers_stay_wrong_rows_under_v2() -> None:
    v1 = {"bins": {"B01": {"numbers_right": False, "amount_right": True, "rows": 1}}, "problems": ["B01: numbers"]}
    judged = judge_v2(page({0: [ok(0)], 1: [flag("SHORT1", "SHORT 4", 62)], 2: [ok(2)]}), TRUE, v1)
    assert wrong_rows_v2(judged) == ["B01"]  # a v2 bug, caught on the stage 6 window state (28 rows read as 9)
