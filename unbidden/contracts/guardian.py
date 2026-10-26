from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from unbidden.contracts.common import Contract, new_id, utc_now


class Autonomy(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class AutonomyPolicy(Contract):
    """Every field defaults to deny: a mandate grants autonomy, it never inherits it."""

    observe: Autonomy = Autonomy.DENY
    run_experiments: Autonomy = Autonomy.DENY
    provision_dependencies: Autonomy = Autonomy.DENY
    delegate_synthetic: Autonomy = Autonomy.DENY
    open_pull_requests: Autonomy = Autonomy.DENY
    merge_pull_requests: Autonomy = Autonomy.DENY


class BusinessConstraints(Contract):
    maximum_monthly_spend_usd: float = Field(default=10.0, ge=0.0)
    destructive_operations: Literal["deny"] = "deny"


class GitHubPolicy(Contract):
    repository: str | None = Field(default=None, pattern=r"^[\w.-]+/[\w.-]+$")
    base_branch: str = "main"
    token_env: str = "GITHUB_TOKEN"
    max_open_pull_requests: int = Field(default=3, ge=0)
    max_payload_bytes: int = Field(default=200_000, gt=0)


class RemoteModelPolicy(Contract):
    """Where synthetic tasks may go, and how much may leave per call."""

    destinations: list[str] = Field(default_factory=list)
    max_payload_bytes: int = Field(default=20_000, gt=0)
    max_tokens_per_call: int = Field(default=16_000, gt=0)


class EgressPolicy(Contract):
    package_registries: list[str] = Field(default_factory=list)
    remote_models: RemoteModelPolicy = Field(default_factory=RemoteModelPolicy)
    github: GitHubPolicy = Field(default_factory=GitHubPolicy)


class EvaluationPolicy(Contract):
    minimum_evidence_for_proposal: int = Field(default=4, ge=1, le=6)
    alpha: float = Field(default=0.01, gt=0.0, lt=1.0)
    min_relative_effect: float = Field(default=0.20, gt=0.0)


class Mandate(Contract):
    workspace: str = Field(min_length=1)
    priorities: list[str] = Field(default_factory=list)
    business_constraints: BusinessConstraints = Field(default_factory=BusinessConstraints)
    autonomy: AutonomyPolicy = Field(default_factory=AutonomyPolicy)
    egress: EgressPolicy = Field(default_factory=EgressPolicy)
    evaluation: EvaluationPolicy = Field(default_factory=EvaluationPolicy)


class ActionRequest(Contract):
    capability: str
    purpose: str
    destinations: list[str] = Field(default_factory=list)
    destructive: bool = False
    approval_id: str | None = None


class Decision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class PolicyVerdict(Contract):
    decision: Decision
    rule: str
    reasons: list[str]

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


EgressKind = Literal["synthetic_task", "github", "package_registry"]


class EgressVerdict(Contract):
    allowed: bool
    kind: EgressKind
    destination: str
    reasons: list[str]
    matched: list[str] = Field(default_factory=list)
    payload_sha256: str
    payload_bytes: int


class Approval(Contract):
    id: str = Field(default_factory=lambda: new_id("apr"))
    capability: str
    subject_id: str
    granted_by: str
    expires_at: datetime
    max_uses: int = Field(default=1, ge=1)
    uses: int = 0
    created_at: datetime = Field(default_factory=utc_now)
