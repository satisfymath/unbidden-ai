"""Campaign 13, WS1: every stop is retried, asked or declared; the questions a person can answer exist, and their
answers do what the command would."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from unbidden.contracts.capability import CapabilityNeed, NeedStatus
from unbidden.contracts.common import utc_now
from unbidden.contracts.jobs import Job, JobStatus
from unbidden.daemon.cycle import idle
from unbidden.director import asks
from unbidden.director.blocks import attempts_for, classify, record
from unbidden.store import Store

pytestmark = pytest.mark.unit


def test_a_spend_cap_a_ledger_refusal_and_the_kill_switch_are_a_persons_blocks() -> None:
    cap = classify("lab.experiment opp_1", "SpendLimitReached: remote spend this month is US$2.00, at the US$2.00 cap",
                   "runs again")  # fmt: skip
    assert cap.kind == "pending_person" and "maximum_monthly_spend_usd above US$2.00" in cap.needs
    ledger = classify("x", "SpendRefused: refused: spend is split into envelopes (a) and this call names b", "again")
    assert ledger.kind == "pending_person" and "`unbidden spend`" in ledger.needs
    kill = classify("x", "KillSwitchEngaged: kill switch engaged", "again")
    assert kill.kind == "pending_person" and "unbidden resume" in kill.needs


def test_each_kind_has_its_retry_policy() -> None:
    unavailable = classify("x", "Connection refused", "again")
    assert attempts_for(unavailable, 3) == 6
    built = classify("x", "the dependencies still fail to build with build tools", "again")
    assert built.kind == "compatibility" and attempts_for(built, 3) == 0  # declared, not retried here
    unknown = classify("x", "ValueError: something nobody recognises", "again")
    assert unknown.kind == "compatibility" and attempts_for(unknown, 3) == 3  # may pass: the usual retries
    person = classify("x", "the key was refused", "again")
    assert attempts_for(person, 3) == 3


def test_blocks_become_the_questions_a_person_can_answer(store: Store) -> None:
    for error, kind in (
        ("remote spend this month is US$2.00, at the US$2.00 cap", "spend"),
        ("refused: spend is split into envelopes", "ledger"),
        ("kill switch engaged", "resume"),
        ("the service refused the credential: 401", "connection"),
    ):
        block = record(store, classify("lab.experiment opp_1", error, "lab.experiment runs again"))
        ask = asks.for_block(block)
        assert ask is not None and ask.kind == kind and ask.subject == block.id, (error, ask)


def test_resuming_from_the_question_releases_the_kill_switch_and_the_held_work(store: Store, tmp_path: Path) -> None:
    from unbidden.director.blocks import open_blocks
    from unbidden.guardian.killswitch import KillSwitch

    KillSwitch(tmp_path).engage("test")
    held = Job(type="lab.experiment", idempotency_key="k:1", payload={"id": "opp_1"})
    store.enqueue(held)
    block = record(store, classify("lab.experiment opp_1", "kill switch engaged", "runs again"), held.id)
    ask = asks.open_ask(store, asks.for_block(block))  # type: ignore[arg-type]
    done = asks.answer(SimpleNamespace(dir=tmp_path), store, ask.id, "resume", by="dave")
    assert "released" in (done.outcome or "") and not KillSwitch(tmp_path).engaged
    assert open_blocks(store) == []


def test_a_capability_waiting_for_approval_is_asked_and_approved_from_the_question(store: Store) -> None:
    from unbidden.forge.needs import COLLECTION, admit

    cap = _validated_log_adapter(store)
    need = CapabilityNeed(id="need_1", kind="log_adapter", source="compose:app", why="lines unparsed",
                          capability_id=cap)  # fmt: skip
    store.put(COLLECTION, need)
    admit(store, None, need)
    (ask,) = [a for a in asks.open_asks(store) if a.kind == "capability"]
    assert ask.subject == need.id
    done = asks.answer(SimpleNamespace(), store, ask.id, "approve", by="dave")
    assert f"approved {cap}" in (done.outcome or "")
    kept = store.get(COLLECTION, need.id, CapabilityNeed)
    assert kept is not None and kept.status is NeedStatus.IN_USE


def _validated_log_adapter(store: Store) -> str:
    from unbidden.forge.adapter import LogAdapter

    fields = LogAdapter.model_fields
    data: dict[str, object] = {"source": "compose:app", "status": "validated"}
    for name, field in fields.items():
        if field.is_required() and name not in data:
            data[name] = {"id": "cap_1", "version": 1, "code": "", "sha256": "x"}.get(name, "x")
    adapter = LogAdapter.model_validate(data)
    store.put("capabilities", adapter)
    return adapter.id


def test_adopting_deploy_steps_asks_for_the_drill_and_running_it_queues_the_job(
    store: Store, tmp_path: Path, mandate: object
) -> None:
    import yaml

    from unbidden.contracts.guardian import Mandate

    assert isinstance(mandate, Mandate)
    path = tmp_path / "mandate.yaml"
    path.write_text(yaml.safe_dump({"mandate": mandate.model_dump(mode="json")}, sort_keys=False))
    ws = SimpleNamespace(mandate_path=path, dir=tmp_path)
    action = SimpleNamespace(operation="docker compose up -d", reason="found in the CI", id="act_1")
    steps = asks.open_ask(store, asks.for_deploy_steps(action))
    asks.answer(ws, store, steps.id, "adopt", by="dave")
    (drill,) = [a for a in asks.open_asks(store) if a.kind == "drill"]
    asks.answer(ws, store, drill.id, "run", by="dave")
    assert [j.type for j in store.jobs(status=JobStatus.QUEUED)] == ["ops.drill"]
    store.set_value("rollback_drill", {"passed": True})
    assert asks.reconcile(store) == []  # answered already; nothing open to withdraw


def test_idle_means_only_housekeeping_is_due(store: Store) -> None:
    assert idle(store)
    store.enqueue(Job(type="world.refresh", idempotency_key="w:1"))
    assert idle(store)
    later = Job(type="lab.experiment", idempotency_key="l:1")
    later.run_at = utc_now() + timedelta(hours=1)
    store.enqueue(later)
    assert idle(store)  # not due yet
    store.enqueue(Job(type="lab.experiment", idempotency_key="l:2"))
    assert not idle(store)


def test_a_lab_result_not_yet_swept_is_not_idle(store: Store) -> None:
    """rich, final pass 0.18.9: two green pull requests went stale on a merge and were measured again; the agent
    read as idle before the director's next sweep (up to a minute away) proposed them again, and the cycle ended."""
    from unbidden.daemon.cycle import SWEEP_DUE

    assert idle(store)
    store.set_value(SWEEP_DUE, True)  # a lab experiment finished, or a stale proposal reopened its opportunity
    assert not idle(store)
    store.set_value(SWEEP_DUE, False)  # the director swept
    assert idle(store)
