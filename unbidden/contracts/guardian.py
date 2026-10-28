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
    use_new_capabilities: Autonomy = Autonomy.DENY
    act_on_connections: Autonomy = Autonomy.DENY  # write operations a connection grant permits


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
    ui_capture_retention_days: float = Field(default=14.0, ge=0)  # screenshots of anomalies, kept locally


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
    # What resolving one opportunity of a category is worth to this team, in hours of a person's work saved;
    # categories not named keep the Director's defaults. Editable: it is the mandate's statement of value.
    value_hours: dict[str, float] = Field(default_factory=dict[str, float])
    # A live result (L5) is checked again about once a day; held for this long, it is persistent (L6).
    persistence_days: float = Field(default=7.0, gt=0)


class ModelsPolicy(Contract):
    """Which models may serve this workspace. Secrets and production data stay local in every profile."""

    profile: Literal["local", "local-first", "frontier"] = "local-first"
    private_code_to_frontier: Literal["deny", "allow"] = "deny"
    # Screenshots of the project's own pages may be shown to a remote multimodal model. Images cannot be scanned for
    # secrets the way text is, so this is a person's explicit choice per workspace, off by default.
    screenshots_to_frontier: Literal["deny", "allow"] = "deny"
    # When the chosen remote model fails or is refused, whether the local model takes over. Every fallback is
    # recorded either way; "deny" keeps a remote-first run from loading a large local model unannounced.
    local_fallback: Literal["allow", "deny"] = "allow"


class ConnectionGrant(Contract):
    """A resource a person authorizes Unbidden to connect to, and what it may do there. A grant is not a check:
    what the credential can really do is observed, and only the smaller of the two is used."""

    id: str = Field(min_length=1)  # a name for the resource in this project
    kind: Literal["postgres", "http_api", "github"]
    location: str  # host:port/database, a base URL, or owner/name
    environment: Literal["local", "development", "staging", "production"] = "staging"
    credential_ref: str | None = None  # a broker name, never a value
    username: str | None = None  # where the protocol needs one apart from the secret
    tls: Literal["disable", "prefer", "require", "verify-full"] = "prefer"
    docs: str | None = None  # where its documentation may be read (an OpenAPI URL, a file in the repository)
    permissions: list[str] = Field(default_factory=lambda: ["read"])  # read, write:<what>
    limits: dict[str, float] = Field(default_factory=dict)  # e.g. max_units, requests_per_minute, timeout_s


class Goal(Contract):
    """An objective in a person's words, with the bounds on what may be done for it."""

    id: str = Field(min_length=1)
    statement: str
    bounds: dict[str, float | int | str] = Field(default_factory=dict)


class Mandate(Contract):
    workspace: str = Field(min_length=1)
    priorities: list[str] = Field(default_factory=list)
    business_constraints: BusinessConstraints = Field(default_factory=BusinessConstraints)
    autonomy: AutonomyPolicy = Field(default_factory=AutonomyPolicy)
    egress: EgressPolicy = Field(default_factory=EgressPolicy)
    evaluation: EvaluationPolicy = Field(default_factory=EvaluationPolicy)
    operations: OperationsPolicy = Field(default_factory=OperationsPolicy)
    models: ModelsPolicy = Field(default_factory=ModelsPolicy)
    connections: list[ConnectionGrant] = Field(default_factory=list[ConnectionGrant])
    goals: list[Goal] = Field(default_factory=list[Goal])


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


EgressKind = Literal["synthetic_task", "github", "package_registry", "screenshots"]


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
