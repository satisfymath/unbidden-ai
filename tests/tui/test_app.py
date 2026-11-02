"""The app, headless: it opens on a workspace, answers commands, toggles the kill switch, answers a question by
rules (no model, US$0), and quits on a second Ctrl+C. Nothing here starts an agent."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.cli import main
from unbidden.tui.app import UnbiddenApp
from unbidden.tui.widgets import Feed, Header, StatusBar
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)  # fmt: skip
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--json"]) == 0
    return Workspace.find()


def _text(feed: Feed) -> str:
    return "\n".join("".join(segment.text for segment in line) for line in feed.lines)


async def test_the_app_opens_with_the_brand_the_state_and_the_bar(ws: Workspace) -> None:
    app = UnbiddenApp(ws, planner="rule")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        assert "UNBiDDEN" in app.query_one(Header).line
        bar = app.query_one(StatusBar).line
        assert "○˙" in bar and "agent off" in bar and "supervised" in bar
        text = _text(app.query_one(Feed))
        assert "Intelligence that doesn't wait for instructions." in text
        assert "> Proving." in text and "Where things stand." in text and "Nothing found yet." in text


async def test_commands_help_kill_resume_and_the_unknown_one(ws: Workspace) -> None:
    app = UnbiddenApp(ws, planner="rule")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        await pilot.press(*"/help", "enter")
        await pilot.pause(0.2)
        text = _text(app.query_one(Feed))
        assert "/approve <id> [--hours N]" in text and "Quitting stops no agent." in text
        await pilot.press(*"/kill from the test", "enter")
        await pilot.pause(0.2)
        assert (ws.dir / "KILL").exists() and "KILL SWITCH" in app.query_one(StatusBar).line
        await pilot.press(*"/resume", "enter")
        await pilot.pause(0.2)
        assert not (ws.dir / "KILL").exists()
        await pilot.press(*"/nope", "enter")
        await pilot.pause(0.2)
        assert "No command /nope." in _text(app.query_one(Feed))
        await pilot.press(*"/why", "enter")
        await pilot.pause(0.2)
        assert "Usage: /why <id>" in _text(app.query_one(Feed))


async def test_a_question_is_answered_by_rules_without_a_model(ws: Workspace) -> None:
    app = UnbiddenApp(ws, planner="rule")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        await pilot.press(*"what did you find", "enter")
        for _ in range(80):
            await pilot.pause(0.25)
            if not app._turn_running:
                break
        text = _text(app.query_one(Feed))
        assert "you > what did you find" in text
        assert "inform · rules · no model" in text


async def test_ctrl_c_arms_then_quits_and_leaves_no_kill_file(ws: Workspace) -> None:
    app = UnbiddenApp(ws, planner="rule")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+c")
        await pilot.pause(0.1)
        assert "press Ctrl+C again to quit" in app.query_one(StatusBar).line
        await pilot.press("ctrl+c")
        await pilot.pause(0.2)
    assert app.return_value == 0
    assert not (ws.dir / "KILL").exists()
