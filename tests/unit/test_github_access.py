"""The GitHub token is found, not asked: Unbidden's env file, the environment, or the gh CLI's sign-in (held in
memory, never copied)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from unbidden.guardian.credentials import broker, reset
from unbidden.setup import github_access, machine
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("MODEL_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"):  # never the developer's own
        monkeypatch.delenv(name, raising=False)
    reset()
    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)
    return repo


def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, token: str | None) -> Path:
    """A `gh` on PATH that is signed in (prints the token) or signed out (exit 1, like the real one)."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    script = bin_ / "gh"
    body = f'#!/bin/sh\necho "{token}"\n' if token else '#!/bin/sh\necho "no oauth token found" >&2\nexit 1\n'
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv(github_access.OPT_OUT, raising=False)
    github_access.forget_gh_token()
    return bin_


def test_the_gh_sign_in_is_held_for_the_process_and_never_written(repo: Path, tmp_path: Path, monkeypatch) -> None:
    fake_gh(tmp_path, monkeypatch, token="gho_fake_0123456789")
    access = github_access.github_access(Workspace(repo))
    assert access.source == "gh" and access.found
    assert broker().get("GITHUB_TOKEN", "github") == "gho_fake_0123456789"
    assert not machine.machine_env().exists() and not (repo / ".unbidden" / ".env").exists()


def test_signed_out_gh_or_no_gh_means_none(repo: Path, tmp_path: Path, monkeypatch) -> None:
    fake_gh(tmp_path, monkeypatch, token=None)
    assert github_access.github_access(Workspace(repo)).source is None
    github_access.forget_gh_token()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert github_access.github_access(Workspace(repo)).source is None


def test_a_saved_token_wins_over_gh(repo: Path, tmp_path: Path, monkeypatch) -> None:
    fake_gh(tmp_path, monkeypatch, token="gho_fake_0123456789")
    machine.write_env(machine.machine_env(), {"GITHUB_TOKEN": "ghp_saved_0123456789"})
    assert github_access.github_access(Workspace(repo)).source == "file"
    assert broker().get("GITHUB_TOKEN", "github") == "ghp_saved_0123456789"


def test_an_environment_token_is_the_env_source(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_0123456789")
    assert github_access.github_access(Workspace(repo)).source == "env"
    assert broker().get("GITHUB_TOKEN", "github") == "ghp_env_0123456789"


def test_load_env_falls_back_to_gh_once_per_process(repo: Path, tmp_path: Path, monkeypatch) -> None:
    bin_ = fake_gh(tmp_path, monkeypatch, token="gho_fake_0123456789")
    ws = Workspace(repo)
    ws.load_env()
    assert broker().get("GITHUB_TOKEN", "github") == "gho_fake_0123456789"
    (bin_ / "gh").write_text("#!/bin/sh\nexit 1\n")  # gh changes its mind: the process keeps what it holds
    ws.load_env()
    assert broker().has("GITHUB_TOKEN")
