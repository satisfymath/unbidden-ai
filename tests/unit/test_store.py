from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.jobs import Job, JobStatus
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.store import Store

pytestmark = pytest.mark.unit


def opportunity(key: str = "k") -> Opportunity:
    return Opportunity(
        source="tsc",
        category="types",
        title="t",
        summary="s",
        dedup_key=key,
        evidence=[EvidenceRef(kind="file", locator="a.ts")],
    )


def test_events_are_append_only(store: Store) -> None:
    stored = store.append_event(Event(type=EventType.HEAD_MOVED, actor="observer", payload={"sha": "x"}))
    assert stored.seq == 1
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM events")  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE events SET actor = 'x'")  # pyright: ignore[reportPrivateUsage]


def test_docs_round_trip_and_filter_by_status(store: Store) -> None:
    opp = opportunity()
    store.put("opportunities", opp, key=opp.dedup_key)
    opp.status = OpportunityStatus.DECLINED
    store.put("opportunities", opp)
    assert store.get_by_key("opportunities", "k", Opportunity) == opp
    assert store.list("opportunities", Opportunity, status="declined") == [opp]
    assert store.list("opportunities", Opportunity, status="open") == []


def test_jobs_are_idempotent_claimed_once_and_retried(store: Store) -> None:
    assert store.enqueue(Job(type="analyzer.run", idempotency_key="tsc@1"))
    assert not store.enqueue(Job(type="analyzer.run", idempotency_key="tsc@1"))
    job = store.claim()
    assert job is not None and job.status is JobStatus.RUNNING
    assert store.claim() is None
    retried = store.finish(job, error="boom", retry_in=timedelta(0))
    assert retried.status is JobStatus.QUEUED
    again = store.claim()
    assert again is not None and again.attempts == 2


def test_running_jobs_are_requeued_after_a_crash(tmp_path: Path) -> None:
    first = Store(tmp_path / "state.db")
    first.enqueue(Job(type="lab.experiment", idempotency_key="e1"))
    assert first.claim() is not None
    first.close()
    second = Store(tmp_path / "state.db")
    assert second.requeue_running() == 1
    assert second.claim() is not None


def test_higher_priority_runs_first(store: Store) -> None:
    store.enqueue(Job(type="lab.experiment", idempotency_key="lab", priority=50))
    store.enqueue(Job(type="github.poll", idempotency_key="gh", priority=10))
    job = store.claim()
    assert job is not None and job.type == "github.poll"
