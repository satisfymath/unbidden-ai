from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, utc_now


class EventType(StrEnum):
    WORKSPACE_INITIALIZED = "workspace.initialized"
    HEAD_MOVED = "repo.head_moved"
    ANALYZER_RAN = "analyzer.ran"
    OPPORTUNITY_OPENED = "opportunity.opened"
    OPPORTUNITY_RESOLVED = "opportunity.resolved"
    DECISION_MADE = "decision.made"
    EXPERIMENT_STARTED = "experiment.started"
    VERDICT_RECORDED = "verdict.recorded"
    PROPOSAL_READY = "proposal.ready"
    PROPOSAL_PUBLISHED = "proposal.published"
    PROPOSAL_STALE = "proposal.stale"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"
    EGRESS_ALLOWED = "egress.allowed"
    EGRESS_BLOCKED = "egress.blocked"
    POLICY_DENIED = "policy.denied"
    MODEL_CALLED = "model.called"
    MODEL_FALLBACK = "model.fallback"
    KILL_SWITCH = "killswitch.changed"
    MANDATE_CHANGED = "mandate.changed"
    DEPLOYED = "operations.deployed"
    MERGED = "operations.merged"
    IMPACT_JUDGED = "impact.judged"
    OUTCOME_RECORDED = "outcome.recorded"
    OUTCOME_HELD = "outcome.held"
    OUTCOME_INVALIDATED = "outcome.invalidated"
    CAPABILITY_BUILT = "capability.built"
    CAPABILITY_APPROVED = "capability.approved"
    CAPABILITY_NEEDED = "capability.needed"
    CONNECTION_CHANGED = "connection.changed"
    ACTION_EXECUTED = "action.executed"
    CAPABILITY_NEED_CHANGED = "capability.need_changed"
    HYPOTHESIS_RECORDED = "hypothesis.recorded"
    WORLD_CHANGED = "world.changed"
    DEPLOYMENT_OBSERVED = "deployment.observed"
    ANOMALY_DETECTED = "anomaly.detected"
    ANOMALY_RESOLVED = "anomaly.resolved"
    LOG_SIGNAL = "log.signal"


class Event(Contract):
    seq: int | None = None
    ts: datetime = Field(default_factory=utc_now)
    type: EventType
    actor: str
    entity_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditEntry(Contract):
    ts: datetime = Field(default_factory=utc_now)
    actor: str
    kind: str
    summary: str
    correlation_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
