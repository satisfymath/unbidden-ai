"""Sign in to GitHub from the terminal: the OAuth device flow. Unbidden shows a short code and a URL, the person
enters the code in the browser, and GitHub hands a token to this machine; no client secret is involved. The token
lands in ~/.unbidden/.env as GITHUB_TOKEN, referenced by name like every credential.

Needs an OAuth App with "Device Flow" enabled; its Client ID is `GITHUB_CLIENT_ID` below (empty until registered:
the option stays hidden). Limits: the code lives 15 minutes; organizations with OAuth-app restrictions refuse such
tokens at publish time (a fine-grained token pasted by hand still works there)."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_CLIENT_ID = ""  # the OAuth App under the project's GitHub account, once registered
SCOPE = "repo"  # private repositories need it; proposals are branches and pull requests on the project's repo
GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def client_id() -> str:
    return os.environ.get("UNBIDDEN_GITHUB_CLIENT_ID") or GITHUB_CLIENT_ID


def github_url() -> str:
    return os.environ.get("UNBIDDEN_GITHUB_URL", "https://github.com").rstrip("/")


def available() -> bool:
    return bool(client_id())


@dataclass(frozen=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class DeviceFlowError(RuntimeError):
    pass


def request_code(client: httpx.Client) -> DeviceCode:
    response = client.post(
        f"{github_url()}/login/device/code",
        data={"client_id": client_id(), "scope": SCOPE},
        headers={"Accept": "application/json"},
    )
    if response.status_code != 200:
        raise DeviceFlowError(f"GitHub refused the device code request: {response.status_code}")
    data = response.json()
    if "device_code" not in data:
        raise DeviceFlowError(f"GitHub answered without a device code: {data.get('error', 'unknown')}")
    return DeviceCode(
        device_code=str(data["device_code"]),
        user_code=str(data["user_code"]),
        verification_uri=str(data["verification_uri"]),
        expires_in=int(data.get("expires_in", 900)),
        interval=int(data.get("interval", 5)),
    )


def poll(
    client: httpx.Client,
    code: DeviceCode,
    *,
    cancel: threading.Event,
    say: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """Ask GitHub every `interval` seconds until the person authorized, refused, the code expired or `cancel` was
    set. Returns the token, or None after saying why."""
    interval = float(code.interval)
    deadline = clock() + code.expires_in
    while True:
        waited = 0.0
        while waited < interval:  # sleep in short steps so Ctrl+C lands within a second
            if cancel.is_set():
                say("cancelled")
                return None
            step = min(1.0, interval - waited)
            sleep(step)
            waited += step
        if clock() > deadline:
            say("the code expired; run /setup credentials to try again")
            return None
        response = client.post(
            f"{github_url()}/login/oauth/access_token",
            data={"client_id": client_id(), "device_code": code.device_code, "grant_type": GRANT},
            headers={"Accept": "application/json"},
        )
        data: dict[str, Any] = response.json() if response.status_code == 200 else {}
        token = data.get("access_token")
        if token:
            return str(token)
        error = str(data.get("error") or f"http {response.status_code}")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = float(data.get("interval", interval + 5))
            continue
        if error == "expired_token":
            say("the code expired; run /setup credentials to try again")
            return None
        if error == "access_denied":
            say("you refused the sign-in; proposals stay local branches")
            return None
        say(f"GitHub answered {error}; proposals stay local branches")
        return None


def sign_in(
    *,
    say: Callable[[str], None],
    cancel: threading.Event | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str | None:
    """The whole flow: show the code and the URL, wait, return the token or None."""
    with httpx.Client(timeout=20, transport=transport) as client:
        code = request_code(client)
        say(f"Open {code.verification_uri} and enter the code {code.user_code}")
        say("Waiting for GitHub (Ctrl+C stops; nothing is saved until GitHub answers).")
        return poll(client, code, cancel=cancel or threading.Event(), say=say, sleep=sleep, clock=clock)
