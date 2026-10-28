"""Capability needs, from noticed to in use, without a person typing a command.

The cycle records a need where it notices one (a metrics endpoint in a format nothing reads, a service whose access
log nothing parses), queues `forge.build`, and this module builds it: Forge, then its oracle, then the one use gate
(`forge.logs.permitted`). In use, whatever waited for it is queued again; awaiting approval, a person's
`unbidden forge approve` finishes the job. Building runs the local model (`capability.build`, under
`run_experiments`); anything remote goes through the Brain's own gates and spend ledger, as every call does.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from unbidden.contracts.capability import CapabilityNeed, NeedStatus
from unbidden.contracts.common import EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.forge.logs import permitted
from unbidden.guardian.policy import PolicyEngine
from unbidden.store import Store

COLLECTION = "needs"
MAX_ATTEMPTS = 2
# What a build needs from outside, injected so the cycle and tests give it lines and a Forge their own way:
# (kind, source) -> lines read from the source now.
Reader = Callable[[str, str], list[str]]
# (need, lines) -> (capability id or None, decision, notes)
Builder = Callable[[CapabilityNeed, list[str]], Awaitable[tuple[str | None, str, list[str]]]]


def record(
    store: Store,
    kind: str,
    source: str,
    why: str,
    *,
    evidence: list[EvidenceRef] | None = None,
    resume: list[dict[str, Any]] | None = None,
    condition: str | None = None,
) -> tuple[CapabilityNeed, bool]:
    """Record a need once per (kind, source); later sightings add what waits for it. Returns it, and whether it is
    one the cycle should build now (new, failed with attempts left, or blocked on a condition that has changed).
    `condition` is what a person controls that the build depends on, as the caller sees it now."""
    key = CapabilityNeed.key(kind, source)
    need = store.get(COLLECTION, key, CapabilityNeed)
    if need is None:
        need = CapabilityNeed(id=key, kind=kind, source=source, why=why, evidence=evidence or [])  # type: ignore[arg-type]
        payload = {"kind": kind, "source": source, "why": why}
        store.append_event(Event(type=EventType.CAPABILITY_NEEDED, actor="observer", entity_id=key, payload=payload))
    for job in resume or []:
        if job not in need.resume:
            need.resume = [*need.resume, job]
    if condition is not None:
        need.condition = condition
    need.updated_at = utc_now()
    store.put(COLLECTION, need)
    if need.status is NeedStatus.BLOCKED and need.condition != need.blocked_on:
        need.unblocked += 1
        _set(store, need, NeedStatus.OPEN, "what blocked it changed; built again")
    return need, buildable(need)


def buildable(need: CapabilityNeed) -> bool:
    return need.status is NeedStatus.OPEN or (need.status is NeedStatus.FAILED and need.attempts < MAX_ATTEMPTS)


async def build(store: Store, mandate: Mandate, need: CapabilityNeed, read: Reader, forge: Builder) -> CapabilityNeed:
    """One attempt at filling a need. Never raises for a failed build: the need records why."""
    verdict = PolicyEngine(mandate).evaluate(
        ActionRequest(capability="capability.build", purpose=f"build a {need.kind} for {need.source}")
    )
    if not verdict.allowed:
        return _set(store, need, need.status, f"not built: {'; '.join(verdict.reasons)}")
    need.attempts += 1
    _set(store, need, NeedStatus.BUILDING, f"attempt {need.attempts}")
    lines = read(need.kind, need.source)
    if not lines:
        return _failed(store, need, "the source returned no lines to build from")
    capability_id, decision, notes = await forge(need, lines)
    need.notes = [*need.notes, *notes[-5:]]
    if capability_id is None and decision == "blocked":
        # Waiting for a person is not a failed attempt: it is built again when what blocked it changes.
        need.attempts -= 1
        need.blocked_on = need.condition
        return _set(store, need, NeedStatus.BLOCKED, "blocked until a person changes what it depends on")
    if capability_id is None:
        return _failed(store, need, f"no capability built ({decision})")
    need.capability_id = capability_id
    return admit(store, mandate, need)


def admit(store: Store, mandate: Mandate | None, need: CapabilityNeed) -> CapabilityNeed:
    """The use gate, then what waited for the need. Called after a build and after a person's approval."""
    status = _capability_status(store, need)
    if status is None:
        return _failed(store, need, "the capability it was filled with is gone or disabled")
    if not permitted(status, mandate, need.source):
        return _set(store, need, NeedStatus.AWAITING_APPROVAL, f"built {need.capability_id}; awaiting approval")
    _set(store, need, NeedStatus.IN_USE, f"in use: {need.capability_id}")
    if need.kind in ("api_client", "api_extension") and need.capability_id:
        _attach(store, need.source.split("#", 1)[0], need.capability_id)
    from unbidden.daemon.cycle import job

    for spec in need.resume:
        store.enqueue(job(spec["type"], f"{spec.get('key', need.id)}:{need.capability_id}", spec.get("payload")))
    return need


