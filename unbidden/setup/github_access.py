"""Where the GitHub token comes from, found rather than asked: a token already saved for Unbidden, one in the
environment, or the `gh` CLI's sign-in. A `gh` token is held in memory for this process and never copied to a
file, so signing out of `gh` signs Unbidden out too."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

import httpx

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


@dataclass(frozen=True)
class Verified:
    """What GitHub says about the token held: who it is, and whether that account can push to the repository."""

    login: str | None
    can_push: bool | None  # None: the repository could not be read (not found for this account, or offline)
    detail: str


API = "https://api.github.com"


def verify(
    slug: str | None,
    *,
    token_env: str = TOKEN_ENV,
    timeout_s: float = 8.0,
    transport: httpx.BaseTransport | None = None,
) -> Verified | None:
    """Ask GitHub, with the token held, who it is and whether it may push to `slug`. None when no token is held;
    a Verified with `can_push=None` when GitHub could not be asked (offline) or does not show the repository to
    this account. Two small reads, never a write."""
    held = broker()
    if not held.has(token_env):
        return None
    token = held.get(token_env, "github")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        with httpx.Client(base_url=os.environ.get("UNBIDDEN_GITHUB_API", API), timeout=timeout_s,
                          headers=headers, transport=transport) as client:  # fmt: skip
            me = client.get("/user")
            login = str(me.json().get("login")) if me.status_code == 200 else None
            if login is None:
                return Verified(None, None, f"the token was refused ({me.status_code})")
            if not slug:
                return Verified(login, None, "no GitHub remote to check")
            repo = client.get(f"/repos/{slug}")
            if repo.status_code == 404:
                return Verified(login, False, f"{slug} is not visible to {login}")
            if repo.status_code != 200:
                return Verified(login, None, f"{slug} could not be read ({repo.status_code})")
            push = bool((repo.json().get("permissions") or {}).get("push"))
            return Verified(login, push, f"can push to {slug}" if push else f"{login} cannot write to {slug}")
    except httpx.HTTPError as exc:
        return Verified(None, None, f"GitHub could not be reached ({type(exc).__name__})")
