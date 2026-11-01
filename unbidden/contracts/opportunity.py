from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, EvidenceLevel, EvidenceRef, new_id, utc_now


class OpportunityStatus(StrEnum):
    OPEN = "open"
    EXPERIMENTING = "experimenting"
    PROPOSED = "proposed"
    DECLINED = "declined"
    VERIFIED = "verified"
    CLOSED = "closed"


class Opportunity(Contract):
    id: str = Field(default_factory=lambda: new_id("opp"))
    source: str
    category: str = Field(max_length=40)
    title: str = Field(max_length=200)
    summary: str
    dedup_key: str
    evidence_level: EvidenceLevel = EvidenceLevel.REASONABLE_SUSPICION
    status: OpportunityStatus = OpportunityStatus.OPEN
    evidence: list[EvidenceRef] = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    priority_score: float = 0.0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ActionKind(StrEnum):
    WAIT = "wait"
    RUN_EXPERIMENT = "run_experiment"
    DELEGATE_SYNTHETIC = "delegate_synthetic"
    PROPOSE_CHANGE = "propose_change"
    REQUEST_APPROVAL = "request_approval"
    DECLINE = "decline"
    MEASURE = "measure"  # observe what the opportunity's value depends on before spending on it
    ACQUIRE_CAPABILITY = "acquire_capability"  # build or reuse the capability the decision needs
    INVESTIGATE = "investigate"  # look for the cause of a runtime signal


class CandidateAction(Contract):
    kind: ActionKind
    p_success: float = Field(ge=0.0, le=1.0)
    value: float
    cost_usd: float = Field(ge=0.0)
    risk: float = Field(ge=0.0, le=1.0)
    utility: float
    reason: str


class Decision(Contract):
    id: str = Field(default_factory=lambda: new_id("dec"))
    opportunity_id: str
    evidence_level: EvidenceLevel
    candidates: list[CandidateAction]
    chosen: ActionKind
    reason: str
    decided_at: datetime = Field(default_factory=utc_now)
