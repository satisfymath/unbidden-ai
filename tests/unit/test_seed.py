"""The lab's seeder (stage 10): data written by fixed code from the engine's catalog, the same in every session."""

from __future__ import annotations

import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest

from unbidden.lab.seed import data_check, plan_seed, statements_using
from unbidden.lab.served import psql_for

pytestmark = [pytest.mark.docker]
SCHEMA = """
CREATE TYPE kind AS ENUM ('pla', 'petg');
CREATE TABLE vendor (id serial PRIMARY KEY, name text NOT NULL UNIQUE, registered timestamptz NOT NULL DEFAULT now());
CREATE TABLE filament (id serial PRIMARY KEY, vendor_id int NOT NULL REFERENCES vendor(id), material kind NOT NULL,
                       density numeric NOT NULL, extra jsonb NOT NULL, code varchar(4) NOT NULL);
CREATE TABLE spool (id serial PRIMARY KEY, filament_id int NOT NULL REFERENCES filament(id), used float8 NOT NULL,
                    archived boolean, registered timestamptz NOT NULL DEFAULT now());
"""


def _available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
    except FileNotFoundError:
        return False


@pytest.fixture
def pg() -> Iterator[str]:
    if not _available():
        pytest.skip("no Docker daemon")
    name = f"t-seed-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=x", "postgres:16",
                    "postgres", "-c", "shared_preload_libraries=pg_stat_statements"], check=True,
                   capture_output=True)  # fmt: skip
    try:
        for _ in range(120):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-q"], check=False).returncode == 0:
                break
            time.sleep(0.5)
        time.sleep(1)
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def test_the_measured_table_is_seeded_over_its_references_and_twice_the_same(pg: str) -> None:
    psql = psql_for(pg, "postgres", "postgres")
    psql(SCHEMA)
    plan = plan_seed(psql, "spool", "filament_id", 2000, 100, others=10)
    assert plan.parent == "filament" and plan.counts == {"vendor": 10, "filament": 100, "spool": 2000}
    for statement in plan.statements:
        psql(statement)
    ok, data = data_check(psql, plan)
    assert ok, data
    first = psql("SELECT md5(string_agg(registered::text || used::text, ',' ORDER BY id)) FROM spool")
    psql("TRUNCATE spool, filament, vendor RESTART IDENTITY CASCADE;")
    for statement in plan_seed(psql, "spool", "filament_id", 2000, 100, others=10).statements:
        psql(statement)
    assert psql("SELECT md5(string_agg(registered::text || used::text, ',' ORDER BY id)) FROM spool") == first


def test_the_engine_says_which_statements_read_the_relation(pg: str) -> None:
    psql = psql_for(pg, "postgres", "postgres")
    psql(SCHEMA)
    for statement in plan_seed(psql, "spool", "filament_id", 500, 50, others=5).statements:
        psql(statement)
    psql("CREATE EXTENSION pg_stat_statements; SELECT pg_stat_statements_reset();")
    for i in range(1, 24):
        psql(f"SELECT * FROM spool WHERE filament_id = {i};")
        psql(f"SELECT * FROM spool WHERE id = {i};")
    used = statements_using(psql, "spool", "filament_id", 20)
    assert len(used) == 1 and "filament_id" in str(used[0]["query"]) and int(used[0]["calls"]) >= 23  # type: ignore[call-overload]


def test_the_table_an_endpoint_acts_on_is_seeded_too(pg: str) -> None:
    """Stage 10, Spoolman: `PUT /spool/{id}/measure` joins `filament` by `vendor_id`; with only `filament` and `vendor`
    seeded, every call answered 404 and no request a model chose could be valid."""
    psql = psql_for(pg, "postgres", "postgres")
    psql(SCHEMA)
    plan = plan_seed(psql, "filament", "vendor_id", 1000, 20, others=5, paths=["/api/v1/spool/{spool_id}/measure"],
                     context_rows=300)  # fmt: skip
    assert plan.counts == {"vendor": 20, "filament": 1000, "spool": 300}
    for statement in plan.statements:
        psql(statement)
    assert psql("SELECT count(*), count(filament_id) FROM spool").strip() == "300\t300"  # each references a filament
