"""The wizard runs unchanged behind the app's IO adapter: answers arrive through Futures, a cancelled Future is the
person's interruption and keeps the answers given so far."""

from __future__ import annotations

import io
import subprocess
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from unbidden.setup.wizard import Options, SetupError, load_answers, run
from unbidden.tui.setup_io import INTERRUPTED, AppIO, Ask, LineSink
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "i"], check=True)  # fmt: skip
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
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


class Answers:
    """Resolves each Ask from a table, in the worker's own thread; records what was asked."""

    def __init__(self, table: dict[str, Any], *, cancel_at: str | None = None) -> None:
        self.table = table
        self.cancel_at = cancel_at
        self.asked: list[Ask] = []

    def __call__(self, ask: Ask) -> Future[Any]:
        self.asked.append(ask)
        future: Future[Any] = Future()
        if ask.key == self.cancel_at:
            future.cancel()
        else:
            future.set_result(self.table.get(ask.key, ""))
        return future


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=120, force_terminal=False, color_system=None), buf


def test_the_wizard_completes_through_the_adapter(repo: Path) -> None:
    out, buf = _console()
    answers = Answers({"github_access": "skip", "MODEL_API_KEY": "", "mode": "supervised", "apply": "y"})
    code = run(Workspace(repo), Options(), out, io=AppIO(answers))
    assert code == 0, buf.getvalue()
    assert (repo / ".unbidden" / "mandate.yaml").exists()
    assert [(a.key, a.kind) for a in answers.asked] == [
        ("github_access", "choice"), ("MODEL_API_KEY", "secret"), ("mode", "choice"), ("apply", "confirm")
    ]  # fmt: skip
    assert "model option: local" in buf.getvalue()


def test_an_empty_answer_takes_the_default_and_a_bad_choice_asks_again(repo: Path) -> None:
    _out, _ = _console()
    seen: list[str] = []

    def ask(a: Ask) -> Future[Any]:
        f: Future[Any] = Future()
        seen.append(a.key)
        f.set_result("nope" if a.key == "models" and seen.count("models") == 1 else "")
        return f

    io_ = AppIO(ask)
    assert io_.choice("models", "?", ("local", "mixed", "api"), "mixed") == "mixed"  # "nope" then "" -> default
    assert seen.count("models") == 2
    assert io_.confirm("apply", "?", True) is True
    assert io_.text("budget", "?", "1") == "1"


def test_a_cancelled_future_keeps_the_answers_and_returns_2(repo: Path) -> None:
    out, buf = _console()
    answers = Answers({"github_access": "skip", "MODEL_API_KEY": ""}, cancel_at="mode")
    code = run(Workspace(repo), Options(), out, io=AppIO(answers))
    assert code == 2
    kept = load_answers(Workspace(repo))
    assert kept.completed == ["found", "models"] and kept.models == "local"
    assert "setup.json" in buf.getvalue() or (repo / ".unbidden" / "setup.json").exists()


def test_the_adapter_names_the_interruption() -> None:
    def ask(a: Ask) -> Future[Any]:
        f: Future[Any] = Future()
        f.cancel()
        return f

    with pytest.raises(SetupError, match=INTERRUPTED):
        AppIO(ask).text("x", "?", None)


def test_the_line_sink_splits_lines_and_flushes_the_rest() -> None:
    lines: list[str] = []
    sink = LineSink(lines.append)
    sink.write("one\ntwo\nthr")
    assert lines == ["one", "two"]
    sink.flush()
    assert lines == ["one", "two", "thr"]
