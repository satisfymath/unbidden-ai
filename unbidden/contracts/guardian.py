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
    deploy: Autonomy = Autonomy.DENY
    rollback: Autonomy = Autonomy.DENY


class ProbeAuth(Contract):
    """How probes log in. Credentials are read from the environment (unbidden's own .env), never stored."""

    username_env: str = "UNBIDDEN_PROBE_USERNAME"
    password_env: str = "UNBIDDEN_PROBE_PASSWORD"


class OperationsPolicy(Contract):
    """How this system is deployed and watched. Declared by a person; unbidden never invents a deploy."""

    deploy_steps: list[list[str]] = Field(default_factory=list[list[str]])  # argv lists, run in the repo
    probe_every_s: float = Field(default=5.0, gt=0)
    probe_auth: ProbeAuth | None = None
    max_merges_per_hour: int = Field(default=2, ge=0)
    max_deploys_per_hour: int = Field(default=2, ge=0)
    guard_samples: int = Field(default=15, ge=5)  # per side, per endpoint, before judging a deploy


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
    operations: OperationsPolicy = Field(default_factory=OperationsPolicy)


class Hold(Contract):
    """A stop on autonomous changes, set by unbidden after a bad outcome. Only a person releases it."""

    id: str = Field(default_factory=lambda: new_id("hold"))
    reason: str
    created_at: datetime = Field(default_factory=utc_now)
    released_by: str | None = None
    released_at: datetime | None = None


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


class EgressAttempt(Contract):
    """One attempt to send something off this machine, allowed or not, with what it carried."""

    id: str = Field(default_factory=lambda: new_id("egr"))
    status: Literal["allowed_pending", "allowed_sent", "blocked", "failed"]
    purpose: str
    destination: str
    provider: str
    model: str | None = None
    verdict: EgressVerdict
    payload: str  # the exact payload when allowed; only "sha256:<hash>" when blocked
    created_at: datetime = Field(default_factory=utc_now)
