from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.opportunity import Opportunity
from unbidden.contracts.world import Relation, Resource, WorldModel
from unbidden.lab.perf import alembic_head
from unbidden.store import Store
from unbidden.world.checks import run_checks, unindexed_foreign_keys

pytestmark = pytest.mark.unit
REF = [EvidenceRef(kind="config", locator="psql")]


def world(indexes: list[dict[str, str]], read: bool = True) -> WorldModel:
    w = WorldModel(rev="a" * 40)
    for name, idx in (("orders", indexes), ("customers", [{"name": "customers_pkey", "columns": "id"}])):
        w.add(
            Resource(
                id=f"table:{name}",
                kind="table",
                name=name,
                attributes={"indexes": idx, "rows_estimate": 9},
                status=EpistemicStatus.OBSERVED,
                confidence=1.0,
                evidence=REF,
            )
        )
    w.add(
        Resource(
            id="endpoint:GET /orders",
            kind="endpoint",
            name="GET /orders",
            attributes={"file": "api/orders.py", "line": 3},
            status=EpistemicStatus.OBSERVED,
            confidence=1.0,
            evidence=REF,
        )
    )
    w.relate(
        Relation(
            src="table:orders",
            dst="table:customers",
            predicate="references",
            status=EpistemicStatus.OBSERVED,
            confidence=1.0,
            evidence=[EvidenceRef(kind="config", locator="psql", note="orders.customer_id -> customers")],
        )
    )
    if read:
        w.relate(
            Relation(
                src="endpoint:GET /orders",
                dst="table:orders",
                predicate="reads",
                status=EpistemicStatus.INFERRED,
                confidence=0.6,
                evidence=REF,
            )
        )
    return w


def test_unindexed_fk_read_by_an_endpoint_is_an_opportunity() -> None:
    (opp,) = unindexed_foreign_keys(world([{"name": "orders_pkey", "columns": "id"}]))
    assert opp.details["table"] == "orders" and opp.details["column"] == "customer_id"
    assert opp.details["endpoints"] == ["GET /orders"] and opp.category == "performance"


def test_an_index_leading_with_the_column_or_no_reader_means_nothing_to_do() -> None:
    assert unindexed_foreign_keys(world([{"name": "ix", "columns": "customer_id, created_at"}])) == []
    assert unindexed_foreign_keys(world([], read=False)) == []


def test_checks_open_once(store: Store) -> None:
    w = world([])
    assert len(run_checks(w, store)) == 1
    assert run_checks(w, store) == []
    assert len(store.list("opportunities", Opportunity)) == 1


def test_alembic_head_follows_down_revisions(tmp_path: Path) -> None:
    versions = tmp_path / "app" / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "a.py").write_text('revision = "aaa"\ndown_revision = None\n')
    (versions / "b.py").write_text('revision = "bbb"\ndown_revision = "aaa"\n')
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    assert alembic_head(tmp_path, "HEAD") == ("app/alembic/versions", "bbb", "app/alembic/versions/b.py")


def test_only_scans_since_the_previous_map_count_as_full_table_scans() -> None:
    from unbidden.contracts.common import EpistemicStatus, EvidenceRef
    from unbidden.contracts.world import Relation, Resource, WorldModel
    from unbidden.world.checks import full_table_scans

    w = WorldModel(rev="r")
    ev = [EvidenceRef(kind="config", locator="x")]
    scans = {"seq": 300, "seq_rows": 36_000_000, "idx": 60_000}
    w.add(Resource(id="table:item", kind="table", name="item", attributes={"rows_estimate": 120_000, "scans": scans},
                   status=EpistemicStatus.OBSERVED, confidence=1, evidence=ev))  # fmt: skip
    w.add(Resource(id="endpoint:GET /items/", kind="endpoint", name="GET /items/",
                   status=EpistemicStatus.OBSERVED, confidence=1, evidence=ev))  # fmt: skip
    w.relate(Relation(src="endpoint:GET /items/", dst="table:item", predicate="reads",
                      status=EpistemicStatus.INFERRED, confidence=0.6, evidence=ev))  # fmt: skip
    history = {"table:item": {"seq": 264, "seq_rows": 33_600_000, "idx": 52_000}}
    found = full_table_scans(w, history, 600)
    assert len(found) == 1 and found[0].details["scans"] == 36 and found[0].details["table"] == "item"
    assert full_table_scans(w, {"table:item": scans}, 600) == []  # nothing new since: history, not a problem


def _sized(rows: int) -> WorldModel:
    w = world([])
    w.resources["table:orders"].attributes["rows_estimate"] = rows
    return w


def test_a_declined_check_reopens_when_the_data_it_was_judged_on_has_doubled(store: Store) -> None:
    # D1: data growth between commits, seen by the map refresh, reaches the opportunity again.
    from unbidden.contracts.opportunity import OpportunityStatus

    (opp,) = run_checks(_sized(10_000), store)
    opp.status = OpportunityStatus.DECLINED
    store.put("opportunities", opp)
    assert run_checks(_sized(15_000), store) == []  # grew, not enough to change a judgement
    assert run_checks(_sized(18_000), store) == []  # measured from the decline (10,000), not from the last map
    (reopened,) = run_checks(_sized(30_000), store)
    assert reopened.status is OpportunityStatus.OPEN and reopened.details["rows"] == 30_000
    (event,) = [e for e in store.events() if e.payload.get("reopened")]
    assert "grew from ~10000 to ~30000" in event.payload["reason"]
    assert run_checks(_sized(10_000), store) == []  # open now: nothing to reopen


def test_a_resolved_check_that_fires_again_is_open_again(store: Store) -> None:
    from unbidden.contracts.opportunity import OpportunityStatus

    (opp,) = run_checks(world([]), store)
    opp.status = OpportunityStatus.CLOSED
    store.put("opportunities", opp)
    (reopened,) = run_checks(world([]), store)
    assert reopened.status is OpportunityStatus.OPEN


def test_the_map_is_refreshed_between_commits_without_a_model(store: Store, mandate: object, tmp_path: Path) -> None:
    import asyncio
    from types import SimpleNamespace

    from unbidden.daemon import cycle as cycle_module
    from unbidden.world import discover as discover_module

    seen: list[object] = []

    async def fake(repo: Path, rev: str, s: Store, m: object, brain: object) -> WorldModel:
        seen.append(brain)
        return world([])

    store.set_value("head", "a" * 40)
    runtime = SimpleNamespace(store=store, workspace=SimpleNamespace(repo=tmp_path, mandate=lambda: mandate))
    cycle = cycle_module.Cycle(runtime, log=lambda _: None)  # type: ignore[arg-type]
    original = discover_module.discover
    discover_module.discover = fake  # type: ignore[assignment]
    try:
        asyncio.run(cycle.world_refresh(cycle_module.job("world.refresh", "1")))
    finally:
        discover_module.discover = original
    assert seen == [None]
