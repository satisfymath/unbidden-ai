"""Connections: found is not connected, granted is not allowed, and what stops working stops being used."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from unbidden.connect.base import Unavailable, require
from unbidden.connect.github import GitHubConnector
from unbidden.connect.http_api import HttpApiConnector
from unbidden.connect.registry import config_hints, survey
from unbidden.contracts.connection import ConnectionState
from unbidden.contracts.guardian import Autonomy, ConnectionGrant, Mandate
from unbidden.guardian import credentials
from unbidden.store import Store

pytestmark = pytest.mark.unit

COMPOSE = """services:
  app:
    build: .
    environment:
      DATABASE_URL: postgresql://shop_reader@host.docker.internal:55432/shop
      STOCKROOM_URL: http://host.docker.internal:18081
      CACHE_URL: redis://cache:6379
      INTERNAL: http://cache:8080
  cache:
    image: redis:7
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docker-compose.yml").write_text(COMPOSE)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    subprocess.run([*git, "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    return tmp_path


def github(status: int, permissions: dict[str, bool] | None = None) -> GitHubConnector:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"permissions": permissions or {}})

    return GitHubConnector(httpx.MockTransport(handle))


def test_configuration_outside_the_compose_project_is_found_never_connected(
    repo: Path, store: Store, mandate: Mandate
) -> None:
    mandate.egress.github.repository = None
    hints = config_hints(repo)
    assert {(k, loc) for k, loc, _ in hints} == {
        ("postgres", "127.0.0.1:55432/shop"),
        ("http_api", "http://127.0.0.1:18081"),
    }
    found = {c.id: c for c in survey(repo, store, mandate, None, {})}
    pg = found["postgres:127.0.0.1:55432/shop"]
    assert pg.state is ConnectionState.DISCOVERED and not pg.can("read") and "grant" in (pg.next_step or "")
    assert found["github:acme/shop"].state is ConnectionState.DISCOVERED  # the remote alone authorizes nothing
    mandate.egress.github.repository = "acme/shop"
    found = {c.id: c for c in survey(repo, store, mandate, None, {})}
    assert found["github:acme/shop"].state is ConnectionState.NEEDS_AUTHORIZATION  # named, but no grant checked yet


@pytest.mark.parametrize(
    ("status", "permissions", "state", "write"),
    [
        (200, {"pull": True, "push": True}, ConnectionState.CONNECTED, True),
        (200, {"pull": True, "push": False}, ConnectionState.CONNECTED, False),
        (401, None, ConnectionState.REVOKED, False),
        (404, None, ConnectionState.NEEDS_AUTHORIZATION, False),
    ],
)
def test_github_reports_what_the_token_really_can(
    status: int,
    permissions: dict[str, bool] | None,
    state: ConnectionState,
    write: bool,
    repo: Path,
    store: Store,
    mandate: Mandate,
) -> None:
    credentials.reset()
    credentials.broker()._values["SHOP_GH"] = "ghp_" + "x" * 20  # pyright: ignore[reportPrivateUsage]
    mandate.connections = [ConnectionGrant(id="gh", kind="github", location="acme/shop", credential_ref="SHOP_GH")]
    (conn,) = [c for c in survey(repo, store, mandate, None, {"github": github(status, permissions)}) if c.grant]
    assert conn.state is state and conn.can("write") is write
    credentials.reset()


def test_a_missing_credential_is_named_and_never_asked_for_in_conversation(
    repo: Path, store: Store, mandate: Mandate
) -> None:
    credentials.reset()
    mandate.connections = [ConnectionGrant(id="gh", kind="github", location="acme/shop", credential_ref="SHOP_GH")]
    (conn,) = [c for c in survey(repo, store, mandate, None, {"github": github(200)}) if c.grant]
    assert conn.state is ConnectionState.NEEDS_AUTHORIZATION and "SHOP_GH" in (conn.next_step or "")


def test_an_api_with_documentation_but_no_integration_needs_a_capability(
    repo: Path, store: Store, mandate: Mandate
) -> None:
    document = {
        "openapi": "3.0.3",
        "info": {"title": "Stockroom", "version": "1"},
        "paths": {"/v1/skus": {"get": {}}},
        "components": {"securitySchemes": {"key": {"type": "apiKey", "name": "X-Api-Key", "in": "header"}}},
    }
    api = HttpApiConnector(httpx.MockTransport(lambda r: httpx.Response(200, content=json.dumps(document))))
    mandate.connections = [
        ConnectionGrant(
            id="stock",
            kind="http_api",
            location="http://127.0.0.1:18081",
            docs="http://127.0.0.1:18081/openapi.json",
            credential_ref="STOCK_KEY",
        )
    ]
    found = {c.id: c for c in survey(repo, store, mandate, None, {"http_api": api})}
    conn = found["http_api:http://127.0.0.1:18081"]
    assert conn.state is ConnectionState.NEEDS_CAPABILITY and "X-Api-Key" in conn.check_detail
    assert "config" in " ".join(conn.discovered_by) or "docker-compose" in " ".join(conn.discovered_by)


def test_a_withdrawn_grant_is_revoked_and_a_vanished_resource_is_gone(
    repo: Path, store: Store, mandate: Mandate
) -> None:
    credentials.reset()
    credentials.broker()._values["SHOP_GH"] = "ghp_" + "x" * 20  # pyright: ignore[reportPrivateUsage]
    mandate.connections = [ConnectionGrant(id="gh", kind="github", location="acme/other", credential_ref="SHOP_GH")]
    survey(repo, store, mandate, None, {"github": github(200, {"pull": True})})
    mandate.connections = []
    (repo / "docker-compose.yml").write_text("services:\n  app:\n    build: .\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "commit", "-qam", "drop the database"], check=True)
    found = {c.id: c for c in survey(repo, store, mandate, None, {})}
    assert found["github:acme/other"].state is ConnectionState.REVOKED
    assert found["postgres:127.0.0.1:55432/shop"].state is ConnectionState.GONE
    credentials.reset()


def test_every_use_goes_through_the_gate(repo: Path, store: Store, mandate: Mandate) -> None:
    credentials.reset()
    credentials.broker()._values["SHOP_GH"] = "ghp_" + "x" * 20  # pyright: ignore[reportPrivateUsage]
    mandate.connections = [
        ConnectionGrant(id="gh", kind="github", location="acme/shop", credential_ref="SHOP_GH", permissions=["read"])
    ]
    (conn,) = [c for c in survey(repo, store, mandate, None, {"github": github(200, {"push": True})}) if c.grant]
    assert require(conn, mandate, "read", None, "read checks") is conn
    with pytest.raises(Unavailable, match="grants"):
        require(conn, mandate, "write", "push branch", "push")  # the token could; the mandate does not allow it
    mandate.autonomy.observe = Autonomy.DENY
    with pytest.raises(Unavailable, match="observe"):
        require(conn, mandate, "read", None, "read checks")
    conn.state = ConnectionState.REVOKED
    with pytest.raises(Unavailable, match="revoked"):
        require(conn, mandate, "read", None, "read checks")
    credentials.reset()
