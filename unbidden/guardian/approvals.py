"""Approvals a person grants from the CLI: scoped to one capability and one subject, expiring, counted."""

from __future__ import annotations

from datetime import datetime, timedelta

from unbidden.contracts.common import utc_now
from unbidden.contracts.guardian import Approval
from unbidden.store import Store

COLLECTION = "approvals"


def grant(store: Store, capability: str, subject_id: str, granted_by: str, *, ttl: timedelta) -> Approval:
    approval = Approval(capability=capability, subject_id=subject_id, granted_by=granted_by, expires_at=utc_now() + ttl)
    store.put(COLLECTION, approval)
    return approval


def find_valid(store: Store, capability: str, subject_id: str, *, now: datetime | None = None) -> Approval | None:
    moment = now or utc_now()
    for approval in store.list(COLLECTION, Approval):
        if (
            approval.capability == capability
            and approval.subject_id == subject_id
            and approval.expires_at > moment
            and approval.uses < approval.max_uses
        ):
            return approval
    return None


def consume(store: Store, approval: Approval) -> None:
    approval.uses += 1
    store.put(COLLECTION, approval)
