"""Acceptance: what must hold for a change or an action to count, fixed before it is made, and what was observed.

A model may claim a problem is resolved; that claim is recorded and is never enough. A change is accepted only when
every condition fixed beforehand is satisfied by an observation made on what is deployed now. A condition that cannot
be checked leaves the result inconclusive; an observation made before a later change is stale.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from unbidden.contracts.common import Contract, new_id, utc_now

# Where a condition comes from: the person's goal, the mandate (declared checks), the data read, the project's own
# conventions, or a model's proposal (made before any change, then fixed like the others).
Source = Literal["goal", "mandate", "data", "project", "model"]
Kind = Literal["checks_pass", "keys_once", "information_kept", "marks", "action_effect"]
Status = Literal["satisfied", "failed", "unverifiable"]
State = Literal["proposed", "applied", "accepted", "rejected", "inconclusive", "stale"]


class Condition(Contract):
    """One thing that must hold. `spec` parameterises the kind; `satisfies` says in words what result counts."""

    id: str
    kind: Kind
    what: str
    source: Source
    spec: dict[str, Any] = Field(default_factory=dict[str, Any])
    satisfies: str
    if_unverifiable: Literal["inconclusive"] = "inconclusive"


class Outcome(Contract):
    condition: str
    status: Status
    observation: dict[str, Any] = Field(default_factory=dict[str, Any])  # what backs it: a digest, counts, a log tail
    basis: str  # what was observed: the deployed commit (or action id) the observation was made on
    at: datetime = Field(default_factory=utc_now)


class Acceptance(Contract):
    id: str = Field(default_factory=lambda: new_id("acc"))
    subject: str  # a goal run, an action
    conditions: list[Condition]
    sealed: str  # digest of the conditions when fixed; any later change to them is refused
    change: dict[str, Any] = Field(default_factory=dict[str, Any])  # what was proposed / applied (commit, patch digest)
    model_claim: Literal["resolved", "unresolved", "none", "unusable"] = "none"
    outcomes: list[Outcome] = Field(default_factory=list[Outcome])
    state: State = "proposed"
    why: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    @staticmethod
    def seal(conditions: list[Condition]) -> str:
        return hashlib.sha256(
            json.dumps([c.model_dump(mode="json") for c in conditions], sort_keys=True).encode()
        ).hexdigest()
