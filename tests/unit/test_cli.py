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
