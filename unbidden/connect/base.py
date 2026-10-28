"""What every connector does alike, and the one place where connections are allowed to be used.

Common to all: a configuration is validated before anything is tried; a check reaches the resource with its own
credential and reports the state, what the credential could actually do (`effective`), and checked abilities;
failures are classified the same way (`Failure`); every read and write goes through `require`, which refuses a
connection that is not usable, an ability that was not checked, and a destination outside the grant.
Specific to each provider, and kept there: what identity and permission mean (a database role's grants, a token's
repository permissions, an API key's scope), how they are observed, and every operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from unbidden.contracts.connection import Ability, Connection, ConnectionState
from unbidden.contracts.guardian import ActionRequest, ConnectionGrant, Mandate
from unbidden.guardian.policy import PolicyEngine, grant_host


class Failure(StrEnum):
    AUTH = "auth"  # the credential was refused (missing, wrong, expired, revoked)
    PERMISSION = "permission"  # accepted, but not allowed to do this
    UNREACHABLE = "unreachable"
    RATE_LIMITED = "rate_limited"
    INVALID = "invalid"  # the configuration or the request is wrong
    NOT_FOUND = "not_found"


@dataclass
class CheckResult:
    state: ConnectionState
    detail: str
    effective: list[str] = field(default_factory=list[str])
    abilities: list[Ability] = field(default_factory=list[Ability])
    failure: Failure | None = None
    next_step: str | None = None
    facts: dict[str, Any] = field(default_factory=dict[str, Any])  # what the check learned (identity, version)


class Connector(Protocol):
    kind: str

    def validate(self, grant: ConnectionGrant) -> list[str]:
        """Problems with the configuration, before anything is reached. Empty when it can be tried."""
        ...

    def check(self, grant: ConnectionGrant) -> CheckResult:
        """Reach the resource with its credential; observe identity and what the credential can do."""
        ...


class Unavailable(RuntimeError):
    """A connection that may not be used for this, now: the reason says what would change that."""


def purpose(grant_id: str) -> str:
    """The broker purpose under which a connection's credential is handed out: to that connection only."""
    return f"connection:{grant_id}"


def require(
    conn: Connection | None, mandate: Mandate, kind: str, operation: str | None, why: str, *, scope: str | None = None
) -> Connection:
    """The gate every connection read or write passes, at the moment it runs. Raises `Unavailable`. A write is
    checked against the grant by what it writes (`scope`, e.g. "reorders"), as grants name it (`write:reorders`)."""
    if conn is None:
        raise Unavailable("no such connection")
    if conn.state not in (ConnectionState.CONNECTED, ConnectionState.DEGRADED):
        raise Unavailable(f"{conn.id} is {conn.state.value}: {conn.blocked or conn.check_detail}")
    if not conn.can(kind, operation):
        what = f"{kind} {operation}" if operation else kind
        raise Unavailable(f"{conn.id}: {what} was not observed to be allowed (effective: {', '.join(conn.effective)})")
    grant = next((g for g in mandate.connections if g.id == conn.grant), None)
    if grant is None:
        raise Unavailable(f"{conn.id} is not granted by the mandate any more")
    wanted = "read" if kind in ("read", "measure") else f"write:{scope or operation}" if scope or operation else "write"
    if wanted not in grant.permissions and not (kind == "write" and "write" in grant.permissions):
        raise Unavailable(f"{conn.id}: the mandate grants {grant.permissions}, not {wanted}")
    capability = "connection.read" if kind in ("read", "measure") else "connection.write"
    verdict = PolicyEngine(mandate).evaluate(
        ActionRequest(capability=capability, purpose=why, destinations=[grant_host(grant.location)])
    )
    if not verdict.allowed:
        raise Unavailable(f"{capability}: {'; '.join(verdict.reasons)}")
    return conn
