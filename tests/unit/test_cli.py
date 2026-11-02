from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from unbidden.cli import main

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_creates_a_supervised_workspace_outside_git(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["created"] is True
    mandate = (repo / ".unbidden" / "mandate.yaml").read_text()
    assert "open_pull_requests: require_approval" in mandate
    assert "merge_pull_requests: deny" in mandate
    assert "repository: acme/shop" in mandate
    assert ".unbidden/" in (repo / ".git" / "info" / "exclude").read_text()
    assert main(["init", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["created"] is False


def test_commands_need_a_workspace(repo: Path) -> None:
    assert main(["inbox"]) == 2


def test_kill_switch_round_trip(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init"])
    main(["kill", "testing"])
    assert (repo / ".unbidden" / "KILL").exists()
    main(["resume"])
    assert not (repo / ".unbidden" / "KILL").exists()


def test_modes_switch_autonomy_but_never_merging(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init"])
    capsys.readouterr()
    assert main(["mode", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "supervised"
    assert main(["mode", "autopilot"]) == 0
    mandate = (repo / ".unbidden" / "mandate.yaml").read_text()
    assert "open_pull_requests: allow" in mandate and "merge_pull_requests: deny" in mandate
    assert main(["mode", "autonomous"]) == 2  # no deploy steps, no drill
    main(["mode", "supervised"])
    assert "open_pull_requests: require_approval" in (repo / ".unbidden" / "mandate.yaml").read_text()


def _commit(repo: Path) -> None:
    """`status` and home name the head: give the repository one commit."""
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)  # fmt: skip


def test_status_reports_the_agent_and_the_kill_switch(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init"])
    _commit(repo)
    capsys.readouterr()
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["kill_switch"] is False and data["stale"] is False
    assert data["agent"]["running"] is False and data["agent"]["pid"] is None and data["agent"]["jobs_running"] == 0
    assert main(["status"]) == 0
    assert "agent: not running" in capsys.readouterr().out


@pytest.fixture
def models_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """The start guard sees the recommended local model as installed, without an Ollama on this machine."""
    import unbidden.runtime as runtime
    from unbidden.brain.hardware import detect, recommend

    tag = recommend(detect(), set()).model.tag
    monkeypatch.setattr(runtime, "installed_models", lambda url: {tag})


def test_start_refuses_without_the_options_model_and_force_starts(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, standin_argv, reaper: list[int]
) -> None:
    """The agent must not run where every cycle would fail: the default mandate (local-first) needs Ollama."""
    import unbidden.runtime as runtime
    from unbidden.daemon import service

    main(["init"])
    _commit(repo)
    monkeypatch.setattr(runtime, "installed_models", lambda url: set())
    monkeypatch.setattr(service, "agent_command", lambda interval_s, extra_args=(): standin_argv(repo / ".unbidden"))
    capsys.readouterr()
    assert main(["start", "--json"]) == 4
    refused = json.loads(capsys.readouterr().out)
    assert refused["started"] is False
    assert [c["check"] for c in refused["refused"]] == ["ollama"]
    assert refused["refused"][0]["fix"] == "unbidden setup models"
    assert main(["start"]) == 4
    errors = " ".join(capsys.readouterr().err.split())
    assert "not started: the agent would fail every cycle here" in errors and "ollama: not reachable" in errors
    assert main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["agent"]["running"] is False
    assert main(["start", "--force", "--json"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["started"] is True
    reaper.append(started["pid"])
    assert main(["stop", "--json"]) == 0


def test_start_status_stop_round_trip(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, standin_argv, reaper: list[int],
    models_ready: None,
) -> None:  # fmt: skip
    from unbidden.daemon import owner, service

    main(["init"])
    _commit(repo)
    monkeypatch.setattr(service, "agent_command", lambda interval_s, extra_args=(): standin_argv(repo / ".unbidden"))
    capsys.readouterr()
    assert main(["start", "--json"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["started"] is True
    reaper.append(started["pid"])
    assert main(["start"]) == 0
    assert f"already running: pid {started['pid']} since" in capsys.readouterr().out
    assert main(["status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["agent"]["running"] is True and status["agent"]["pid"] == started["pid"]
    assert main([]) == 0  # home names the agent too
    assert f"agent: running pid {started['pid']}" in capsys.readouterr().out
    assert main(["stop"]) == 0
    out = capsys.readouterr().out
    assert f"agent stopped (pid {started['pid']}," in out and "forced" not in out
    assert owner.holder(repo / ".unbidden") is None and not (repo / ".unbidden" / "KILL").exists()
    assert main(["stop"]) == 0
    assert "agent is not running" in capsys.readouterr().out
    assert main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["agent"]["running"] is False


def test_kill_stop_freezes_and_ends_the_agent(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, standin_argv, reaper: list[int],
    models_ready: None,
) -> None:  # fmt: skip
    from unbidden.daemon import owner, service

    main(["init"])
    monkeypatch.setattr(service, "agent_command", lambda interval_s, extra_args=(): standin_argv(repo / ".unbidden"))
    capsys.readouterr()
    assert main(["start", "--json"]) == 0
    reaper.append(json.loads(capsys.readouterr().out)["pid"])
    assert main(["kill", "--stop", "testing"]) == 0
    out = capsys.readouterr().out
    assert "Kill switch engaged" in out and "agent stopped" in out
    assert (repo / ".unbidden" / "KILL").exists() and owner.holder(repo / ".unbidden") is None
    main(["resume"])
    assert not (repo / ".unbidden" / "KILL").exists()


def test_executing_commands_refuse_while_another_process_owns_the_workspace(
    repo: Path, capsys: pytest.CaptureFixture[str], standin_argv, reaper: list[int]
) -> None:
    main(["init"])
    child = subprocess.Popen(standin_argv(repo / ".unbidden"), stdout=subprocess.PIPE, text=True)
    reaper.append(child.pid)
    assert child.stdout is not None and child.stdout.readline().strip() == "held"
    capsys.readouterr()
    for argv in (["scan"], ["try", "opp_x"], ["map"], ["probe", "pkg"], ["investigate", "a", "b"], ["watch"]):
        assert main(argv) == 2, argv
        errors = " ".join(capsys.readouterr().err.split())  # the console wraps long lines
        assert f"another unbidden is working in this workspace: pid {child.pid} (unbidden watch, started" in errors
        assert "stop it: unbidden stop" in errors
    assert main(["mode"]) == 0  # a decision does not take the lock
    assert main(["map", "--connectors", "--json"]) == 0  # nor does reading
    child.terminate()
    child.wait(timeout=10)
    _commit(repo)
    capsys.readouterr()
    assert main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["agent"]["running"] is False


def test_the_app_opens_only_on_a_real_terminal(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unbidden.cli import _wants_app, build_parser

    args = build_parser().parse_args([])
    assert not _wants_app(args)  # pytest's captured stdout is not a terminal
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("UNBIDDEN_PLAIN", raising=False)
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): type("S", (), {"columns": 120})())
    assert _wants_app(args)
    assert not _wants_app(build_parser().parse_args(["--plain"]))
    assert not _wants_app(build_parser().parse_args(["--json"]))
    monkeypatch.setenv("UNBIDDEN_PLAIN", "1")
    assert not _wants_app(args)
    monkeypatch.delenv("UNBIDDEN_PLAIN")
    monkeypatch.setenv("TERM", "dumb")
    assert not _wants_app(args)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(80, 24): type("S", (), {"columns": 50})())
    assert not _wants_app(args)


def test_app_without_a_terminal_says_so(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init"])
    assert main(["app"]) == 2
    assert "interactive terminal" in capsys.readouterr().err


def test_no_command_still_shows_the_text_home_under_pytest(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init"])
    _commit(repo)
    assert main([]) == 0
    assert "next:" in capsys.readouterr().out
