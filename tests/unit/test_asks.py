"""The agent's questions as records: opened once per subject, answered with the CLI's own effect, withdrawn when the
matter is settled another way; the pipeline stage an opportunity has reached."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.events import EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.director import asks
from unbidden.director.blocks import classify, record
from unbidden.director.pipeline import OF, describe, job_stage, stage_of
from unbidden.operate.holds import active, place
from unbidden.store import Store

pytestmark = pytest.mark.unit


def _proposal(store: Store, opp_id: str = "opp_1") -> Proposal:
    sha = "a" * 40
    opp = Opportunity(id=opp_id, source="t", category="perf", title="Index bill.payer_id", summary="s",
                      dedup_key=opp_id, evidence=[EvidenceRef(kind="file", locator="x")],
                      evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
                      status=OpportunityStatus.PROPOSED)  # fmt: skip
    store.put("opportunities", opp, key=opp.dedup_key)
    proposal = Proposal(opportunity_id=opp_id, experiment_id="exp_1", branch="unbidden/index", base_sha=sha,
                        commit_sha=sha, title="Index bill.payer_id", body_md="body",
                        evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION)  # fmt: skip
    store.put("proposals", proposal, key=opp_id)
    return proposal


def test_an_ask_opens_once_per_subject_and_writes_one_event(store: Store) -> None:
    proposal = _proposal(store)
    first = asks.open_ask(store, asks.for_approval(proposal, proposal.title))
    again = asks.open_ask(store, asks.for_approval(proposal, proposal.title))
    assert again.id == first.id and len(asks.open_asks(store)) == 1
    opened = [e for e in store.events() if e.type is EventType.ASK_OPENED]
    assert len(opened) == 1 and opened[0].payload["options"] == ["approve", "reject", "later"]
    assert first.cli == "unbidden approve opp_1" and first.default == "approve"


def test_approving_from_an_ask_grants_the_same_approval_the_cli_does(store: Store, tmp_path: Path) -> None:
    from unbidden.guardian.approvals import find_valid
    from unbidden.publish.github import CAPABILITY

    proposal = _proposal(store)
    ask = asks.open_ask(store, asks.for_approval(proposal, proposal.title))
    done = asks.answer(SimpleNamespace(), store, ask.id, "approve", by="dave")
    assert done.status == "answered" and done.answer == "approve" and "24 h" in (done.outcome or "")
    assert find_valid(store, CAPABILITY, proposal.id) is not None
    answered = [e for e in store.events() if e.type is EventType.ASK_ANSWERED]
    assert answered and answered[0].actor == "person:dave"
    assert asks.open_asks(store) == []
    with pytest.raises(asks.AskError):
        asks.answer(SimpleNamespace(), store, ask.id, "approve")


def test_rejecting_takes_the_reason_typed_and_later_changes_nothing(store: Store) -> None:
    proposal = _proposal(store)
    ask = asks.open_ask(store, asks.for_approval(proposal, proposal.title))
    assert asks.answer(SimpleNamespace(), store, ask.id, "later").outcome == "nothing changed"
    ask = asks.open_ask(store, asks.for_approval(proposal, proposal.title))
    done = asks.answer(SimpleNamespace(), store, ask.id, "reject", value="not now")
    assert done.outcome == "rejected: not proposed again"
    opp = store.get("opportunities", "opp_1", Opportunity)
    assert opp is not None and opp.status is OpportunityStatus.DECLINED


def test_a_wrong_option_or_a_missing_value_is_refused(store: Store) -> None:
    block = record(store, classify("lab.experiment opp_1", "ProviderUnauthorized: meta 401: the key was refused",
                                   "lab.experiment runs again"))  # fmt: skip
    ask = asks.for_block(block)
    assert ask is not None and ask.kind == "credential"
    ask = asks.open_ask(store, ask)
    with pytest.raises(asks.AskError, match="not one of"):
        asks.answer(SimpleNamespace(), store, ask.id, "approve")
    with pytest.raises(asks.AskError, match="needs the value"):
        asks.answer(SimpleNamespace(), store, ask.id, "set")
    with pytest.raises(asks.AskError, match="command"):
        asks.answer(SimpleNamespace(), store, ask.id, "set", value="cd ~/repo")


def test_a_registry_block_becomes_an_ask_whose_answer_edits_the_mandate_and_releases_the_work(
    store: Store, tmp_path: Path, mandate: Mandate
) -> None:
    import yaml

    from unbidden.contracts.jobs import Job, JobStatus

    ws_dir = tmp_path / ".unbidden"
    ws_dir.mkdir()
    mandate_path = ws_dir / "mandate.yaml"
    mandate_path.write_text(yaml.safe_dump({"mandate": mandate.model_dump(mode="json")}, sort_keys=False))
    ws = SimpleNamespace(mandate_path=mandate_path)
    held = Job(type="lab.experiment", idempotency_key="lab:1", payload={"id": "opp_1"})
    store.enqueue(held)
    block = record(
        store,
        classify("lab.experiment opp_1", "packages come from deb.debian.org, which the mandate's package registries "
                 "do not list", "lab.experiment runs again"),
        held.id,
    )  # fmt: skip
    ask = asks.for_block(block)
    assert ask is not None and ask.kind == "registry" and "deb.debian.org" in ask.title
    ask = asks.open_ask(store, ask)
    done = asks.answer(ws, store, ask.id, "allow", by="dave")
    assert "deb.debian.org allowed" in (done.outcome or "")
    written = yaml.safe_load(mandate_path.read_text())["mandate"]["egress"]["package_registries"]
    assert "deb.debian.org" in written
    from unbidden.director.blocks import open_blocks

    assert open_blocks(store) == []
    queued = [j for j in store.jobs(status=JobStatus.QUEUED) if j.id == held.id]
    assert queued and queued[0].run_at <= queued[0].run_at  # requeued, due now


def test_a_hold_asks_and_releasing_it_from_the_ask_is_a_persons_release(store: Store) -> None:
    hold = place(store, "deploy 3 judged degraded")
    ask = asks.open_ask(store, asks.for_hold(hold))
    assert ask.default == "keep"
    done = asks.answer(SimpleNamespace(), store, ask.id, "release", value="looked at it", by="dave")
    assert "released" in (done.outcome or "") and active(store) == []


def test_reconcile_withdraws_what_was_settled_elsewhere(store: Store) -> None:
    proposal = _proposal(store)
    ask = asks.open_ask(store, asks.for_approval(proposal, proposal.title))
    assert asks.reconcile(store) == []
    proposal.status = ProposalStatus.PR_OPENED
    store.put("proposals", proposal, key=proposal.opportunity_id)
    gone = asks.reconcile(store)
    assert [a.id for a in gone] == [ask.id] and gone[0].withdrawn_why == "the proposal is pr_opened"
    hold = place(store, "x")
    ask = asks.open_ask(store, asks.for_hold(hold))
    from unbidden.operate.holds import release

    release(store, hold.id, "person:dave", "ok")
    assert [a.id for a in asks.reconcile(store)] == [ask.id]


def test_a_block_with_no_option_is_not_an_ask(store: Store) -> None:
    block = classify("lab.experiment opp_1", "Failed to build wheel", "lab.experiment runs again")
    assert asks.for_block(block) is None


def test_the_stage_of_an_opportunity_follows_its_records(store: Store) -> None:
    opp = Opportunity(source="t", category="perf", title="x", summary="s", dedup_key="k",
                      evidence=[EvidenceRef(kind="file", locator="x")])  # fmt: skip
    assert stage_of(opp, None) == (1, "found")
    opp.details = {"decision": {"chosen": "run_experiment"}}
    assert stage_of(opp, None) == (2, "decided")
    opp.details["attempts"] = 1
    assert stage_of(opp, None) == (3, "measured")
    opp.evidence_level = EvidenceLevel.FUNCTIONAL_VALIDATION
    assert stage_of(opp, None) == (4, "proven")
    store.put("opportunities", opp, key="k")
    proposal = Proposal(opportunity_id=opp.id, experiment_id="e", branch="b", base_sha="a" * 40, commit_sha="a" * 40,
                        title="t", body_md="b", evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION)  # fmt: skip
    store.put("proposals", proposal, key=opp.id)
    assert describe(store, opp)["text"] == f"5/{OF} proposed"
    proposal.status = ProposalStatus.MERGED
    store.put("proposals", proposal, key=opp.id)
    assert describe(store, opp)["stage"] == 6
    assert job_stage("lab.experiment") == ("measuring a candidate in the sandbox", "measured")
    assert job_stage("something.new") == ("something.new", "found")


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_the_loop_writes_job_events_with_the_stage_and_what_was_queued_next(store: Store) -> None:
    """One job run through the loop's bookkeeping: JOB_STARTED with the stage, JOB_FINISHED with the outcome, the
    seconds and the jobs it queued; the duration remembered for the next estimate."""
    from unbidden.contracts.jobs import Job
    from unbidden.daemon.loop import _job_event, remember_seconds, usual_seconds

    claimed = Job(type="lab.experiment", idempotency_key="lab:1", payload={"id": "opp_1"}, correlation_id="opp_1")
    assert usual_seconds(store, "lab.experiment") is None
    _job_event(store, EventType.JOB_STARTED, claimed, {"stage": "measured", "doing": "measuring", "usual_s": None})
    remember_seconds(store, "lab.experiment", 93.0)
    remember_seconds(store, "lab.experiment", 101.0)
    finished = {"outcome": "ok", "seconds": 101.0, "next": ["proposal.prepare"]}
    _job_event(store, EventType.JOB_FINISHED, claimed, finished)
    assert usual_seconds(store, "lab.experiment") == 101.0
    for _ in range(12):
        remember_seconds(store, "lab.experiment", 50.0)
    assert len(store.get_value("durations")["lab.experiment"]) == 10
    events = [e for e in store.events() if e.type in (EventType.JOB_STARTED, EventType.JOB_FINISHED)]
    assert [e.payload["subject"] for e in events] == ["opp_1", "opp_1"]
    assert events[1].payload["next"] == ["proposal.prepare"] and events[0].correlation_id == "opp_1"


def test_what_the_feed_makes_of_asks_jobs_and_notes() -> None:
    from unbidden.contracts.events import Event
    from unbidden.tui.feed import Coalescer, narrate

    opened = narrate(Event(type=EventType.ASK_OPENED, actor="director", entity_id="ask_1",
                           payload={"kind": "approval", "title": "Open the pull request for opp_1?",
                                    "options": ["approve"], "cli": "unbidden approve opp_1"}))  # fmt: skip
    assert opened is not None and opened.shade == "ask" and "/ask ask_1" in opened.text
    assert opened.detail == "from a terminal: unbidden approve opp_1"
    started = narrate(Event(type=EventType.JOB_STARTED, actor="daemon",
                            payload={"type": "lab.experiment", "doing": "measuring a candidate in the sandbox",
                                     "stage": "measured", "usual_s": 93.0}))  # fmt: skip
    assert started is not None and "Usually ~93 s" in started.text
    routine = narrate(Event(type=EventType.JOB_STARTED, actor="daemon", payload={"type": "github.poll"}))
    assert routine is None, "routine jobs are quiet unless verbose"
    parked = narrate(Event(type=EventType.JOB_FINISHED, actor="daemon",
                           payload={"type": "lab.experiment", "doing": "measuring", "outcome": "parked"}))  # fmt: skip
    assert parked is not None and parked.shade == "warn"
    good = narrate(Event(type=EventType.NOTE, actor="agent", payload={"text": "CI green on pull request #3 (url)"}))
    assert good is not None and good.shade == "good"
    pushed = narrate(Event(type=EventType.BRANCH_PUSHED, actor="publisher",
                           payload={"branch": "unbidden/x", "commit": "a" * 40}))  # fmt: skip
    assert pushed is not None and pushed.shade == "good" and "unbidden/x" in pushed.text
    folder = Coalescer()
    rejected = [Event(type=EventType.MODEL_CALLED, actor="brain", correlation_id="opp_1",
                      payload={"ok": False, "problem": "key rejected", "tier": "frontier"})
                for _ in range(3)]  # fmt: skip
    out: list[Any] = []
    for e in rejected:
        out.extend(folder.push(e))
    out.extend(folder.flush())
    assert len(out) == 1 and out[0].shade == "bad" and "3 model calls refused for the key" in out[0].text
