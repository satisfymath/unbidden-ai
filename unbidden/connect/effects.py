"""Effects on a connected service: the one authorization every mutating request passes, whoever sends it.

Three permissions stay apart:
- building an integration (`capability.build`, under `run_experiments`): reading documentation, choosing operations;
- adopting it (`capability.use`, or a person's `forge approve`): letting Unbidden read through it;
- modifying the service (`connection.write`, under `act_on_connections`): any request that changes it, including
  the oracle's own probes, which are effects too.
`authorize` is called immediately before each mutating request. It refuses, in this order: a grant that does not
allow writing that scope; a production environment; a connection revoked or gone (as recorded now, not as when the
caller looked); the kill switch; the policy (DENY, or REQUIRE_APPROVAL without a valid, unexpired approval for this
connection); the connection's daily write budget (`limits.max_writes_per_day`, 20 by default). `record_effect` keeps
each request sent as an action, so audit and budget count the oracle's probes like any other write.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from unbidden.contracts.action import Action, ActionStatus
from unbidden.contracts.common import utc_now
from unbidden.contracts.connection import Connection, ConnectionState
from unbidden.contracts.guardian import ActionRequest, ConnectionGrant, Mandate
from unbidden.guardian.approvals import find_valid, grant
from unbidden.guardian.killswitch import KillSwitch
from unbidden.guardian.policy import PolicyEngine, grant_host
from unbidden.store import Store

WRITE = "connection.write"
DEFAULT_WRITES_PER_DAY = 20
SENT = (
    ActionStatus.EXECUTED,
    ActionStatus.VERIFIED,
    ActionStatus.UNVERIFIED,
    ActionStatus.COMPENSATED,
    ActionStatus.FAILED,
)


def _grant(mandate: Mandate, conn: Connection) -> ConnectionGrant | None:
    return next((g for g in mandate.connections if g.id == conn.grant), None)


def writes_today(store: Store, conn: Connection) -> int:
    today = f"{utc_now():%Y-%m-%d}"
    return sum(
        1
        for a in store.list("actions", Action)
        if a.connection == conn.id and a.status in SENT and f"{a.created_at:%Y-%m-%d}" == today
    )


def authorize(store: Store, mandate: Mandate, conn: Connection, scope: str, purpose: str) -> tuple[bool, str]:
    """Whether one more mutating request may be sent to this connection now, and if not, exactly why."""
    from unbidden.connect.registry import get

    granted = _grant(mandate, conn)
    if granted is None:
        return False, f"{conn.id} is not granted by the mandate"
    if f"write:{scope}" not in granted.permissions and "write" not in granted.permissions:
        return False, f"the grant {granted.id} allows {granted.permissions}, not write:{scope}"
    if granted.environment == "production":
        return False, f"{granted.id} is production: Unbidden does not change it"
    current = get(store, conn.id)
    if current is not None and current.state in (ConnectionState.REVOKED, ConnectionState.GONE):
        return False, f"{conn.id} is {current.state.value}"
    switch = KillSwitch.of(store)
    if switch is not None and switch.engaged:
        return False, "the kill switch is engaged"
    approved = find_valid(store, WRITE, conn.id) is not None
    verdict = PolicyEngine(mandate).evaluate(
        ActionRequest(capability=WRITE, purpose=purpose, destinations=[grant_host(granted.location)]), approved=approved
    )
    if not verdict.allowed:
        if verdict.decision.value == "require_approval":
            return False, (
                f"changing {conn.id} needs a person's approval: `unbidden approve-writes {granted.id}` (time-limited)"
            )
        return False, "; ".join(verdict.reasons)
    limit = int(granted.limits.get("max_writes_per_day", DEFAULT_WRITES_PER_DAY))
    used = writes_today(store, conn)
    if used >= limit:
        return False, f"{conn.id}: {used} writes today, its limit is {limit}"
    return True, "approved by a person" if approved else verdict.rule


def approve_writes(store: Store, mandate: Mandate, grant_id: str, by: str, hours: float) -> Any:
    """A person's time-limited approval to change one connection (the policy's REQUIRE_APPROVAL)."""
    from unbidden.connect.registry import by_grant

    conn = by_grant(store, grant_id)
    if conn is None:
        raise ValueError(f"no connection granted as {grant_id}")
    return grant(store, WRITE, conn.id, by, ttl=timedelta(hours=hours))


def record_effect(
    store: Store,
    conn: Connection,
    operation: str,
    body: dict[str, Any] | None,
    *,
    kind: str,
    status: ActionStatus,
    result: dict[str, Any],
    reason: str,
    key: str,
    goal: str | None = None,
) -> Action:
    """A mutating request that was sent (or attempted), kept for audit and counted in the write budget."""
    from unbidden.operate.actions import save

    action = Action(
        kind=kind,
        goal=goal,
        connection=conn.id,
        environment=conn.environment.value,
        operation=operation,
        body=body,
        idempotency_key=key,
        requires=WRITE,
        status=status,
        reason=reason,
        result=result,
    )
    return save(store, action)
