"""A person's decisions about the engine's work, written the same way from the CLI, the dashboard served apart or
the dashboard served by the agent: approve a proposal, reject an opportunity, approve writes through a connection.

Each one runs in ONE store transaction (`BEGIN IMMEDIATE`, which SQLite serialises across connections and processes,
so a decision never interleaves with the agent's own writes or with another decision): read, check, write, event,
job, all or nothing. These are not jobs and take no engine lock (`daemon/owner.py`); the loop reads them on its next
cycle ("the pull request opens on the next cycle"), and a decision made while the agent is stopped waits in the
store for `unbidden start`. Approving is idempotent: a proposal that already holds a valid approval gets no second
approval, event or publish job. Every decision leaves its event
(APPROVAL_GRANTED, APPROVAL_REJECTED) with `person:<who>` as actor; the effect itself (publishing, writing) still
passes the PolicyEngine and the kill switch when the engine runs it. This module imports nothing from `unbidden.web`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.store import Store


class DecisionError(ValueError):
    """What was asked cannot be decided: no such proposal, opportunity or connection."""


def proposal_for(store: Store, opportunity_id: str) -> Proposal | None:
    return store.get_by_key("proposals", opportunity_id, Proposal)


def approve(store: Store, proposal: Proposal, *, by: str, hours: float) -> dict[str, Any]:
    """Allow the pull request of a proven opportunity for `hours`; the publish job is queued for the next cycle."""
    from unbidden.daemon.cycle import job
    from unbidden.guardian.approvals import find_valid, grant
    from unbidden.publish.github import CAPABILITY

    with store.transaction():
        existing = find_valid(store, CAPABILITY, proposal.id)
        approval = existing or grant(store, CAPABILITY, proposal.id, granted_by=by, ttl=timedelta(hours=hours))
        if existing is None:
            store.append_event(
                Event(
                    type=EventType.APPROVAL_GRANTED,
                    actor=f"person:{by}",
                    entity_id=approval.id,
                    correlation_id=proposal.opportunity_id,
                    payload={"capability": CAPABILITY, "proposal": proposal.id},
                )
            )
        queued = store.enqueue(
            job(
                "github.publish",
                f"{proposal.id}:{approval.id}",
                {"id": proposal.id},
                correlation_id=proposal.opportunity_id,
            )
        )
    return {
        "approval": approval.id,
        "proposal": proposal.id,
        "branch": proposal.branch,
        "expires_at": approval.expires_at,
        "already": existing is not None,
        "queued": queued,
    }


def approve_by_id(store: Store, opportunity_id: str, *, by: str, hours: float) -> dict[str, Any]:
    proposal = proposal_for(store, opportunity_id)
    if proposal is None:
        raise DecisionError(f"no proposal for {opportunity_id} yet")
    return approve(store, proposal, by=by, hours=hours)


def reject(store: Store, opp: Opportunity, *, by: str, reason: str) -> dict[str, Any]:
    """Decline an opportunity for good; a ready proposal for it is rejected too. The opportunity is re-read inside
    the transaction, so a field the agent wrote meanwhile is kept (no lost update); a second rejection changes
    nothing."""
    with store.transaction():
        current = store.get("opportunities", opp.id, Opportunity) or opp
        proposal = proposal_for(store, opp.id)
        if current.status is OpportunityStatus.DECLINED:
            rejected = proposal is not None and proposal.status is ProposalStatus.REJECTED
            return {"opportunity": opp.id, "proposal_rejected": rejected, "already": True}
        current.status = OpportunityStatus.DECLINED
        current.details = {**current.details, "rejected_because": reason}
        store.put("opportunities", current)
        if proposal is not None and proposal.status is ProposalStatus.READY:
            proposal.status = ProposalStatus.REJECTED
            store.put("proposals", proposal)
        store.append_event(
            Event(
                type=EventType.APPROVAL_REJECTED,
                actor=f"person:{by}",
                entity_id=opp.id,
                correlation_id=opp.id,
                payload={"reason": reason},
            )
        )
    opp.status, opp.details = current.status, current.details  # the caller's copy follows what was written
    rejected = proposal is not None and proposal.status is ProposalStatus.REJECTED
    return {"opportunity": opp.id, "proposal_rejected": rejected, "already": False}


def reject_by_id(store: Store, opportunity_id: str, *, by: str, reason: str) -> dict[str, Any]:
    opp = store.get("opportunities", opportunity_id, Opportunity)
    if opp is None:
        raise DecisionError(f"no opportunity {opportunity_id}")
    return reject(store, opp, by=by, reason=reason)


def approve_writes(store: Store, mandate: Any, grant_id: str, *, by: str, hours: float) -> dict[str, Any]:
    """A time-limited approval to change one granted connection (its grant's limits still apply); a connection that
    already holds a valid write approval gets no second one."""
    from unbidden.connect.effects import WRITE
    from unbidden.connect.effects import approve_writes as _approve_writes
    from unbidden.connect.registry import by_grant
    from unbidden.guardian.approvals import find_valid

    with store.transaction():
        conn = by_grant(store, grant_id)
        existing = find_valid(store, WRITE, conn.id) if conn is not None else None
        if existing is not None:
            return {"approval": existing.id, "grant": grant_id, "expires_at": existing.expires_at, "already": True}
        try:
            approval = _approve_writes(store, mandate, grant_id, f"person:{by}", hours)
        except ValueError as exc:
            raise DecisionError(str(exc)) from exc
    return {"approval": approval.id, "grant": grant_id, "expires_at": approval.expires_at, "already": False}
