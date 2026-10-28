"""Typed actions: refused before acting when they should be, never sent twice, checked by reading back."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.unit.test_api_client import connected, grant, integration, key  # noqa: F401  (fixture)
from unbidden.contracts.action import Action, ActionStatus
from unbidden.contracts.connection import Ability
from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.forge import api_client
from unbidden.operate.actions import compensate, idempotency_key, propose_procedure, run_api_action
from unbidden.store import Store

pytestmark = pytest.mark.unit


class Stock:
    """A stock service whose listing shows `incoming` grow with each reorder; counts the writes it received."""

    def __init__(self) -> None:
        self.items = {"A": {"sku": "A", "on_hand": 1, "incoming": 0}}
        self.posts = 0
        self.keys: dict[str, dict[str, Any]] = {}

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json=list(self.items.values()))
            if request.method == "POST":
                self.posts += 1
                k = request.headers["Idempotency-Key"]
                if k not in self.keys:
                    body = json.loads(request.content)
                    self.items[body["sku"]]["incoming"] += body["units"]
                    self.keys[k] = {"id": f"r{len(self.keys)}", **body}
                    return httpx.Response(201, json=self.keys[k])
                return httpx.Response(200, json=self.keys[k])
            return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[-1], "status": "cancelled"})

        return httpx.MockTransport(handle)


@pytest.fixture
def setup(mandate: Mandate, monkeypatch: pytest.MonkeyPatch) -> tuple[Stock, Any, Any]:
    stock = Stock()
    real = api_client.call
    monkeypatch.setattr("unbidden.operate.actions.call", lambda *a, **k: real(*a, transport=stock.transport(), **k))
    mandate.connections = [grant(["read", "write:reorders"])]
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    built = integration(["listItems", "createReorder", "cancelReorder"])
    built.quality = {"operations": {"createReorder": {"passed": True, "observed": "made, repeated, undone"}}}
    conn = connected(["listItems"])
    conn.abilities.append(
        Ability(kind="write", operations=["createReorder", "cancelReorder"], known_by="checked: oracle")
    )
    return stock, built, conn


def proposed(units: int = 5) -> Action:
    intent = {"sku": "A", "units": units}
    return Action(
        kind="api_call",
        goal="stock-cover",
        connection="http_api:http://127.0.0.1:1",
        environment="staging",
        operation="createReorder",
        body=intent,
        requires="connection.write",
        idempotency_key=idempotency_key("stock-cover", "c", "createReorder", intent, "2026-10-28"),
    )


def test_an_action_is_verified_by_reading_its_effect_back_and_never_sent_twice(
    setup: tuple[Stock, Any, Any], store: Store, mandate: Mandate
) -> None:
    stock, built, conn = setup
    done = run_api_action(store, mandate, proposed(), built, conn, [("units within the bound", True, "5 <= 50")])
    assert done.status is ActionStatus.VERIFIED and "incoming 0 → 5" in done.reason
    assert done.compensation.available and done.compensation.operation == "cancelReorder"
    again = run_api_action(store, mandate, proposed(), built, conn, [("units within the bound", True, "5 <= 50")])
    assert again.id == done.id and stock.posts == 1  # the repeated intent was not sent again
    undone = compensate(store, mandate, done, built, conn)
    assert undone.status is ActionStatus.COMPENSATED


def test_a_failed_precondition_or_an_unobserved_write_refuses_before_anything_is_sent(
    setup: tuple[Stock, Any, Any], store: Store, mandate: Mandate
) -> None:
    stock, built, conn = setup
    refused = run_api_action(store, mandate, proposed(80), built, conn, [("units within the bound", False, "80 > 50")])
    assert refused.status is ActionStatus.REFUSED and "80 > 50" in refused.reason
    conn.abilities = [a for a in conn.abilities if a.kind == "read"]
    gated = run_api_action(store, mandate, proposed(6), built, conn, [("units within the bound", True, "6 <= 50")])
    assert gated.status is ActionStatus.REFUSED and stock.posts == 0


def test_no_compensation_is_claimed_where_none_was_observed(
    setup: tuple[Stock, Any, Any], store: Store, mandate: Mandate
) -> None:
    _, built, conn = setup
    built.quality = {"operations": {}}
    done = run_api_action(store, mandate, proposed(), built, conn, [])
    assert not done.compensation.available and "no compensation" in done.compensation.known_by
    assert compensate(store, mandate, done, built, conn).status is ActionStatus.VERIFIED  # not attempted


def test_a_deploy_procedure_found_in_the_repository_is_only_a_proposal(store: Store, tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("Deploy with `docker compose -p shop-staging up -d`.\n")
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    (found,) = propose_procedure(store, tmp_path)
    assert found.status is ActionStatus.PROPOSED and found.kind == "deploy_steps" and "a proposal only" in found.reason
    assert propose_procedure(store, tmp_path) == []  # recorded once
