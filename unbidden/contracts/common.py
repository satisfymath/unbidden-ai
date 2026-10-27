from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _full_sha(value: str) -> str:
    # Prefixes caused silent mismatches between versions; only full object names are accepted.
    if not _FULL_SHA.match(value):
        raise ValueError(f"expected a full 40-character git SHA, got {value!r}")
    return value


Sha = Annotated[str, AfterValidator(_full_sha)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)


class EpistemicStatus(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"
    VERIFIED = "verified"
    OBSOLETE = "obsolete"


class EvidenceLevel(IntEnum):
    REASONABLE_SUSPICION = 1
    REPRODUCTION = 2
    LAB_IMPROVEMENT = 3
    FUNCTIONAL_VALIDATION = 4
    OPERATIONAL_RESULT = 5
    PERSISTENCE = 6


_CONFIDENCE_CAP: dict[EvidenceLevel, float] = {
    EvidenceLevel.REASONABLE_SUSPICION: 0.60,
    EvidenceLevel.REPRODUCTION: 0.75,
    EvidenceLevel.LAB_IMPROVEMENT: 0.85,
    EvidenceLevel.FUNCTIONAL_VALIDATION: 0.92,
    EvidenceLevel.OPERATIONAL_RESULT: 0.97,
    EvidenceLevel.PERSISTENCE: 0.99,
}
CONFIDENCE_FLOOR = 0.20


def capped_confidence(claimed: float, level: EvidenceLevel) -> float:
    """A model's own confidence never exceeds what the evidence level supports."""
    return max(CONFIDENCE_FLOOR, min(claimed, _CONFIDENCE_CAP[level]))


EvidenceKind = Literal[
    "file",
    "commit",
    "diff",
    "analyzer_report",
    "sandbox_run",
    "model_run",
    "egress_attempt",
    "experiment",
    "test_run",
    "config",
]


class EvidenceRef(Contract):
    kind: EvidenceKind
    locator: str = Field(min_length=1)
    sha256: str | None = None
    note: str | None = None
    captured_at: datetime = Field(default_factory=utc_now)


class Cost(Contract):
    tokens_in: int = 0
    tokens_out: int = 0
    compute_seconds: float = 0.0
    usd_local: float = 0.0
    usd_remote: float = 0.0

    @property
    def usd(self) -> float:
        return self.usd_local + self.usd_remote

    def __add__(self, other: Cost) -> Cost:
        return Cost(
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            compute_seconds=self.compute_seconds + other.compute_seconds,
            usd_local=self.usd_local + other.usd_local,
            usd_remote=self.usd_remote + other.usd_remote,
        )
