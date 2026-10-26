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
