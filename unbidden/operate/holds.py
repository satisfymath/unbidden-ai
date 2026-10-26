"""Holds stop autonomous merges and deploys. Unbidden may set one; only a person may release it."""

from __future__ import annotations

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import Hold
from unbidden.store import Store

COLLECTION = "holds"


def active(store: Store) -> list[Hold]:
    return [h for h in store.list(COLLECTION, Hold) if h.released_at is None]


def place(store: Store, reason: str) -> Hold:
    hold = Hold(reason=reason)
    store.put(COLLECTION, hold)
    store.append_event(
        Event(
            type=EventType.POLICY_DENIED,
            actor="guardian",
            entity_id=hold.id,
            payload={"rule": "hold", "reason": reason},
        )
    )
    return hold


def release(store: Store, hold_id: str, person: str, reason: str) -> Hold:
    if not person.startswith("person:"):
        raise PermissionError("only a person releases a hold")
    hold = store.get(COLLECTION, hold_id, Hold)
    if hold is None or hold.released_at is not None:
        raise LookupError(f"no active hold {hold_id}")
    hold.released_by, hold.released_at = f"{person} ({reason})", utc_now()
    store.put(COLLECTION, hold)
    return hold
