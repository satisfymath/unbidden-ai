"""A connection: a resource of the project, and what Unbidden can actually do with it, as last checked.

Knowing a resource exists, being able to reach it, understanding it and being allowed to change it are different
things, and each is recorded apart:
- `state` says whether a check reached it with working credentials (never set to `connected` without one);
- `requested` is what the mandate grants; `effective` is what the last check observed the credentials can do;
- `abilities` lists read, measure and write operations, each with how it is known.
Credentials appear only as a reference to the broker (`credential_ref`), never as a value.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, utc_now


class ConnectionState(StrEnum):
    DISCOVERED = "discovered"  # seen (a config value, a remote, a compose service); not configured to connect
    NEEDS_CONFIGURATION = "needs_configuration"  # granted, but something to connect with is missing (a location)
    NEEDS_AUTHORIZATION = "needs_authorization"  # reachable, but no working credential or no grant to use it
    NEEDS_CAPABILITY = "needs_capability"  # reachable and authorized; Unbidden has no integration to use it yet
    CONNECTED = "connected"  # a check reached it with its credential; `effective` holds what it could do
    DEGRADED = "degraded"  # reached, but some checks failed (an operation erroring, a timeout)
    REVOKED = "revoked"  # its credential stopped working, or the grant was withdrawn
    GONE = "gone"  # the resource is no longer where it was


USABLE = frozenset({ConnectionState.CONNECTED, ConnectionState.DEGRADED})


class Environment(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Ability(Contract):
    kind: str  # read | measure | write
    operations: list[str] = Field(default_factory=list)
    known_by: str  # "checked: <how>" or "declared: <where>"; only checked abilities may be used


class Connection(Contract):
    id: str  # "<kind>:<location>", stable across checks, however it was found
    project: str
    grant: str | None = None  # the mandate's grant for it, when a person authorized it
    kind: str  # postgres | http_api | github | compose | prometheus | jaeger
    protocol: str
    location: str
    environment: Environment = Environment.LOCAL
    discovered_by: list[str] = Field(default_factory=list)  # where it was seen, each with its evidence
    credential_ref: str | None = None
    requested: list[str] = Field(default_factory=list)
    effective: list[str] = Field(default_factory=list)
    abilities: list[Ability] = Field(default_factory=list[Ability])
    state: ConnectionState = ConnectionState.DISCOVERED
    checked_at: datetime | None = None
    check_detail: str = ""
    limits: dict[str, Any] = Field(default_factory=dict)
    network: str = ""  # the only destination its checks and reads may reach
    relations: list[dict[str, str]] = Field(
        default_factory=list[dict[str, str]]
    )  # {"predicate", "target"} to other resources
    capability_id: str | None = None  # the integration it is used through, when Forge built one
    blocked: str | None = None
    next_step: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list[dict[str, str]])  # state changes, with their reason
    updated_at: datetime = Field(default_factory=utc_now)

    def can(self, kind: str, operation: str | None = None) -> bool:
        """Whether a checked ability allows this, on a usable connection."""
        if self.state not in USABLE:
            return False
        return any(
            a.kind == kind and a.known_by.startswith("checked") and (operation is None or operation in a.operations)
            for a in self.abilities
        )
