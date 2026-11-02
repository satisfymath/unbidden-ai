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


async def test_tab_completes_a_command_and_never_leaves_the_prompt(ws: Workspace) -> None:
    from unbidden.tui.widgets import Prompt

    app = UnbiddenApp(ws, planner="rule")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        prompt = app.query_one(Prompt)
        await pilot.press("tab")  # empty: nothing to complete, the focus stays
        assert app.focused is prompt and prompt.value == ""
        await pilot.press(*"/sta", "tab")
        await pilot.pause(0.1)
        assert prompt.value == "/start " and app.focused is prompt
        prompt.value = "/s"
        await pilot.press("tab")  # several commands start with /s: the text stays, the suggestion shows the first
        assert prompt.value == "/s" or prompt.value.startswith("/s")
        prompt.value = ""
        await pilot.press(*"/kill from tab", "enter")
        await pilot.pause(0.2)
        assert (ws.dir / "KILL").exists()


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


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    """A git repository with no .unbidden yet."""
    import unbidden.cli as cli
    import unbidden.runtime as runtime
    from unbidden.brain import hardware

    monkeypatch.setattr(runtime, "installed_models", lambda url: set())
    from unbidden.setup import discover as discover_

    monkeypatch.setattr(discover_, "_ollama_installed", lambda: False)
    monkeypatch.setattr(discover_, "_verify", lambda slug: None)
    monkeypatch.setattr(cli, "meta_api_status", lambda key, get=None: (False, "the model listing refuses the key"))
    monkeypatch.setattr(
        hardware, "detect", lambda: hardware.Machine(total_gb=16.0, apple_silicon=True, chip="test", gpu_gb=0.0)
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)  # fmt: skip
    monkeypatch.chdir(repo)
    return Workspace.find()


async def test_a_first_run_opens_setup_and_ctrl_c_keeps_the_answers(bare: Workspace) -> None:
    from textual.widgets import Input, OptionList, RichLog

    from unbidden.tui.screens import SetupScreen

    app = UnbiddenApp(bare, planner="rule")
    async with app.run_test(size=(100, 30)) as pilot:
        for _ in range(60):
            await pilot.pause(0.1)
            if isinstance(app.screen, SetupScreen) and app.screen._pending is not None:
                break
        assert isinstance(app.screen, SetupScreen)
        log = "\n".join("".join(s.text for s in line) for line in app.screen.query_one("#log", RichLog).lines)
        assert "Unbidden is not set up in this repository yet" in log and "Found" in log
        assert "repository acme/shop" in log and "GitHub access: none" in log
        menu = app.screen.query_one("#choices", OptionList)
        assert app.screen._pending[0].key == "github_access"  # type: ignore[index]
        assert menu.display and menu.option_count == 3 and menu.highlighted == 0  # gh, token, skip; gh first
        await pilot.press("down", "down", "enter")  # skip: no terminal in a test
        for _ in range(40):
            await pilot.pause(0.1)
            if app.screen._pending is not None and app.screen._pending[0].key == "MODEL_API_KEY":  # type: ignore[attr-defined]
                break
        assert not menu.display and app.screen.query_one("#answer", Input).password  # a secret, hidden
        await pilot.press("enter")  # no key: the local option
        for _ in range(40):
            await pilot.pause(0.1)
            if app.screen._pending is not None and app.screen._pending[0].key == "mode":  # type: ignore[attr-defined]
                break
        assert menu.display and menu.option_count == 3 and menu.highlighted == 0  # supervised is the default
        await pilot.press("ctrl+c")
        for _ in range(40):
            await pilot.pause(0.1)
            if not isinstance(app.screen, SetupScreen):
                break
        assert not isinstance(app.screen, SetupScreen)
        assert (bare.dir / "setup.json").exists()
        await pilot.pause(0.3)
        text = " ".join(_text(app.query_one(Feed)).split())  # the feed wraps long lines
        assert "Setup is not finished; your answers are kept in .unbidden/setup.json. /setup resumes it." in text
        assert "UNBiDDEN" in app.query_one(Header).line
        assert not app.query_one(Input).password
