"""A fake secret is planted in every place a value can enter; it must never be found in stored state.

This grows with the product: each new path that writes or sends data adds itself here.
"""

from __future__ import annotations

import pytest

from unbidden.contracts.events import AuditEntry, Event, EventType
from unbidden.contracts.jobs import Job
from unbidden.store import Store

pytestmark = pytest.mark.e2e

PLANTED = "PAYMENT_API_KEY=pk_live_9f8e7d6c5b4a3210"
SECRET_VALUE = "pk_live_9f8e7d6c5b4a3210"


def test_planted_secret_never_reaches_stored_state(store: Store) -> None:
    store.append_event(Event(type=EventType.ANALYZER_RAN, actor="observer", payload={"stderr": PLANTED}))
    store.append_audit(AuditEntry(actor="lab", kind="sandbox", summary=f"ran with {PLANTED}", data={"env": PLANTED}))
    store.enqueue(Job(type="lab.experiment", idempotency_key="k", payload={"note": PLANTED}))
    store.set_value("last_error", PLANTED)

    dumped = "\n".join(store.dump_all_text())
    assert dumped, "the store should hold something"
    assert SECRET_VALUE not in dumped
