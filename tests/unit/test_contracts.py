from __future__ import annotations

import pytest
from pydantic import ValidationError

from unbidden.contracts.common import EvidenceLevel, EvidenceRef, capped_confidence
from unbidden.contracts.experiment import Proposal
from unbidden.contracts.finding import Finding
from unbidden.contracts.opportunity import Opportunity

pytestmark = pytest.mark.unit

SHA = "a" * 40


def test_confidence_is_capped_by_evidence() -> None:
    assert capped_confidence(0.95, EvidenceLevel.REASONABLE_SUSPICION) == 0.60
    assert capped_confidence(0.05, EvidenceLevel.FUNCTIONAL_VALIDATION) == 0.20
    assert capped_confidence(0.80, EvidenceLevel.FUNCTIONAL_VALIDATION) == 0.80


def test_short_shas_are_rejected() -> None:
    kwargs = dict(
        opportunity_id="o",
        experiment_id="e",
        branch="b",
        commit_sha=SHA,
        title="t",
        body_md="b",
        evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
    )
    Proposal(base_sha=SHA, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Proposal(base_sha="abc1234", **kwargs)  # type: ignore[arg-type]


def test_fingerprint_ignores_line_numbers() -> None:
    a = Finding.build(tool="tsc", rule="TS2322", severity="error", category="types", path="a.ts", message="m", line=3)
    b = Finding.build(tool="tsc", rule="TS2322", severity="error", category="types", path="a.ts", message="m", line=9)
    assert a.fingerprint == b.fingerprint


def test_opportunity_needs_evidence() -> None:
    with pytest.raises(ValidationError):
        Opportunity(source="tsc", category="types", title="t", summary="s", dedup_key="k", evidence=[])
    Opportunity(
        source="tsc",
        category="types",
        title="t",
        summary="s",
        dedup_key="k",
        evidence=[EvidenceRef(kind="analyzer_report", locator="tsc@" + SHA)],
    )
