"""Executing typed actions on connected resources, and checking what they did.

`run_api_action` takes a proposed `Action` through, in order: the kill switch; a repeat (the same idempotency key
already executed here: nothing is sent again, the earlier result is returned); its preconditions, each recorded with
what was observed; the connection gate (usable, a write ability the oracle observed, the grant's scope, the policy);
a read of the affected record before; the call; a read after; the verification (the record changed by what was
written); and the compensation, declared available only if the integration's oracle observed it undo this
operation. Deploy steps stay with `operate/deploy.py`; a deploy procedure found in a repository is recorded here
as a proposal only (`propose_procedure`), never executed from it.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from unbidden.connect.base import Unavailable
from unbidden.contracts.action import Action, ActionStatus, Compensation
from unbidden.contracts.common import utc_now
from unbidden.contracts.connection import Connection
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import Mandate
from unbidden.forge.api_client import ApiIntegration, CallFailed, call
from unbidden.guardian.killswitch import Cancelled, before_effect
from unbidden.store import Store

COLLECTION = "actions"


def idempotency_key(goal: str | None, connection: str, operation: str, intent: dict[str, Any], window: str) -> str:
    """The same intent, in the same window, is the same key: a repeated decision cannot act twice."""
    digest = hashlib.sha256(json.dumps([goal, connection, operation, intent, window], sort_keys=True).encode())
    return f"unbidden-{digest.hexdigest()[:24]}"


def compensation_for(integration: ApiIntegration, operation: str) -> Compensation:
    op = integration.op(operation)
    observed = (integration.quality.get("operations") or {}).get(operation) or {}
    if op.undo and observed.get("passed"):
        return Compensation(
            operation=op.undo, available=True, known_by=f"observed by the oracle: {observed.get('observed', '')}"[:300]
        )
    return Compensation()


def _record_of(data: Any, keys: dict[str, Any]) -> dict[str, Any] | None:
    from unbidden.forge.api_client import _list_items  # pyright: ignore[reportPrivateUsage]

    return next((r for r in _list_items(data) if all(r.get(k) == v for k, v in keys.items())), None)


def _read_record(
    integration: ApiIntegration, conn: Connection, mandate: Mandate, keys: dict[str, Any]
) -> dict[str, Any] | None:
    """The affected record, through the integration's listing read (all pages)."""
    listing = next(
        (
            o
            for o in integration.operations
            if o.effect == "read" and not any(p.get("in") == "path" for p in o.parameters)
        ),
        None,
    )
    if listing is None:
        return None
    page, pages = 1, 1
    while page <= min(pages, 10):
        params = {"page": page} if any(p["name"] == "page" for p in listing.parameters) else {}
        _, data = call(integration, conn, mandate, listing.id, params=params)
        found = _record_of(data, keys)
        if found is not None:
            return found
        pages = int(data.get("pages", 1)) if isinstance(data, dict) and isinstance(data.get("pages"), int) else 1
        page += 1
    return None


def save(store: Store, action: Action) -> Action:
    action.updated_at = utc_now()
    store.put(COLLECTION, action)
    store.append_event(
        Event(
            type=EventType.ACTION_EXECUTED,
            actor="operator",
            entity_id=action.id,
            correlation_id=action.goal,
            payload={
                "status": action.status.value,
                "operation": action.operation,
                "connection": action.connection,
                "reason": action.reason[:300],
            },
        )
    )
    return action


