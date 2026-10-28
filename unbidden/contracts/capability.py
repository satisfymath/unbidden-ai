"""A capability Unbidden lacks, named where it was noticed, and followed until it is filled or given up.

A need is not a suggestion to a person: the cycle builds it (Forge, judged by its oracle), the mandate's use gate
admits it or leaves it for a person's approval, and whatever waited for it is resumed. The permissions a need asks
are fixed when it is recorded and never wider than what reading its source already takes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from unbidden.contracts.common import Contract, EvidenceRef, utc_now


class NeedStatus(StrEnum):
    OPEN = "open"  # noticed, nothing built yet
    BUILDING = "building"
    AWAITING_APPROVAL = "awaiting_approval"  # built and validated; the mandate leaves its use to a person
    IN_USE = "in_use"
    FAILED = "failed"  # the last build failed; built again on the next attempt
    BLOCKED = "blocked"  # a person's decision is missing (a grant's scope, an approval); built again once it changes
    ABANDONED = "abandoned"  # every attempt failed; reopened only when its source changes


class CapabilityNeed(Contract):
    id: str
    kind: Literal["log_adapter", "stats_reader", "api_client", "api_extension"]
    source: str  # "compose:backend", "http://127.0.0.1:10000/stats"
    why: str
    evidence: list[EvidenceRef] = Field(default_factory=list[EvidenceRef])
    permissions: list[str] = Field(default_factory=lambda: ["runtime.read"])
    status: NeedStatus = NeedStatus.OPEN
    capability_id: str | None = None
    attempts: int = 0
    notes: list[str] = Field(default_factory=list[str])
    resume: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])  # jobs to queue once it is in use
    operations: list[str] = Field(default_factory=list[str])  # for an extension: the documented operations needed
    # What a person controls that the build depends on (a grant's permissions, a valid approval), as seen at the last
    # sighting; a blocked need is built again only when it differs from what it was blocked on. Not an attempt.
    condition: str = ""
    blocked_on: str | None = None
    unblocked: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @staticmethod
    def key(kind: str, source: str) -> str:
        return "need_" + hashlib.sha256(f"{kind}:{source}".encode()).hexdigest()[:16]
