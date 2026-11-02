"""Sign in to GitHub through the browser: the device flow against a fake GitHub (no network), with the person
authorizing, refusing, letting the code expire, being told to slow down, or interrupting."""

from __future__ import annotations

import threading
from urllib.parse import parse_qs

import httpx
import pytest

from unbidden.setup import github_device

pytestmark = pytest.mark.unit


class FakeGitHub:
    def __init__(self, answers: list[dict[str, object]]) -> None:
        self.answers = answers  # what /login/oauth/access_token says, in order
        self.polls = 0
        self.requests: list[dict[str, list[str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode())
        self.requests.append(body)
        assert request.headers["accept"] == "application/json"
        assert body["client_id"] == ["test-client"]
        if request.url.path == "/login/device/code":
            assert body["scope"] == ["repo"]
            return httpx.Response(200, json={
                "device_code": "dev-1", "user_code": "ABCD-EFGH", "verification_uri": "https://github.com/login/device",
                "expires_in": 900, "interval": 1,
            })  # fmt: skip
        assert request.url.path == "/login/oauth/access_token"
        assert body["device_code"] == ["dev-1"] and body["grant_type"] == [github_device.GRANT]
        assert "client_secret" not in body
        self.polls += 1
        return httpx.Response(200, json=self.answers[min(self.polls, len(self.answers)) - 1])


@pytest.fixture(autouse=True)
def oauth_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNBIDDEN_GITHUB_CLIENT_ID", "test-client")
    monkeypatch.setenv("UNBIDDEN_GITHUB_URL", "https://github.test")


def run(fake: FakeGitHub, cancel: threading.Event | None = None) -> tuple[str | None, list[str]]:
    said: list[str] = []
    clock = {"now": 0.0}

    def sleep(s: float) -> None:
        clock["now"] += s

    token = github_device.sign_in(
        say=said.append, cancel=cancel, transport=httpx.MockTransport(fake), sleep=sleep, clock=lambda: clock["now"]
    )
    return token, said


def test_hidden_until_the_oauth_app_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNBIDDEN_GITHUB_CLIENT_ID")
    assert github_device.GITHUB_CLIENT_ID == "" and not github_device.available()


def test_the_person_authorizes_after_two_polls() -> None:
    fake = FakeGitHub([{"error": "authorization_pending"}, {"error": "authorization_pending"},
                       {"access_token": "gho_granted_0123456789", "token_type": "bearer"}])  # fmt: skip
    token, said = run(fake)
    assert token == "gho_granted_0123456789" and fake.polls == 3
    assert said[0] == "Open https://github.com/login/device and enter the code ABCD-EFGH"


def test_slow_down_widens_the_interval_and_denied_or_expired_say_why() -> None:
    fake = FakeGitHub([{"error": "slow_down", "interval": 6}, {"error": "access_denied"}])
    token, said = run(fake)
    assert token is None and "you refused the sign-in" in said[-1]
    fake = FakeGitHub([{"error": "expired_token"}])
    token, said = run(fake)
    assert token is None and "expired" in said[-1]


def test_ctrl_c_cancels_within_a_second() -> None:
    fake = FakeGitHub([{"error": "authorization_pending"}])
    cancel = threading.Event()
    cancel.set()
    token, said = run(fake, cancel)
    assert token is None and said[-1] == "cancelled" and fake.polls == 0


def test_the_deadline_ends_the_wait() -> None:
    fake = FakeGitHub([{"error": "authorization_pending"}] * 2000)
    token, said = run(fake)
    assert token is None and "expired" in said[-1] and fake.polls < 1000
