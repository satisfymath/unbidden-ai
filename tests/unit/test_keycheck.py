"""A key is proven, not assumed: the shape of a pasted value, the verdict of one short call, and the memory that
keeps `start` and `doctor` from paying twice for the same key."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from unbidden.guardian.credentials import reset
from unbidden.setup import keycheck, machine

pytestmark = pytest.mark.unit

KEY = "LLM|1234567890|abcdefghijklmnopqrstuvwxyz"


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    reset()
    return tmp_path


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("cd ~/ihatemoney-demo", "command"),
        ("export MODEL_API_KEY=abc", "command"),
        ("unbidden start", "command"),
        ("LLM|123 456|abcdefghijklmnop", "spaces"),
        ("abc123", "short"),
        (KEY, None),
        ("sk-ant-0123456789abcdef", None),
    ],
)
def test_what_cannot_be_a_key_is_named(value: str, why: str | None) -> None:
    assert keycheck.looks_like_key(value) == why


def test_the_verdict_of_a_probe_tells_a_refused_key_from_an_unreachable_api() -> None:
    ok = keycheck.verdict_of({"ok": True, "model": "muse-spark-1.3", "usd": 0.0002})
    assert ok.ok and not ok.rejected and ok.model == "muse-spark-1.3" and ok.usd == 0.0002
    refused = keycheck.verdict_of({"ok": False, "why": "ProviderUnauthorized: meta 401: the key was refused"})
    assert not refused.ok and refused.rejected
    down = keycheck.verdict_of({"ok": False, "why": "ProviderError: meta unreachable: connect"})
    assert not down.ok and not down.rejected and down.why is not None and "unreachable" in down.why


def test_verify_key_calls_once_per_key_and_remembers_the_fingerprint_never_the_key(home: Path) -> None:
    machine.write_env(machine.machine_env(), {"MODEL_API_KEY": KEY})
    calls: list[int] = []

    def probe(ws: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(int(kwargs["max_tokens"]))
        return {"ok": True, "model": "muse-spark-1.3", "usd": 0.0001}

    first = keycheck.verify_key(object(), probe=probe)
    assert first.ok and calls == [keycheck.PROBE_TOKENS]
    again = keycheck.verify_key(object(), probe=probe)
    assert again == first and calls == [keycheck.PROBE_TOKENS], "the same key is never paid for twice"
    saved = json.loads((home / ".unbidden" / "keys.json").read_text())
    assert saved["MODEL_API_KEY"]["fingerprint"] == keycheck.fingerprint(KEY) and KEY not in json.dumps(saved)
    assert oct((home / ".unbidden" / "keys.json").stat().st_mode & 0o777) == "0o600"

    machine.write_env(machine.machine_env(), {"MODEL_API_KEY": KEY + "-replaced"})
    reset()
    keycheck.verify_key(object(), probe=probe)
    assert calls == [keycheck.PROBE_TOKENS] * 2, "a replaced key starts unknown"
    assert keycheck.verify_key(object(), probe=probe, force=True).ok and len(calls) == 3


def test_a_refused_key_stays_refused_without_another_call_and_forget_clears_it() -> None:
    machine.write_env(machine.machine_env(), {"MODEL_API_KEY": KEY})
    calls = 0

    def refused(ws: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": False, "why": "ProviderUnauthorized: meta 401: the key was refused"}

    assert keycheck.verify_key(object(), probe=refused).rejected and calls == 1
    assert keycheck.verify_key(object(), probe=refused).rejected and calls == 1
    keycheck.forget("MODEL_API_KEY")
    assert keycheck.recall("MODEL_API_KEY", KEY) is None
    assert keycheck.verify_key(object(), probe=refused).rejected and calls == 2


def test_an_unprovable_key_is_asked_again_next_time() -> None:
    machine.write_env(machine.machine_env(), {"MODEL_API_KEY": KEY})
    answers = iter([{"ok": False, "why": "ProviderError: meta unreachable"}, {"ok": True, "model": "m", "usd": 0.0}])
    assert not keycheck.verify_key(object(), probe=lambda ws, **kw: next(answers)).ok
    assert keycheck.verify_key(object(), probe=lambda ws, **kw: next(answers)).ok


def test_no_key_is_a_verdict_not_a_call() -> None:
    verdict = keycheck.verify_key(object(), probe=lambda ws, **kw: pytest.fail("no key, no call"))
    assert not verdict.ok and not verdict.rejected and verdict.why == "no MODEL_API_KEY"