def run_api_action(
    store: Store,
    mandate: Mandate,
    action: Action,
    integration: ApiIntegration,
    conn: Connection,
    preconditions: list[tuple[str, bool, str]],
) -> Action:
    previous = next(
        (
            a
            for a in store.list(COLLECTION, Action)
            if a.idempotency_key == action.idempotency_key
            and a.status in (ActionStatus.EXECUTED, ActionStatus.VERIFIED, ActionStatus.UNVERIFIED)
        ),
        None,
    )
    if previous is not None:
        return previous  # the same intent was already acted on: not sent again
    action.preconditions = [{"what": w, "held": h, "observed": o} for w, h, o in preconditions]
    action.compensation = compensation_for(integration, action.operation)
    try:
        before_effect(store, f"{action.operation} on {conn.id}")
    except Cancelled as exc:
        action.status, action.reason = ActionStatus.REFUSED, str(exc)
        return save(store, action)
    failed = [f"{w} ({o})" for w, h, o in preconditions if not h]
    if failed:
        action.status, action.reason = ActionStatus.REFUSED, "preconditions: " + "; ".join(failed)
        return save(store, action)
    from unbidden.connect.effects import authorize

    if not conn.can("write", action.operation):
        action.status, action.reason = ActionStatus.REFUSED, f"{action.operation} was not observed to work on {conn.id}"
        return save(store, action)
    # The same authorization as every effect: grant scope, environment, revocation now, kill switch, policy with a
    # person's approval, write budget.
    ok, why = authorize(
        store, mandate, conn, integration.op(action.operation).scope, f"{action.operation} for {action.goal}"
    )
    if not ok:
        action.status, action.reason = ActionStatus.REFUSED, why
        return save(store, action)
    keys = {k: v for k, v in (action.body or {}).items() if isinstance(v, str)}
    try:
        before = _read_record(integration, conn, mandate, keys) if keys else None
        status, data = call(
            integration,
            conn,
            mandate,
            action.operation,
            params=action.params,
            body=action.body,
            idempotency_key=action.idempotency_key,
        )
        after = _read_record(integration, conn, mandate, keys) if keys else None
    except (CallFailed, Unavailable) as exc:
        action.status, action.reason = ActionStatus.FAILED, str(exc)
        return save(store, action)
    action.result = {"status": status, "body": data}
    action.evidence = [
        {"read": "before", "record": before},
        {"call": action.operation, "status": status, "response": data},
        {"read": "after", "record": after},
    ]
    action.verification = _verify(action, before, after)
    action.status = ActionStatus.VERIFIED if action.verification["verified"] else ActionStatus.UNVERIFIED
    action.reason = action.verification["how"]
    return save(store, action)


def _verify(action: Action, before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """The record read back after the write differs from before by what was written (a numeric field grown by the
    written amount); anything else is not verified, and says what was seen."""
    amounts = [v for v in (action.body or {}).values() if isinstance(v, int) and not isinstance(v, bool)]
    if before is None or after is None:
        return {"verified": False, "how": "the affected record could not be read back"}
    changed = {k: (before.get(k), after.get(k)) for k in after if before.get(k) != after.get(k)}
    grown = [k for k, (b, a) in changed.items() if isinstance(b, int) and isinstance(a, int) and a - b in amounts]
    if grown:
        return {
            "verified": True,
            "how": f"read back: {', '.join(f'{k} {changed[k][0]} → {changed[k][1]}' for k in grown)}",
        }
    return {
        "verified": False,
        "how": f"read back: no field grew by the written amount ({changed or 'nothing changed'})",
    }


def compensate(store: Store, mandate: Mandate, action: Action, integration: ApiIntegration, conn: Connection) -> Action:
    """Undo an executed action with its observed compensation; refused when none was observed."""
    if not action.compensation.available or not action.compensation.operation:
        action.reason = "no compensation was observed for this operation: not attempted"
        return save(store, action)
    undo = integration.op(action.compensation.operation)
    names = [p["name"] for p in undo.parameters if p.get("in") == "path"]
    created = (action.result.get("body") or {}).get("id")
    try:
        status, data = call(integration, conn, mandate, undo.id, params={names[0]: created})
    except (CallFailed, Unavailable) as exc:
        action.reason = f"compensation failed: {exc}"
        return save(store, action)
    action.status, action.reason = ActionStatus.COMPENSATED, f"{undo.id} answered {status}"
    action.evidence = [*action.evidence, {"call": undo.id, "status": status, "response": data}]
    return save(store, action)


_DEPLOY_HINT = re.compile(r"(docker compose[^\n`]*\bup\b[^\n`]*|kubectl apply[^\n`]*|helm (?:upgrade|install)[^\n`]*)")


def propose_procedure(store: Store, repo: Path) -> list[Action]:
    """Deploy procedures the repository describes, recorded as proposals for a person: never executed from here.
    Executing one needs a person to declare it in `mandate.operations.deploy_steps` (operate/deploy.py)."""
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.split()
    proposals = []
    for path in [p for p in tracked if p.lower().endswith((".md", "makefile", ".yml", ".yaml", ".sh"))][:50]:
        text = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{path}"], capture_output=True, text=True).stdout
        for match in _DEPLOY_HINT.finditer(text):
            command = match.group(1).strip().rstrip(";")
            action = Action(
                kind="deploy_steps",
                environment="unknown",
                operation=command,
                requires="deploy.run",
                idempotency_key=f"proposal:{path}:{command}",
                reason=f"found in {path}; a proposal only: a person declares deploy steps in the mandate",
            )
            if not any(a.idempotency_key == action.idempotency_key for a in store.list(COLLECTION, Action)):
                proposals.append(save(store, action))
    return proposals
