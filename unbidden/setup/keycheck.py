"""Whether the model configured here answers: the shape of a pasted key, one short inference call that proves the
remote key (less than a cent, recorded in the ledger like any call), the same against the local model, and a memory
of which key was proven so `start` and `doctor` never pay twice for the same one.

A pasted key is never written to a log, an event or the terminal: only its fingerprint (16 hex chars of its sha256)
is kept, in `~/.unbidden/keys.json`, next to when and by which model it was proven."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from unbidden.setup import machine

MIN_LENGTH = 16
_SHELL_PREFIX = re.compile(r"^(cd|ls|export|echo|unbidden|curl|sh|bash|sudo|git|python3?|pip|uv)\b")
PROBE_TOKENS = 8


@dataclass(frozen=True)
class KeyVerdict:
    ok: bool
    rejected: bool  # the service refused the key itself (401/403); False when unreachable or another failure
    model: str | None
    usd: float
    why: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def looks_like_key(value: str) -> str | None:
    """Why `value` cannot be an API key, or None when it may be one. A key has no whitespace and is not short; a
    line that starts like a shell command is what a person pastes by mistake (seen 2026-11-02: `cd ~/repo`)."""
    stripped = value.strip()
    if not stripped:
        return "empty"
    if _SHELL_PREFIX.match(stripped):
        return "command"
    if any(ch.isspace() for ch in stripped):
        return "spaces"
    if len(stripped) < MIN_LENGTH:
        return "short"
    return None


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _path() -> Path:
    return machine.machine_dir() / "keys.json"


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def remember(name: str, value: str, verdict: KeyVerdict) -> None:
    """What was learned about the key currently saved under `name`: its fingerprint and the verdict, never itself."""
    data = _load()
    data[name] = {
        "fingerprint": fingerprint(value),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        **verdict.as_dict(),
    }
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def recall(name: str, value: str) -> KeyVerdict | None:
    """The verdict remembered for this very key (same fingerprint), else None: a replaced key starts unknown."""
    entry = _load().get(name)
    if not isinstance(entry, dict) or entry.get("fingerprint") != fingerprint(value):
        return None
    return KeyVerdict(
        ok=bool(entry.get("ok")),
        rejected=bool(entry.get("rejected")),
        model=entry.get("model"),
        usd=float(entry.get("usd") or 0.0),
        why=entry.get("why"),
    )


def forget(name: str) -> None:
    data = _load()
    if name in data:
        del data[name]
        _path().write_text(json.dumps(data, indent=2))


def current_key(name: str = "MODEL_API_KEY") -> str | None:
    """The key saved on this machine for `name`, read for fingerprinting only (never shown, never logged)."""
    from unbidden.guardian.credentials import broker

    held = broker()
    if held.has(name):
        value = held.get(name, "model.remote")
        if value:
            return value
    return machine.read_env(machine.machine_env()).get(name) or None


def verdict_of(probe: dict[str, Any]) -> KeyVerdict:
    """A probe's answer (`probe_remote`) as a verdict: a ProviderUnauthorized is the key refused; anything else that
    failed is not the key's fault yet (network, a cap, a policy)."""
    if probe.get("ok"):
        return KeyVerdict(True, False, probe.get("model"), float(probe.get("usd") or 0.0), None)
    why = str(probe.get("why") or "no answer")
    return KeyVerdict(False, why.startswith("ProviderUnauthorized"), None, 0.0, why)


def verify_key(ws: Any, *, name: str = "MODEL_API_KEY", probe: Any = None, force: bool = False) -> KeyVerdict:
    """Prove the saved key with one short inference call, unless this very key was proven before (`force` asks
    again). The call goes through the Brain like every other: policy, egress gate, ledger."""
    from unbidden.setup.wizard import probe_remote

    value = current_key(name)
    if not value:
        return KeyVerdict(False, False, None, 0.0, f"no {name}")
    if not force:
        known = recall(name, value)
        if known is not None and (known.ok or known.rejected):
            return known
    verdict = verdict_of((probe or probe_remote)(ws, max_tokens=PROBE_TOKENS))
    remember(name, value, verdict)
    return verdict


def verify_local(url: str, tag: str) -> KeyVerdict:
    """One short generation against the local model: proves Ollama serves it. Costs nothing; nothing leaves."""
    from unbidden.brain.providers import ProviderError
    from unbidden.brain.providers.ollama import OllamaProvider
    from unbidden.contracts.llm import LLMRequest, Message, Tier

    provider = OllamaProvider(url, timeout_s=120)
    request = LLMRequest(
        purpose="setup.probe_local",
        tier=Tier.LOCAL,
        messages=[Message(role="user", content="Reply with the single word OK.", source="prompt")],
        max_tokens=PROBE_TOKENS,
    )

    async def once() -> Any:
        try:
            return await provider.chat(request, model=tag, think=None)
        finally:
            await provider.aclose()

    try:
        response = asyncio.run(once())
    except ProviderError as exc:
        return KeyVerdict(False, False, tag, 0.0, f"{type(exc).__name__}: {str(exc)[:200]}")
    except Exception as exc:  # a connection refused, a missing model: said, never raised at the person
        return KeyVerdict(False, False, tag, 0.0, f"{type(exc).__name__}: {str(exc)[:200]}")
    return KeyVerdict(bool(response.content or response.done_reason), False, tag, 0.0, None)
