"""A page check's answer that cannot be used never becomes success (stage 6, fix B).

Reproduced on c804aaf: an answer that was not JSON gave `unreadable: true` with no discrepancies, and the goal ended
`page_ok`; a discrepancy naming an unknown row was dropped without a word. Before and after a repair."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.guardian import Goal, Mandate
from unbidden.director import presentation
from unbidden.director.goals import GoalRun
from unbidden.store import Store

pytestmark = pytest.mark.unit
WANT = {"B01": {"fields": {"picks_7d": 9}, "value": 4.0, "flag": True},
        "B02": {"fields": {"picks_7d": 1}, "value": -3.0, "flag": False}}  # fmt: skip
ROWS = [
    {"row": 0, "cells": ["B01", "SHORT 4"], "box": {"y": 0, "h": 40}, "marks": []},
    {"row": 1, "cells": ["B02", "OK"], "box": {"y": 40, "h": 40}, "marks": []},
]
PAGE = {"rows": ROWS, "overlays": []}
RED_MARK = {"text": "SHORT 4", "background": "rgb(198, 40, 40)", "color": "rgb(255, 255, 255)", "font_px": 14,
            "visible": 1, "covered_by": {}, "visibility": "visible"}  # fmt: skip
# After the repair: every objective condition holds (B01 marked red, B02 plain, both once).
FIXED = {"rows": [{**ROWS[0], "marks": [RED_MARK]}, ROWS[1]], "overlays": []}
GOOD_EMPTY = '{"discrepancies": [], "cause": "none"}'
ONE = (
    '{"discrepancies": [{"key": "B01", "kind": "not_flagged", "evidence": "green"}], "cause": "css", '
    '"flag": {"text_contains": "SHORT", "background": "red"}}'
)


@dataclass
class FakeScan:
    page: dict[str, Any] = field(default_factory=lambda: PAGE)
    screenshots: list[tuple[int, bytes]] = field(default_factory=list[tuple[int, bytes]])

    def digests(self) -> dict[str, str]:
        return {}


class Brain:
    def __init__(self, *answers: str) -> None:
        self.answers, self.calls, self.served_by = list(answers), 0, {}

    async def complete(self, request: Any) -> Any:
        self.calls += 1
        return type("R", (), {"content": self.answers.pop(0)})()


@pytest.mark.parametrize(
    ("answers", "status"),
    [
        (["I think the page looks fine.", "still not json"], "page_inconclusive"),  # the reproduced case
        (['{"discrepancies": []}', '{"discrepancies": []}'], "page_inconclusive"),  # JSON, not the schema
        (
            ['{"discrepancies": [{"key": "B99", "kind": "not_flagged", "evidence": "x"}], "cause": "c"}'] * 2,
            "page_inconclusive",
        ),  # a row the data does not have: not dropped quietly
        (["not json", GOOD_EMPTY], "page_ok"),  # one bounded retry, then a usable answer
        ([GOOD_EMPTY], "page_ok"),
    ],
)
def test_an_unusable_answer_before_a_repair_is_inconclusive(
    answers: list[str], status: str, store: Store, mandate: Mandate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("unbidden.lab.ui.scan", lambda url, out: FakeScan())
    run, brain = GoalRun(goal="g"), Brain(*answers)
    asyncio.run(presentation.pursue_page(brain, store, mandate, Goal(id="g", statement="s"), run, WANT, "u",
                                         repo=tmp_path, artifacts=tmp_path, perception="dom", window="w",
                                         source="synthetic"))  # fmt: skip
    assert run.status == status
    assert brain.calls <= presentation.CHECK_ATTEMPTS


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / "board.css").write_text(".short { background: green; }\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    return repo


def test_an_unusable_answer_after_a_repair_is_not_a_fix_and_the_change_is_withdrawn(
    store: Store, mandate: Mandate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deploys: list[tuple[str, bool]] = []

    async def propose(*_: Any) -> tuple[dict[str, str], str, dict[str, Any]]:
        return {"board.css": ".short { background: red; }\n"}, "the badge is green", {}

    def deploy(repo: Path, store: Any, mandate: Any, commit: str, *, reason: str, rollback: bool = False) -> Any:
        deploys.append((commit, rollback))
        return type("D", (), {"ok": True, "log": ""})()

    scans = iter([FakeScan(), FakeScan(page=FIXED)])
    monkeypatch.setattr("unbidden.lab.ui.scan", lambda url, out: next(scans))
    monkeypatch.setattr(presentation, "propose", propose)
    monkeypatch.setattr(presentation, "run_checks", lambda tree, mandate: {"ok": True, "log": ""})
    monkeypatch.setattr("unbidden.operate.deploy.deploy", deploy)
    run, brain = GoalRun(goal="g"), Brain(ONE, "the page is fixed now", "really fixed")
    asyncio.run(presentation.pursue_page(brain, store, mandate, Goal(id="g", statement="s", bounds={"max_changes": 1}),
                                         run, WANT, "u", repo=repo, artifacts=tmp_path / "art", perception="dom",
                                         window="w", source="synthetic"))  # fmt: skip
    assert run.status == "page_inconclusive"
    assert [rollback for _, rollback in deploys] == [False, True]  # deployed, then the base redeployed


def test_read_answer_says_why() -> None:
    keys = {"B01", "B02"}
    assert presentation.read_answer(ONE, keys)[1] is None
    assert "not JSON" in (presentation.read_answer("nope", keys)[1] or "")
    assert "schema" in (presentation.read_answer('{"discrepancies": [{"key": "B01"}], "cause": ""}', keys)[1] or "")
    assert "B77" in (presentation.read_answer(ONE.replace("B01", "B77"), keys)[1] or "")


@pytest.mark.parametrize(
    ("css", "name"),
    [
        ("rgb(198, 40, 40)", "red"),
        ("rgb(253, 236, 234)", "very light red (pale pink)"),  # what two repairs called a red badge
        ("rgb(227, 241, 229)", "very light green"),
        ("rgb(31, 95, 44)", "dark green"),
        ("rgba(0, 0, 0, 0)", "transparent"),
        ("rgb(255, 255, 255)", "white"),
    ],
)
def test_colours_are_named_as_a_person_would(css: str, name: str) -> None:
    assert presentation.colour_name(css) == name


def test_observations_name_each_marks_colours() -> None:
    page = {"rows": [{"row": 0, "cells": ["B01", "SHORT 4"], "box": {"y": 0, "h": 40}, "marks": [
        {"text": "SHORT 4", "background": "rgb(253, 236, 234)", "color": "rgb(179, 38, 30)", "font_px": 14,
         "visible": 1, "covered_by": {}, "visibility": "visible"}]}], "overlays": []}  # fmt: skip
    assert "bg rgb(253, 236, 234) (very light red (pale pink))" in presentation.observed_lines(page)
