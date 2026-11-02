"""Where the GitHub token comes from, found rather than asked: a token already saved for Unbidden, one in the
environment, or the `gh` CLI's sign-in. A `gh` token is held in memory for this process and never copied to a
file, so signing out of `gh` signs Unbidden out too."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

from unbidden.guardian.credentials import broker
from unbidden.setup import machine

Source = Literal["file", "env", "gh"]
TOKEN_ENV = "GITHUB_TOKEN"
OPT_OUT = "UNBIDDEN_GH_TOKEN"  # "off": never ask the gh CLI (the test suite sets it)

_gh_cache: dict[str, str | None] = {}


@dataclass(frozen=True)
class Access:
    source: Source | None

    @property
    def found(self) -> bool:
        return self.source is not None


def gh_token(*, timeout_s: float = 5.0) -> str | None:
    """The token `gh auth token` prints when the CLI is signed in; None when gh is absent, signed out, opted out
    or slow. One subprocess per process: the answer is cached."""
    if os.environ.get(OPT_OUT, "").lower() == "off":
        return None
    if "token" in _gh_cache:
        return _gh_cache["token"]
    token: str | None = None
    gh = shutil.which("gh")
    if gh:
        try:
            out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=timeout_s, check=False)
            if out.returncode == 0 and out.stdout.strip():
                token = out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            token = None
    _gh_cache["token"] = token
    return token


def forget_gh_token() -> None:
    _gh_cache.clear()


def github_access(ws: Any, *, token_env: str = TOKEN_ENV) -> Access:
    """Find a token, first wins: Unbidden's own env files, the process environment, the gh CLI. Loads the
    workspace's env (the broker absorbs an environment value on grant, and `load_env` itself falls back to gh)."""
    in_files = any(
        token_env in machine.read_env(path) for path in (ws.dir / ".env", machine.machine_env()) if path.exists()
    )
    in_env = token_env in os.environ or "GH_TOKEN" in os.environ
    held = broker()
    if "GH_TOKEN" in os.environ and token_env not in os.environ and not held.has(token_env):
        held.hold(token_env, os.environ["GH_TOKEN"])
    ws.load_env()
    if in_files and held.has(token_env):
        return Access("file")
    if in_env and held.has(token_env):
        return Access("env")
    if held.has(token_env):
        return Access("gh" if gh_token() else "env")
    return Access(None)
