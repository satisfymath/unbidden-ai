"""An action on a connected resource: what it targets, with what, under which conditions, how it is checked.

Proposing, validating and executing are separate states, so a procedure found in a repository (a script, a
workflow, a README) can be proposed without ever being taken as authorization. A compensation is declared available
only when it was observed to work (`known_by`); otherwise the action has none, and says so.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, new_id, utc_now


class ActionStatus(StrEnum):
    PROPOSED = "proposed"  # described; nothing checked or done
    REFUSED = "refused"  # a precondition, the gate or a bound said no
    EXECUTED = "executed"  # done; its effect not yet read back
    VERIFIED = "verified"  # its effect was read back as intended
    UNVERIFIED = "unverified"  # done, but the read-back did not show the intended effect
    FAILED = "failed"
    COMPENSATED = "compensated"  # undone by its compensation, observed


class Compensation(Contract):
    operation: str | None = None
    available: bool = False
    known_by: str = "no compensation was observed to work"


class Action(Contract):
    id: str = Field(default_factory=lambda: new_id("act"))
    kind: str  # api_call | deploy_steps
    goal: str | None = None
    connection: str | None = None
    environment: str
    operation: str
    params: dict[str, Any] = Field(default_factory=dict[str, Any])
    body: dict[str, Any] | None = None
    idempotency_key: str
    requires: str  # the capability the gate checks ("connection.write", "deploy.run")
    preconditions: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])  # {"what", "held", "observed"}
    timeout_s: float = 30.0
    status: ActionStatus = ActionStatus.PROPOSED
    reason: str = ""
    result: dict[str, Any] = Field(default_factory=dict[str, Any])
    evidence: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    verification: dict[str, Any] = Field(default_factory=dict[str, Any])
    compensation: Compensation = Field(default_factory=Compensation)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
