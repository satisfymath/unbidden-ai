from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, Cost, EvidenceLevel, Sha, new_id, utc_now


class TestOutcome(StrEnum):
    """What a test suite run on both sides says about a change. Only PASSED and PRE_EXISTING validate it (L4)."""

    __test__ = False  # not a pytest test class

    PASSED = "passed"  # nothing fails on either side
    PRE_EXISTING = "pre_existing"  # failures, none more frequent with the change
    REGRESSION = "regression"  # a test fails in every candidate round and in no baseline round
    FLAKIER = "flakier"  # a test fails in more candidate rounds than baseline rounds
    NOT_RUN = "not_run"  # the suite ran but collected no test
    INFRA_FAILURE = "infra_failure"  # the suite did not run, or failed on both sides without naming a test
    INCONCLUSIVE = "inconclusive"  # there was no suite to run on both sides


VALIDATING = frozenset({TestOutcome.PASSED, TestOutcome.PRE_EXISTING})
SUITE = "<suite>"  # a failure the runner could not attribute to a named test

# How each round of a suite went. Records written before these were kept have none; see TestSummary.status.
RAN, NOT_COLLECTED, INFRA_FAILED = "ran", "not_collected", "infra_failed"


class TestSummary(Contract):
    __test__ = False  # not a pytest test class

    rounds: int
    failed_per_round: list[list[str]]
    round_status: list[str] = Field(default_factory=list[str])  # RAN, NOT_COLLECTED or INFRA_FAILED per round
    collected_per_round: list[int | None] = Field(default_factory=list[int | None])  # None: the runner did not say

    def status(self, i: int) -> str:
        """A round's status; for an older record, an unattributed failure is taken as a suite that did not run."""
        if i < len(self.round_status):
            return self.round_status[i]
        return INFRA_FAILED if self.failed_per_round[i] == [SUITE] else RAN


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
    samples_before_ms: list[float] = Field(default_factory=list[float])
    samples_after_ms: list[float] = Field(default_factory=list[float])
    workload_sha256: str | None = None
    # Unbidden's commit and cleanliness, model routes, images, seed: what produced this measurement.
    provenance: dict[str, Any] = Field(default_factory=dict)
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
    merge_sha: Sha | None = None  # the commit the merge created on the base (squash merges rewrite history)
    egress_attempt_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
