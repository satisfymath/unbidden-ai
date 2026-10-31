"""The read-only reader, the historical loader, a live workspace, and the actions."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from tests.web.conftest import Client, make_server
from unbidden.contracts.events import Event, EventType
from unbidden.store import Store
from unbidden.store.sqlite import SCHEMA_VERSION
from unbidden.web.reader import ReaderError, ReadOnlyStore
from unbidden.web.sources import historical, live

pytestmark = pytest.mark.unit
RECORDS = Path(__file__).resolve().parents[2] / "docs" / "bench"


def test_the_reader_opens_without_migrating_and_refuses_writes(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    writer = Store(path)
    writer.append_event(Event(type=EventType.HEAD_MOVED, actor="t", payload={"to": "abc"}))
    writer.set_value("head", "abc")
    before = path.stat().st_mtime_ns
    reader = ReadOnlyStore(path)
    assert reader.schema_version == SCHEMA_VERSION and reader.last_seq() == 1 and reader.get_value("head") == "abc"
    with pytest.raises(sqlite3.OperationalError):
        reader.set_value("head", "evil")
    with pytest.raises(sqlite3.OperationalError):
        reader.append_event(Event(type=EventType.HEAD_MOVED, actor="t"))
    assert path.stat().st_mtime_ns == before
    # The writer goes on; the reader sees it (WAL honoured, no copy made).
    writer.append_event(Event(type=EventType.ANALYZER_RAN, actor="t"))
    assert reader.last_seq() == 2
    assert reader.event_types() == {"repo.head_moved": 1, "analyzer.ran": 1}


def test_the_reader_refuses_a_newer_schema_and_a_foreign_file(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    Store(path).close()
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version = 99")
    with pytest.raises(ReaderError, match="schema 99"):
        ReadOnlyStore(path)
    (tmp_path / "text.db").write_text("not a database")
    with pytest.raises(ReaderError):
        ReadOnlyStore(tmp_path / "text.db")
    with pytest.raises(ReaderError, match="does not exist"):
        ReadOnlyStore(tmp_path / "none.db")


@pytest.mark.skipif(not (RECORDS / "stage9-demo" / "DEMO-B-1" / "activity.json").exists(), reason="record not here")
def test_a_published_run_is_served_as_history_and_never_as_current(tmp_path: Path) -> None:
    src = historical(RECORDS / "stage9-demo" / "DEMO-B-1")
    assert src.mode == "historical" and not src.streams and src.observed_at is not None
    s = src.summary()
    assert s["freshness"] == "historical" and s["activity"]["discovered"]["total"] == 6
    assert len(s["activity"]["proven"]) == 2 and s["workspace"]["head"].startswith("029eb77")
    assert "experiments" in s["capabilities"] and "connections" in s["capabilities"]
    assert src.timeline and src.timeline[0]["kind"] == "cycle" and any("map of" in t["text"] for t in src.timeline)
    srv = make_server([src], tmp_path)
    try:
        c = Client(srv, src.id)
        opps = c.get("/opportunities").json()
        assert opps["total"] == 2 and opps["items"][0]["evidence_level"] == 4
        assert c.get("/timeline", params={"limit": 5}).json()["total"] == len(src.timeline)
        got = c.sse("/events/stream", method="GET")
        assert got[-1][0] == "closed" and "historical" in got[-1][2]["reason"]
    finally:
        srv.stop()


@pytest.mark.skipif(
    not (RECORDS / "stage10-revalidation" / "v4-f9fe965" / "fst-f9fe965.json").exists(), reason="record not here"
)
def test_a_revalidation_record_gives_real_latency_samples(tmp_path: Path) -> None:
    src = historical(RECORDS / "stage10-revalidation" / "v4-f9fe965" / "fst-f9fe965.json")
    srv = make_server([src], tmp_path)
    try:
        c = Client(srv, src.id)
        s = c.get("/summary").json()
        assert s["freshness"] == "historical" and s["counts"]["experiments"] == 1
        exp_id = c.get("/opportunities").json()["items"][0]["experiment_id"]
        rows = c.post(
            "/data",
            {
                "dataset": "experiment.samples",
                "params": {"experiment_id": exp_id},
                "transform": {"group_by": "arm", "aggregate": {"field": "ms", "fn": "count"}},
            },
        ).json()["rows"]
        assert {r["arm"]: r["count_ms"] for r in rows} == {"before": 80, "after": 80}
        sessions = c.post("/data", {"dataset": "experiment.sessions", "params": {"experiment_id": exp_id}}).json()
        assert len(sessions["rows"]) == 8 and sessions["provenance"]["freshness"] == "historical"
        tests = c.post("/data", {"dataset": "experiment.tests", "params": {"experiment_id": exp_id}}).json()
        assert [r["collected"] for r in tests["rows"]] == [58] * 6
    finally:
        srv.stop()


@pytest.mark.skipif(not (RECORDS / "mealie-l5" / "rounds-foods-empty.json").exists(), reason="record not here")
def test_an_l5_record_gives_probe_rounds_per_deploy(tmp_path: Path) -> None:
    src = historical(RECORDS / "mealie-l5")
    rows = (
        __import__("unbidden.web.datasets", fromlist=["resolve"])
        .resolve(src, __import__("unbidden.web.contracts", fromlist=["DataRef"]).DataRef(dataset="probe.rounds"))
        .rows
    )
    assert rows and {r["deploy"] for r in rows} >= {0} and all(r["p50_ms"] > 0 for r in rows)


def test_a_live_workspace_streams_new_events_without_duplicates(tmp_path: Path) -> None:
    from unbidden.web.devseed import seed

    repo = tmp_path / "sample"
    store = seed(repo)
    src = live(repo)
    assert src.mode == "live" and src.streams and src.notes and "seed" in src.notes[0]
    assert src.summary()["activity"]["discovered"]["total"] == 6
    srv = make_server([src], tmp_path / "web")
    try:
        c = Client(srv, src.id)
        last = c.get("/events").json()["last_seq"]

        def write() -> None:
            time.sleep(0.5)
            for i in range(3):
                store.append_event(Event(type=EventType.LOG_SIGNAL, actor="t", payload={"i": i}))
                time.sleep(0.2)

        threading.Thread(target=write).start()
        got = []
        with c.http.stream("GET", c.ws("/events/stream"), params={"after": last}, timeout=10) as r:
            for line in r.iter_lines():
                if line.startswith("id:"):
                    got.append(int(line[3:]))
                if len(got) == 3:
                    break
        assert got == [last + 1, last + 2, last + 3]
        again = c.sse("/events/stream", method="GET", headers={"Last-Event-ID": str(last + 2)}, limit_events=2)
        assert [g[2]["seq"] for g in again if g[0] == "engine"] == [last + 3]
        # Actions on a live workspace: the kill switch is the engine's own file; approvals are handed to the CLI.
        r = c.post("/actions", {"operation": "kill", "reason": "test", "idempotency_key": "k1"}).json()
        assert r["effect"] == "done" and (repo / ".unbidden" / "KILL").read_text().strip() == "test"
        assert (
            c.post("/actions", {"operation": "kill", "reason": "test", "idempotency_key": "k1"}).json()["effect"]
            == "already"
        )
        assert c.get("/summary").json()["connection"]["kill_switch"] is True
        assert c.post("/actions", {"operation": "resume", "idempotency_key": "k2"}).json()["effect"] == "done"
        assert not (repo / ".unbidden" / "KILL").exists()
        r = c.post(
            "/actions", {"operation": "approve", "subject": "opp_demo000000000001", "idempotency_key": "k3"}
        ).json()
        assert r["effect"] == "not_supported_here" and r["cli"] == "unbidden approve opp_demo000000000001"
        r = c.post(
            "/actions", {"operation": "evaluate", "capability": "github.open_pull_request", "idempotency_key": "k4"}
        ).json()
        assert r["verdict"]["decision"] == "require_approval"
        r = c.post("/actions", {"operation": "evaluate", "capability": "deploy.run", "idempotency_key": "k5"}).json()
        assert r["verdict"]["decision"] == "deny"
        assert c.post("/actions", {"operation": "nuke", "idempotency_key": "k6"}).status_code == 422
        assert (
            c.post(
                "/actions",
                {"operation": "kill", "reason": "x", "expected_revision": "deadbeef", "idempotency_key": "k7"},
            ).json()["effect"]
            == "refused"
        )
    finally:
        srv.stop()
        store.close()


def test_the_demo_source_has_no_kill_switch_to_lie_about(tmp_path: Path) -> None:
    from unbidden.web.sources import demo

    src = demo()
    src.streams = False
    srv = make_server([src], tmp_path)
    try:
        r = Client(srv, src.id).post("/actions", {"operation": "kill", "idempotency_key": "k"}).json()
        assert r["effect"] == "not_supported_here"
    finally:
        srv.stop()
