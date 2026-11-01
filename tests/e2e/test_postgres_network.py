"""The network PostgreSQL connector against the lab's real database (`bench.ecosystem.lab up`), not a mock."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from unbidden.connect.base import Unavailable
from unbidden.connect.postgres import PostgresConnector, QueryRefused, catalog, query
from unbidden.connect.registry import by_grant, survey
from unbidden.contracts.connection import ConnectionState
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.guardian import credentials
from unbidden.store import Store

LAB = Path.home() / "unbidden-lab"
up = subprocess.run(["docker", "ps", "-q", "--filter", "name=^unbidden-lab-pg$"], capture_output=True, text=True)
pytestmark = [pytest.mark.slow, pytest.mark.skipif(not up.stdout.strip(), reason="the ecosystem lab is not up")]


def lab_secrets() -> dict[str, str]:
    return dict(line.split("=", 1) for line in (LAB / "secrets.env").read_text().splitlines() if "=" in line)


def grant(role: str, ref: str, permissions: list[str] | None = None) -> ConnectionGrant:
    return ConnectionGrant(
        id=f"shop-{role}",
        kind="postgres",
        location="127.0.0.1:55432/shop",
        username=role,
        credential_ref=ref,
        tls="prefer",
        permissions=permissions or ["read"],
    )


@pytest.fixture
def held() -> Iterator[None]:
    fresh = credentials.reset()
    values = lab_secrets()
    fresh._values["SHOP_READER_PW"] = values["SHOP_READER_PW"]  # pyright: ignore[reportPrivateUsage]
    fresh._values["SHOP_OPS_PW"] = values["SHOP_OPS_PW"]  # pyright: ignore[reportPrivateUsage]
    fresh._values["WRONG_PW"] = "not-the-password-at-all"  # pyright: ignore[reportPrivateUsage]
    yield
    credentials.reset()


def lab(*action: str) -> None:
    subprocess.run([sys.executable, "-m", "bench.ecosystem.lab", *action], check=True, cwd=Path(__file__).parents[2])


def test_least_privilege_is_observed_and_reads_are_bounded(
    held: None, store: Store, mandate: Mandate, tmp_path: Path
) -> None:
    mandate.connections = [grant("shop_reader", "SHOP_READER_PW")]
    survey(tmp_path, store, mandate, None, {"postgres": PostgresConnector()})
    conn = by_grant(store, "shop-shop_reader")
    assert conn is not None and conn.state is ConnectionState.CONNECTED and conn.effective == ["read"]
    assert {t["table"] for t in catalog(conn, mandate)} == {"products", "orders"}
    rows = query(conn, mandate, "SELECT sku, sum(quantity) AS units FROM orders GROUP BY sku", limit=5)
    assert len(rows) == 5 and set(rows[0]) == {"sku", "units"}
    with pytest.raises(QueryRefused):
        query(conn, mandate, "DELETE FROM orders")
    with pytest.raises(QueryRefused):
        query(conn, mandate, "SELECT 1; DROP TABLE orders")


def test_a_role_holding_more_than_granted_is_reported_never_granted(
    held: None, store: Store, mandate: Mandate, tmp_path: Path
) -> None:
    mandate.connections = [grant("shop_ops", "SHOP_OPS_PW")]
    survey(tmp_path, store, mandate, None, {"postgres": PostgresConnector()})
    conn = by_grant(store, "shop-shop_ops")
    assert conn is not None and conn.state is ConnectionState.CONNECTED
    assert "write (held by the role, not granted)" in conn.effective and not conn.can("write")
    assert "can also change" in conn.check_detail


def test_a_wrong_password_needs_authorization_and_a_revoked_one_stops_its_users(
    held: None, store: Store, mandate: Mandate, tmp_path: Path
) -> None:
    mandate.connections = [grant("shop_reader", "WRONG_PW")]
    survey(tmp_path, store, mandate, None, {"postgres": PostgresConnector()})
    wrong = by_grant(store, "shop-shop_reader")
    assert (
        wrong is not None
        and wrong.state is ConnectionState.NEEDS_AUTHORIZATION
        and "WRONG_PW" in (wrong.next_step or "")
    )
    mandate.connections = [grant("shop_reader", "SHOP_READER_PW")]
    survey(tmp_path, store, mandate, None, {"postgres": PostgresConnector()})
    lab("revoke-reader")
    try:
        survey(tmp_path, store, mandate, None, {"postgres": PostgresConnector()})
        revoked = by_grant(store, "shop-shop_reader")
        assert revoked is not None and revoked.state is ConnectionState.REVOKED
        with pytest.raises(Unavailable, match="revoked"):
            query(revoked, mandate, "SELECT 1")
    finally:
        lab("restore-reader")
    survey(tmp_path, store, mandate, None, {"postgres": PostgresConnector()})
    restored = by_grant(store, "shop-shop_reader")
    assert restored is not None and restored.state is ConnectionState.CONNECTED
    assert [h["state"] for h in restored.history][-3:] == ["connected", "revoked", "connected"]
