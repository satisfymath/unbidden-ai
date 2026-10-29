"""Withdrawing a lab verdict that does not hold, without erasing it (stage 9).

The B-7 L4 on Conduit's `commentaries.author_id` was a measurement artifact (criteria v1: one session per side, a
per-sample test). A revocation keeps the verdict, the experiment and every earlier decision; it adds the reason, the
criteria and the evidence that withdrew it, lowers the level to what is still shown (the finding reproduces: L2),
reopens the opportunity, and marks its unpublished proposals stale. Performance verdicts judged by criteria older
than the current ones are listed as pending revalidation until measured again (`pending`).
"""

from __future__ import annotations

from typing import Any

from unbidden.contracts.common import EvidenceLevel, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.lab.perfstats import SESSION_CRITERIA
from unbidden.store import Store


def revoke(store: Store, opp_id: str, why: str, *, criteria: str, evidence: str, by: str) -> Opportunity:
    opp = store.get("opportunities", opp_id, Opportunity)
    if opp is None:
        raise KeyError(opp_id)
    entry: dict[str, Any] = {
        "at": utc_now().isoformat(), "why": why, "criteria": criteria, "evidence": evidence, "by": by,
        "previous_level": int(opp.evidence_level), "previous_status": opp.status.value,
    }  # fmt: skip
    opp.details = {**opp.details, "revocations": [*opp.details.get("revocations", []), entry]}
    if opp.evidence_level > EvidenceLevel.REPRODUCTION:
        opp.evidence_level = EvidenceLevel.REPRODUCTION
    opp.status = OpportunityStatus.OPEN
    opp.updated_at = utc_now()
    store.put("opportunities", opp)
    for proposal in store.list("proposals", Proposal):
        if proposal.opportunity_id == opp_id and proposal.status is ProposalStatus.READY:
            proposal.status = ProposalStatus.STALE
            store.put("proposals", proposal)
    store.append_event(Event(type=EventType.VERDICT_REVOKED, actor=by, entity_id=opp_id, correlation_id=opp_id,
                             payload=entry))  # fmt: skip
    return opp


def pending(opp: Opportunity) -> str | None:
    """Why a performance verdict at L3 or above awaits revalidation, or None: judged by older criteria."""
    verdict = opp.details.get("verdict") or {}
    criteria = verdict.get("criteria") or {}
    if opp.evidence_level < EvidenceLevel.LAB_IMPROVEMENT or "min_median_improvement" not in criteria:
        return None
    if criteria.get("version") == SESSION_CRITERIA["version"]:
        return None
    return f"judged by criteria older than {SESSION_CRITERIA['version']}: pending revalidation"
