from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from unbidden.contracts.common import Contract, Cost, EvidenceLevel, Sha, new_id, utc_now


class TestOutcome(StrEnum):
    PASSED = "passed"
    REGRESSION = "regression"
    PRE_EXISTING = "pre_existing"
    INCONCLUSIVE = "inconclusive"


class TestSummary(Contract):
    rounds: int
    failed_per_round: list[list[str]]


class Experiment(Contract):
    id: str = Field(default_factory=lambda: new_id("exp"))
    opportunity_id: str
    base_sha: Sha
    candidate_patch_sha256: str
    rounds: int = 3
    baseline_tests: TestSummary | None = None
    candidate_tests: TestSummary | None = None
    findings_before: list[str] = Field(default_factory=list)
    findings_after: list[str] = Field(default_factory=list)
    cost: Cost = Field(default_factory=Cost)
    started_at: datetime = Field(default_factory=utc_now)


class Verdict(Contract):
    experiment_id: str
    improved: bool
    evidence_level: EvidenceLevel
    criteria: dict[str, float | int | str]
    tests: TestOutcome
    reasons: list[str]
    caveats: list[str] = Field(default_factory=list)


class ProposalStatus(StrEnum):
    READY = "ready"
    PUBLISHING = "publishing"
    PR_OPENED = "pr_opened"
    MERGED = "merged"
    CLOSED_UNMERGED = "closed_unmerged"
    STALE = "stale"
    REJECTED = "rejected"


class PullRequestRef(Contract):
    number: int
    url: str
    head_sha: Sha


class Proposal(Contract):
    id: str = Field(default_factory=lambda: new_id("prop"))
    opportunity_id: str
    experiment_id: str
    branch: str
    base_sha: Sha
    commit_sha: Sha
    title: str = Field(max_length=120)
    body_md: str
    evidence_level: EvidenceLevel
    status: ProposalStatus = ProposalStatus.READY
    pr: PullRequestRef | None = None
    egress_attempt_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
