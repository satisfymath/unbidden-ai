"""Integrations built from a document: the model chooses among documented operations, the oracle decides."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from unbidden.connect.base import Unavailable
from unbidden.contracts.connection import Ability, Connection, ConnectionState
from unbidden.contracts.guardian import Autonomy, ConnectionGrant, Mandate
from unbidden.forge.api_client import ApiIntegration, call, choose, documented, oracle, signature
from unbidden.guardian import credentials

pytestmark = pytest.mark.unit

ITEM = {
    "type": "object",
    "required": ["sku", "on_hand"],
    "properties": {"sku": {"type": "string"}, "on_hand": {"type": "integer"}},
}
DOC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Stock", "version": "1.0"},
    "components": {"securitySchemes": {"k": {"type": "apiKey", "in": "header", "name": "X-Key"}}},
    "paths": {
        "/v1/items": {
            "get": {
                "operationId": "listItems",
                "responses": {
                    "200": {"content": {"application/json": {"schema": {"type": "array", "items": ITEM}}}},
                    "401": {"content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/v1/reorders": {
            "post": {
                "operationId": "createReorder",
                "parameters": [
                    {"name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string"}}
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["sku", "units"],
                                "properties": {"sku": {"type": "string"}, "units": {"type": "integer", "minimum": 1}},
                            }
                        }
                    }
                },
                "responses": {
                    "201": {"content": {"application/json": {"schema": {"type": "object"}}}},
                    "200": {"content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/v1/reorders/{id}": {
            "delete": {
                "operationId": "cancelReorder",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
            }
        },
    },
}


def grant(permissions: list[str]) -> ConnectionGrant:
    return ConnectionGrant(
        id="stock",
        kind="http_api",
        location="http://127.0.0.1:1",
        docs="http://127.0.0.1:1/o",
        credential_ref="STOCK_KEY",
        permissions=permissions,
    )


def connected(ops: list[str], kind: str = "read") -> Connection:
    return Connection(
        id="http_api:http://127.0.0.1:1",
        project="p",
        kind="http_api",
        protocol="http",
        location="http://127.0.0.1:1",
        grant="stock",
        state=ConnectionState.CONNECTED,
        abilities=[Ability(kind=kind, operations=ops, known_by="checked: oracle")],
    )


def integration(ops: list[str]) -> ApiIntegration:
    chosen = [o for o in documented(DOC) if o.id in ops]
    if "createReorder" in ops:
        chosen = [
            o.model_copy(update={"undo": "cancelReorder" if "cancelReorder" in ops else None})
            if o.id == "createReorder"
            else o
            for o in chosen
        ]
    return ApiIntegration(
        source="http_api:http://127.0.0.1:1",
        title="Stock",
        api_version="1.0",
        document_url="x",
        document_sha256="x",
        signature=signature(DOC, chosen),
        auth={"type": "apiKey", "in": "header", "name": "X-Key"},
        operations=chosen,
    )


@pytest.fixture(autouse=True)
def key() -> Any:
    fresh = credentials.reset()
    fresh._values["STOCK_KEY"] = "k" * 20  # pyright: ignore[reportPrivateUsage]
    fresh.grant("STOCK_KEY", "connection:stock")
    yield
    credentials.reset()


def service(items: Any, *, honest: bool = True) -> httpx.MockTransport:
    reorders: dict[str, dict[str, Any]] = {}
    keys: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.headers.get("X-Key") != "k" * 20:
            return httpx.Response(401, json={"error": "key"})
        if request.method == "GET":
            return httpx.Response(200, json=items if honest else {"not": "a list"})
        if request.method == "POST":
            k = request.headers["Idempotency-Key"]
            if k in keys:
                return httpx.Response(200, json=reorders[keys[k]])
            keys[k] = f"r{len(keys)}"
            reorders[keys[k]] = {"id": keys[k], **json.loads(request.content), "status": "pending"}
            return httpx.Response(201, json=reorders[keys[k]])
        rid = request.url.path.rsplit("/", 1)[-1]
        reorders[rid]["status"] = "cancelled"
        return httpx.Response(200, json=reorders[rid])

    return httpx.MockTransport(handle)


def test_the_choice_keeps_documented_operations_granted_writes_and_their_undo() -> None:
    answer = {
        "operations": [
            {"id": "listItems", "use": "read", "why": "stock"},
            {"id": "deleteEverything", "use": "write", "why": "invented"},
            {"id": "createReorder", "use": "write", "why": "restock"},
        ]
    }
    chosen, notes = choose(answer, documented(DOC), grant(["read", "write:reorders"]))
    by_id = {o.id: o for o in chosen}
    assert (
        set(by_id) == {"listItems", "createReorder", "cancelReorder"} and by_id["createReorder"].undo == "cancelReorder"
    )
    assert any("not in the document" in n for n in notes)
    read_only, notes = choose(answer, documented(DOC), grant(["read"]))
    assert [o.id for o in read_only] == ["listItems"] and any("does not allow" in n for n in notes)


def test_a_service_that_does_not_answer_as_documented_is_rejected(mandate: Mandate) -> None:
    mandate.connections = [grant(["read"])]
    verdict = oracle(integration(["listItems"]), connected([]), mandate, transport=service([], honest=False))
    assert not verdict["passed"] and "schema" in str(verdict["operations"]["listItems"]["error"])


def test_a_write_is_enabled_only_once_made_repeated_and_undone(mandate: Mandate) -> None:
    mandate.connections = [grant(["read", "write:reorders"])]
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    items = [{"sku": "A", "on_hand": 1}]
    verdict = oracle(
        integration(["listItems", "createReorder", "cancelReorder"]), connected([]), mandate, transport=service(items)
    )
    assert verdict["passed"] and verdict["operations"]["createReorder"]["passed"]
    no_undo = oracle(integration(["listItems", "createReorder"]), connected([]), mandate, transport=service(items))
    assert not no_undo["operations"]["createReorder"]["passed"]  # no undo observed: never enabled


def test_writes_are_not_exercised_where_the_grant_or_the_mandate_does_not_allow_them(mandate: Mandate) -> None:
    mandate.connections = [grant(["read"])]
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    verdict = oracle(
        integration(["listItems", "createReorder", "cancelReorder"]),
        connected([]),
        mandate,
        transport=service([{"sku": "A", "on_hand": 1}]),
    )
    assert verdict["passed"] and "not exercised" in verdict["operations"]["createReorder"]["observed"]


def test_every_call_passes_the_gate_and_is_built_from_the_document(mandate: Mandate) -> None:
    mandate.connections = [grant(["read"])]
    transport = service([{"sku": "A", "on_hand": 1}])
    assert (
        call(integration(["listItems"]), connected(["listItems"]), mandate, "listItems", transport=transport)[0] == 200
    )
    with pytest.raises(Unavailable):  # a checked read is not a write
        call(
            integration(["listItems", "createReorder"]),
            connected(["listItems"]),
            mandate,
            "createReorder",
            body={"sku": "A", "units": 1},
            idempotency_key="k" * 10,
            transport=transport,
        )
    with pytest.raises(Unavailable):
        call(integration(["listItems"]), connected(["listItems"]), mandate, "getAnything", transport=transport)
