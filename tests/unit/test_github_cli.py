"""GitHub through the gh CLI: installed when missing (asked first, in the person's terminal), signed in with
`gh auth login --web`, the session read afterwards. A fake gh on PATH and a fake terminal stand in."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from unbidden.setup import github_access, github_cli

pytestmark = pytest.mark.unit


@pytest.fixture
def bin_(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty PATH directory first in line; tests put a fake gh or a fake package manager in it."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}/usr/bin:/bin")
    monkeypatch.delenv(github_access.OPT_OUT, raising=False)
    github_access.forget_gh_token()
    return bin_


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def fake_gh(bin_: Path, state: Path) -> None:
    """Signed in once a `state` file exists; `gh auth login` writes it (what the terminal command would do)."""
    script(
        bin_ / "gh",
        f'if [ "$1" = auth ] && [ "$2" = login ]; then echo tok > "{state}"; exit 0; fi\n'
        f'if [ -f "{state}" ]; then echo gho_fake_0123456789; exit 0; fi\necho "not logged in" >&2; exit 1\n',
    )


def test_install_command_follows_the_package_manager_found(bin_: Path) -> None:
    assert github_cli.install_command() is None  # a PATH with none
    script(bin_ / "dnf", "exit 0\n")
    assert github_cli.install_command() == ["sudo", "dnf", "install", "-y", "gh"]
    script(bin_ / "brew", "exit 0\n")
    assert github_cli.install_command() == ["brew", "install", "gh"]  # brew first when both exist


def test_sign_in_installs_when_missing_then_logs_in_through_the_terminal(bin_: Path, tmp_path: Path) -> None:
    script(bin_ / "brew", "exit 0\n")
    state = tmp_path / "signed-in"
    ran: list[list[str]] = []
    said: list[str] = []

    def terminal(argv: list[str]) -> int:
        ran.append(argv)
        if argv == ["brew", "install", "gh"]:
            fake_gh(bin_, state)  # what the install would leave on PATH
            return 0
        if argv == github_cli.LOGIN:
            state.write_text("tok")
            return 0
        return 1

    asked: list[list[str]] = []
    ok = github_cli.sign_in(terminal, said.append, confirm_install=lambda c: asked.append(c) or True)
    assert ok and asked == [["brew", "install", "gh"]]
    assert ran == [["brew", "install", "gh"], github_cli.LOGIN]
    assert github_access.gh_token() == "gho_fake_0123456789"
    assert any("Signing in with gh" in line for line in said)


def test_refusing_the_install_or_a_failed_login_says_so_and_stores_nothing(bin_: Path, tmp_path: Path) -> None:
    said: list[str] = []
    assert not github_cli.sign_in(lambda argv: 0, said.append, confirm_install=lambda c: True)
    assert "no package manager" in said[-1]
    script(bin_ / "apt-get", "exit 0\n")
    assert not github_cli.sign_in(lambda argv: 0, said.append, confirm_install=lambda c: False)
    assert "Not installed" in said[-1]
    fake_gh(bin_, tmp_path / "never")
    assert not github_cli.sign_in(lambda argv: 1, said.append, confirm_install=lambda c: True)
    assert "did not sign in" in said[-1] and github_access.gh_token() is None
