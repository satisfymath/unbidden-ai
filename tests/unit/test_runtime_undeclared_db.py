"""A PostgreSQL started from a compose file the map does not read is still read, read-only (stage 8: LNbits's
tables were never read, so no check had anything to look at). Docker is faked here."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import unbidden.world.runtime as rt
from unbidden.contracts.world import WorldModel

pytestmark = pytest.mark.unit


def test_an_undeclared_postgres_is_read_with_its_own_user_and_database(monkeypatch: Any) -> None:
    rows = [{"Service": "db", "Name": "lab-db-1", "Image": "postgres:16", "State": "running", "Publishers": []}]
    monkeypatch.setattr(rt, "running_containers", lambda repo: rows)
    monkeypatch.setattr(rt, "load_compose", lambda repo, rev, files: None)
    inspected = [{"Config": {"Env": ["POSTGRES_USER=pg", "POSTGRES_DB=shop", "POSTGRES_PASSWORD=not-read"]}}]
    monkeypatch.setattr("unbidden.operate.ledger._docker_json", lambda *args: inspected)
    called: list[tuple[str, str, str, str]] = []

    def postgres(world: WorldModel, service: str, container: str, user: str, default: str) -> bool:
        called.append((service, container, user, default))
        return True

    monkeypatch.setattr(rt, "_postgres", postgres)
    ran = rt.discover_runtime(Path("."), WorldModel(rev="HEAD"))
    assert called == [("db", "lab-db-1", "pg", "shop")] and rt.POSTGRES_READONLY.ref in ran
    assert rt.container_env("lab-db-1", ("POSTGRES_USER",)) == {"POSTGRES_USER": "pg"}  # the password is not read