def _attach(store: Store, connection: str, capability_id: str) -> None:
    """An integration in use is the way its connection is used: recorded on it, whoever admitted it (the mandate in
    the cycle, or a person's approval). The connection's next check goes through the integration."""
    from unbidden.connect.registry import get, record

    conn = get(store, connection)
    if conn is not None and conn.capability_id != capability_id:
        conn.capability_id = capability_id
        record(store, conn, reason=f"integration {capability_id} in use")


def approved(store: Store, capability_id: str) -> list[CapabilityNeed]:
    """A person approved a capability: the needs it fills are in use, and what waited for them runs."""
    filled = [n for n in store.list(COLLECTION, CapabilityNeed) if n.capability_id == capability_id]
    return [admit(store, None, n) for n in filled]


def _capability_status(store: Store, need: CapabilityNeed) -> str | None:
    from unbidden.forge.adapter import LogAdapter
    from unbidden.forge.stats import StatsAdapter
    from unbidden.forge.stats_build import COLLECTION as STATS

    if need.capability_id is None:
        return None
    if need.kind in ("api_client", "api_extension"):
        from unbidden.forge.api_client import COLLECTION as INTEGRATIONS
        from unbidden.forge.api_client import ApiIntegration

        integration = store.get(INTEGRATIONS, need.capability_id, ApiIntegration)
        return (
            integration.status if integration is not None and integration.status in ("validated", "approved") else None
        )
    found: LogAdapter | StatsAdapter | None = (
        store.get("capabilities", need.capability_id, LogAdapter)
        if need.kind == "log_adapter"
        else store.get(STATS, need.capability_id, StatsAdapter)
    )
    return found.status if found is not None and found.status in ("validated", "approved") else None


def _failed(store: Store, need: CapabilityNeed, why: str) -> CapabilityNeed:
    status = NeedStatus.ABANDONED if need.attempts >= MAX_ATTEMPTS else NeedStatus.FAILED
    _set(store, need, status, why)
    if status is NeedStatus.ABANDONED:
        # What waited is told, once: it reports the specific block instead of waiting for a capability forever.
        from unbidden.daemon.cycle import job

        for spec in need.resume:
            store.enqueue(job(spec["type"], f"{spec.get('key', need.id)}:abandoned:{need.id}", spec.get("payload")))
    return need


def _set(store: Store, need: CapabilityNeed, status: NeedStatus, note: str) -> CapabilityNeed:
    changed = need.status is not status
    need.status, need.updated_at = status, utc_now()
    need.notes = [*need.notes, note][-20:]
    store.put(COLLECTION, need)
    if changed:
        store.append_event(
            Event(type=EventType.CAPABILITY_NEED_CHANGED, actor="forge", entity_id=need.id,
                  payload={"status": status.value, "source": need.source, "note": note})
        )  # fmt: skip
    return need
