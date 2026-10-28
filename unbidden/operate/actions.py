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


def _read_record(
    integration: ApiIntegration, conn: Connection, mandate: Mandate, keys: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """The affected record, from a whole read of the integration's listing; (None, why) when it cannot be said."""
    from unbidden.forge.api_client import read_collection

    listing = next(
        (
            o
            for o in integration.operations
            if o.effect == "read" and not any(p.get("in") == "path" for p in o.parameters)
        ),
        None,
    )
    if listing is None:
        return None, "no listing operation to read the record with"
    read = read_collection(integration, conn, mandate, listing.id)
    found = [r for r in read.records if all(r.get(k) == v for k, v in keys.items())]
    if len(found) == 1:
        return found[0], read.completeness.value
    if read.completeness.value != "complete":
        return None, f"read {read.completeness.value} ({read.why}): the record may be on a page not read"
    return None, f"{len(found)} records match {keys}"


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
    from unbidden.connect.effects import approved, authorize

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
    op = integration.op(action.operation)
    effect = op.observed_effect
    if not effect:
        action.status, action.reason = ActionStatus.REFUSED, f"{op.id} has no observed effect to verify it against"
        return save(store, action)
    keys = {k: (action.body or {}).get(k) for k in effect["match"]}
    expected = (action.body or {}).get(effect["amount_from"])
    try:
        before, read_why = _read_record(integration, conn, mandate, keys)
    except (CallFailed, Unavailable) as exc:
        action.status, action.reason = ActionStatus.REFUSED, f"the record could not be read before acting: {exc}"
        return save(store, action)
    if before is None:
        action.status, action.reason = ActionStatus.REFUSED, f"the record could not be read before acting: {read_why}"
        return save(store, action)
    attempts: list[dict[str, Any]] = []
    status, data = None, None
    for attempt in (1, 2):
        try:
            status, data = call(
                integration,
                conn,
                mandate,
                op.id,
                params=action.params,
                body=action.body,
                idempotency_key=action.idempotency_key,
                approved=approved(store, conn),
            )
            attempts.append({"attempt": attempt, "status": status})
            break
        except Unavailable as exc:  # the gate refused at the moment of sending: nothing left
            action.status, action.reason, action.evidence = ActionStatus.REFUSED, str(exc), attempts
            return save(store, action)
        except CallFailed as exc:
            attempts.append({"attempt": attempt, "status": exc.status, "error": str(exc)[:200]})
            if exc.status is not None:
                action.status, action.reason, action.evidence = ActionStatus.FAILED, str(exc), attempts
                return save(store, action)
            # No answer: the write may have happened. Look before deciding anything.
            seen, why = _read_record(integration, conn, mandate, keys)
            if seen is None:
                action.status, action.evidence = ActionStatus.UNVERIFIED, attempts
                action.reason = f"no answer, and the record cannot be read ({why}): not retried, outcome unknown"
                return save(store, action)
            if _delta(before, seen, effect["field"]) == expected:
                attempts.append({"reconciled": "the effect is there: the answer was lost, nothing is sent again"})
                break
            if _delta(before, seen, effect["field"]) != 0:
                action.status, action.evidence = ActionStatus.UNVERIFIED, attempts
                action.reason = f"no answer, and {effect['field']} changed by an unexpected amount: not retried"
                return save(store, action)
            attempts.append({"reconciled": "no effect seen: retried once with the same idempotency key"})
    else:
        action.status, action.reason, action.evidence = ActionStatus.FAILED, "no answer twice", attempts
        return save(store, action)
    after, _ = _read_record(integration, conn, mandate, keys)
    action.result = {"status": status, "body": data, "attempts": attempts}
    action.evidence = [{"read": "before", "record": before}, *attempts, {"read": "after", "record": after}]
    action.verification = _verify(effect, expected, before, after)
    action.status = ActionStatus.VERIFIED if action.verification["verified"] else ActionStatus.UNVERIFIED
    action.reason = action.verification["how"]
    return save(store, action)


def _delta(before: dict[str, Any], after: dict[str, Any], field: str) -> Any:
    b, a = before.get(field), after.get(field)
    return a - b if isinstance(a, int) and isinstance(b, int) else None


def _verify(
    effect: dict[str, Any], expected: Any, before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    """The postcondition the oracle observed for this operation: on the record matched, its field changed by the
    amount written, and no other field changed. Anything else is not verified, and says what was seen."""
    if before is None or after is None:
        return {"verified": False, "how": "the affected record could not be read back"}
    changed = {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k)}
    field = effect["field"]
    grew = _delta(before, after, field)
    others = {k: v for k, v in changed.items() if k != field}
    if grew == expected and not others:
        return {"verified": True, "how": f"read back: {field} {before.get(field)} → {after.get(field)} (+{expected})"}
    return {"verified": False, "how": f"read back: expected {field} +{expected}, saw {changed or 'no change'}"}


def compensate(store: Store, mandate: Mandate, action: Action, integration: ApiIntegration, conn: Connection) -> Action:
    """Undo an executed action with its observed compensation; refused when none was observed."""
    if not action.compensation.available or not action.compensation.operation:
        action.reason = "no compensation was observed for this operation: not attempted"
        return save(store, action)
    from unbidden.connect.effects import approved, authorize

    undo = integration.op(action.compensation.operation)
    names = [p["name"] for p in undo.parameters if p.get("in") == "path"]
    created = (action.result.get("body") or {}).get(names[0]) if names else None
    effect = integration.op(action.operation).observed_effect or {}
    keys = {k: (action.body or {}).get(k) for k in effect.get("match", [])}
    ok, why = authorize(store, mandate, conn, undo.scope, f"undo {action.id}")
    if created is None or not ok:
        action.reason = f"compensation not sent: {why if not ok else 'the created record has no ' + str(names)}"
        return save(store, action)
    try:
        before, _ = _read_record(integration, conn, mandate, keys)
        status, data = call(
            integration, conn, mandate, undo.id, params={names[0]: created}, approved=approved(store, conn)
        )
        after, _ = _read_record(integration, conn, mandate, keys)
    except (CallFailed, Unavailable) as exc:
        action.reason = f"compensation failed: {exc}"
        return save(store, action)
    action.evidence = [
        *action.evidence,
        {"call": undo.id, "status": status, "response": data},
        {"read": "after undo", "record": after},
    ]
    amount = (action.body or {}).get(effect.get("amount_from", ""))
    field = effect.get("field", "")
    reverted = before is not None and after is not None and _delta(before, after, field) == -(amount or 0)
    if reverted:
        action.status, action.reason = ActionStatus.COMPENSATED, f"read back: {field} {before[field]} → {after[field]}"  # type: ignore[index]
    else:
        was, now = (before or {}).get(field), (after or {}).get(field)
        action.reason = f"{undo.id} answered {status}, but the record was not restored ({field}: {was} → {now})"
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
