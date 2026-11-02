"""A person's decisions written while the agent owns the workspace: no lost updates, no duplicate effects, no
half-written state. Every decision is one `BEGIN IMMEDIATE` transaction; SQLite serialises them across connections,
which is what two processes (the CLI, the dashboard, the agent) are."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.events import EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import Approval
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.operate.decisions import DecisionError, approve_by_id, reject_by_id
from unbidden.store import Store

pytestmark = pytest.mark.unit

SHA = "a" * 40


def _opportunity(i: int) -> Opportunity:
    return Opportunity(
        id=f"opp_{i:012d}", source="t", category="perf", title=f"opp {i}", summary="s", dedup_key=f"k{i}",
        evidence=[EvidenceRef(kind="file", locator="x")], details={"decision": {"chosen": "wait"}},
    )  # fmt: skip


def _proposal(opp: str) -> Proposal:
    return Proposal(opportunity_id=opp, experiment_id="exp_1", branch=f"unbidden/{opp}", base_sha=SHA, commit_sha=SHA,
                    title="fix", body_md="b", evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION)  # fmt: skip


@pytest.fixture
def db(tmp_path: Path) -> Path:
    store = Store(tmp_path / "state.db")
    for i in range(3):
        store.put("opportunities", _opportunity(i))
        store.put("proposals", _proposal(f"opp_{i:012d}"), key=f"opp_{i:012d}")
    store.close()
    return tmp_path / "state.db"


def test_eight_concurrent_approvals_of_one_proposal_grant_once_and_queue_one_job(db: Path) -> None:
    def approve(n: int) -> dict:  # type: ignore[type-arg]
        store = Store(db)  # each caller its own connection, as separate processes would be
        try:
            return approve_by_id(store, "opp_000000000000", by=f"p{n}", hours=1)
        finally:
            store.close()

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(approve, range(8)))
    store = Store(db)
    approvals = store.list("approvals", Approval)
    assert len(approvals) == 1, "one valid approval, however many people clicked"
    assert len([e for e in store.events() if e.type is EventType.APPROVAL_GRANTED]) == 1
    publish = [j for j in store.jobs() if j.type == "github.publish"]
    assert len(publish) == 1, "one publish job for the one approval"
    assert sum(1 for r in results if not r["already"]) == 1 and all(r["approval"] == approvals[0].id for r in results)


def test_a_rejection_keeps_what_the_agent_wrote_meanwhile_and_is_idempotent(db: Path) -> None:
    """The agent updates the opportunity (its details) in its own transactions while a person rejects it: both
    writes survive, the status is DECLINED, and a second rejection changes nothing."""
    stop = threading.Event()
    writes = {"n": 0}

    def agent() -> None:
        store = Store(db)
        try:
            while not stop.is_set():
                with store.transaction():
                    opp = store.get("opportunities", "opp_000000000001", Opportunity)
                    assert opp is not None
                    opp.details = {**opp.details, "agent_ticks": opp.details.get("agent_ticks", 0) + 1}
                    store.put("opportunities", opp)
                writes["n"] += 1
                time.sleep(0.001)  # the agent writes often, not in a closed loop
        finally:
            store.close()

    t = threading.Thread(target=agent)
    t.start()
    try:
        deadline = time.monotonic() + 10
        while writes["n"] < 1 and time.monotonic() < deadline:  # the agent is writing before the person decides
            time.sleep(0.005)
        assert writes["n"] >= 1, "the agent thread never wrote"
        store = Store(db)
        first = reject_by_id(store, "opp_000000000001", by="p", reason="not worth it")
        ticks_at_reject = writes["n"]
        while writes["n"] < ticks_at_reject + 2 and time.monotonic() < deadline:  # and keeps writing after it
            time.sleep(0.005)
        second = reject_by_id(store, "opp_000000000001", by="p", reason="again")
    finally:
        stop.set()
        t.join()
    assert first["already"] is False and second["already"] is True
    opp = store.get("opportunities", "opp_000000000001", Opportunity)
    assert opp is not None and opp.status is OpportunityStatus.DECLINED
    assert opp.details["rejected_because"] == "not worth it", "the second rejection did not overwrite the first"
    assert opp.details.get("agent_ticks", 0) >= 1 and writes["n"] >= 1, "the agent's writes were not lost"
    assert opp.details["decision"] == {"chosen": "wait"}
    assert len([e for e in store.events() if e.type is EventType.APPROVAL_REJECTED]) == 1
    proposal = store.get_by_key("proposals", "opp_000000000001", Proposal)
    assert proposal is not None and proposal.status is ProposalStatus.REJECTED


def test_approve_and_reject_racing_on_one_opportunity_leave_a_consistent_record(db: Path) -> None:
    """Whichever wins, the record is one of the two consistent outcomes, never a mix."""
    outcomes = []

    def approve() -> None:
        store = Store(db)
        try:
            outcomes.append(("approve", approve_by_id(store, "opp_000000000002", by="a", hours=1)))
        finally:
            store.close()

    def reject() -> None:
        store = Store(db)
        try:
            outcomes.append(("reject", reject_by_id(store, "opp_000000000002", by="r", reason="no")))
        finally:
            store.close()

    threads = [threading.Thread(target=approve), threading.Thread(target=reject)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    store = Store(db)
    proposal = store.get_by_key("proposals", "opp_000000000002", Proposal)
    opp = store.get("opportunities", "opp_000000000002", Opportunity)
    assert proposal is not None and opp is not None
    assert opp.status is OpportunityStatus.DECLINED and proposal.status is ProposalStatus.REJECTED
    granted = [e for e in store.events() if e.type is EventType.APPROVAL_GRANTED]
    rejected = [e for e in store.events() if e.type is EventType.APPROVAL_REJECTED]
    assert len(granted) == 1 and len(rejected) == 1, "each decision recorded exactly once"
    # a publish job may exist from the approval; the publisher refuses a REJECTED proposal, so it has no effect


def test_unknown_subjects_are_refused_without_writing(db: Path) -> None:
    store = Store(db)
    before = len(store.events())
    with pytest.raises(DecisionError):
        approve_by_id(store, "opp_nothing", by="p", hours=1)
    with pytest.raises(DecisionError):
        reject_by_id(store, "opp_nothing", by="p", reason="x")
    assert len(store.events()) == before and store.jobs() == []
