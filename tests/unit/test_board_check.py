"""The harness's board checker (bench/ecosystem/board_check.py): its rules, on synthetic pages."""

from __future__ import annotations

from typing import Any

import pytest

from bench.ecosystem.board_check import contrast, judge, red
from bench.ecosystem.board_lab import stock

pytestmark = pytest.mark.unit
TRUE = {"B01": {"supply": 5, "picks": 9, "shortfall": 4}, "B02": {"supply": 9, "picks": 3, "shortfall": 0}}


def state(sid: str, text: str, bg: str, y: float = 10) -> dict[str, Any]:
    style = {"color": "rgb(255, 255, 255)", "font_px": 14, "opacity": 1, "visibility": "visible", "display": "block"}
    return {"id": sid, "text": text, "background": bg, **style, "box": {"x": 900, "y": y, "w": 80, "h": 26}}


def page(states: dict[str, list[dict[str, Any]]], seen: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = [
        {"index": 0, "cells": ["B01", "Zone A", "5", "9", "SHORT 4"], "box": {"x": 0, "y": 0, "w": 1200, "h": 50},
         "states": states.get("B01", [])},
        {"index": 1, "cells": ["B02", "Zone A", "9", "3", "OK"], "box": {"x": 0, "y": 50, "w": 1200, "h": 50},
         "states": states.get("B02", [])},
    ]  # fmt: skip
    return {"rows": rows, "seen": seen}


def test_colour_rules() -> None:
    assert red((198, 40, 40, 1)) and red([211, 47, 47]) and not red((46, 158, 68)) and not red((198, 40, 40, 0))
    assert not red((255, 230, 230)) and contrast((198, 40, 40), (255, 255, 255)) > 4.5


def test_a_visible_red_badge_on_its_row_is_flagged_and_an_ok_row_is_not() -> None:
    hit = [{"visible": 1.0, "rgb": [198, 40, 40]}]
    judged = judge(
        page({"B01": [state("0-0", "SHORT 4", "rgb(198, 40, 40)")], "B02": [state("1-0", "OK", "rgb(227, 241, 229)",
             60)]}, {"0-0": hit, "1-0": [{"visible": 1.0, "rgb": [227, 241, 229]}]}),
        TRUE,
    )  # fmt: skip
    assert judged["problems"] == [] and judged["bins"]["B01"]["flagged"] and not judged["bins"]["B02"]["false_flag"]


@pytest.mark.parametrize(
    ("bg", "seen", "y", "fails"),
    [
        ("rgb(227, 241, 229)", {"visible": 1.0, "rgb": [227, 241, 229]}, 10, "alert_style"),  # styled as OK
        ("rgb(198, 40, 40)", {"visible": 0.4, "rgb": [255, 248, 214]}, 10, "visible"),  # 60 % covered
        ("rgb(198, 40, 40)", {"visible": 1.0, "rgb": [198, 40, 40]}, 70, "bound"),  # drawn on the next row
        ("rgb(198, 40, 40)", {"visible": 1.0, "rgb": [240, 240, 240]}, 10, "alert_pixels"),  # the screen disagrees
    ],
)
def test_each_rule_fails_on_its_own(bg: str, seen: dict[str, Any], y: float, fails: str) -> None:
    judged = judge(page({"B01": [state("0-0", "SHORT 4", bg, y)]}, {"0-0": [seen]}), TRUE)
    assert not judged["bins"]["B01"]["flagged"] and fails in judged["problems"][0]


def test_a_red_alert_on_a_row_that_is_not_short_is_a_false_flag() -> None:
    judged = judge(
        page({"B02": [state("1-0", "OK", "rgb(198, 40, 40)", 60)]}, {"1-0": [{"visible": 1.0, "rgb": [198, 40, 40]}]}),
        TRUE,
    )
    assert judged["bins"]["B02"]["false_flag"]


def test_the_board_lab_data_has_every_kind_and_picks_outside_the_window() -> None:
    bins, picks, kinds = stock(7, 24)
    assert sorted(set(kinds.values())) == ["equal", "fine", "reserved", "short"] and len(bins) == 24
    assert any(days > 7 for _, _, days in picks)
