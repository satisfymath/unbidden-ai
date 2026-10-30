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


def test_a_service_that_does_not_answer_as_documented_is_rejected(mandate: Mandate, store: Any) -> None:
    mandate.connections = [grant(["read"])]
    verdict = oracle(
        integration(["listItems"]), connected([]), mandate, store=store, transport=service([], honest=False)
    )
    assert not verdict["passed"] and "schema" in str(verdict["operations"]["listItems"]["error"])


def test_writes_are_not_exercised_where_the_grant_or_the_mandate_does_not_allow_them(
    mandate: Mandate, store: Any
) -> None:
    mandate.connections = [grant(["read"])]
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    verdict = oracle(
        integration(["listItems", "createReorder", "cancelReorder"]),
        connected([]),
        mandate,
        store=store,
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


def test_a_refused_key_is_an_access_problem_not_a_bad_integration(mandate: Mandate, store: Any) -> None:
    import asyncio

    from unbidden.connect.registry import get, record
    from unbidden.forge import integrate

    class Brain:
        async def complete(self, request: Any) -> Any:
            return type(
                "R",
                (),
                {
                    "content": json.dumps({"operations": [{"id": "listItems", "use": "read", "why": "x"}]}),
                    "model": "test",
                },
            )()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/o":
            return httpx.Response(200, json=DOC)
        return httpx.Response(401, json={"error": "key"})

    mandate.connections = [grant(["read"])]
    conn = connected([])
    conn.state = ConnectionState.NEEDS_CAPABILITY
    record(store, conn, reason="test")
    built, decision, _ = asyncio.run(
        integrate.build(Brain(), store, mandate, conn, transport=httpx.MockTransport(handle))
    )
    stored = get(store, conn.id)
    assert built is None and decision == "credential_refused"
    assert (
        stored is not None
        and stored.state is ConnectionState.NEEDS_AUTHORIZATION
        and "STOCK_KEY" in (stored.next_step or "")
    )
    assert store.list("integrations", ApiIntegration) == []  # nothing condemned for what the key did


def test_a_persons_approval_attaches_the_integration_to_its_connection(store: Any) -> None:
    from unbidden.connect.registry import get, record
    from unbidden.contracts.capability import CapabilityNeed, NeedStatus
    from unbidden.forge import needs

    conn = connected([])
    conn.state = ConnectionState.NEEDS_CAPABILITY
    record(store, conn, reason="test")
    approved = integration(["listItems"]).model_copy(update={"status": "approved"})
    store.put("integrations", approved)
    store.put(
        "needs",
        CapabilityNeed(
            id="need_1",
            kind="api_client",
            source=conn.id,
            why="x",
            status=NeedStatus.AWAITING_APPROVAL,
            capability_id=approved.id,
        ),
    )
    (need,) = needs.approved(store, approved.id)
    attached = get(store, conn.id)
    assert need.status is NeedStatus.IN_USE and attached is not None and attached.capability_id == approved.id


def test_a_documented_error_is_an_error_and_a_refused_key_revokes_an_integrated_connection(mandate: Mandate) -> None:
    # Found on dev (d5): a 401 the document declares was taken as an answer; the goal read "0 of 0 short".
    from unbidden.forge.api_client import CallFailed
    from unbidden.forge.integrate import live_check

    mandate.connections = [grant(["read"])]
    refused = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "key"}))
    with pytest.raises(CallFailed) as failed:
        call(integration(["listItems"]), connected(["listItems"]), mandate, "listItems", transport=refused)
    assert failed.value.status == 401
    result = live_check(integration(["listItems"]), connected(["listItems"]), mandate, transport=refused)
    assert result.state is ConnectionState.NEEDS_AUTHORIZATION and result.failure is not None


class Counting:
    """A service that counts the mutating requests it receives."""

    def __init__(self) -> None:
        self.mutations = 0
        self.inner = service([{"sku": "A", "on_hand": 1}])

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method != "GET":
                self.mutations += 1
            return self.inner.handle_request(request)

        return httpx.MockTransport(handle)


@pytest.mark.parametrize(
    ("autonomy", "approve", "mutations"),
    [
        (Autonomy.DENY, False, 0),
        (Autonomy.REQUIRE_APPROVAL, False, 0),
        (Autonomy.REQUIRE_APPROVAL, True, 3),
        (Autonomy.ALLOW, False, 3),
    ],
)
def test_the_oracle_writes_only_where_writing_is_authorized(
    autonomy: Autonomy, approve: bool, mutations: int, mandate: Mandate, store: Any
) -> None:
    from unbidden.connect.effects import approve_writes
    from unbidden.connect.registry import record

    mandate.connections = [grant(["read", "write:reorders"])]
    mandate.autonomy.act_on_connections = autonomy
    conn = connected([])
    record(store, conn, reason="test")
    if approve:
        approve_writes(store, mandate, "stock", "david", hours=1)
    counting = Counting()
    verdict = oracle(
        integration(["listItems", "createReorder", "cancelReorder"]),
        conn,
        mandate,
        store=store,
        transport=counting.transport(),
    )
    assert counting.mutations == mutations  # create, repeat, undo: or nothing at all
    sent = [
        a
        for a in store.list("actions", __import__("unbidden.contracts.action", fromlist=["Action"]).Action)
        if a.kind == "oracle_probe"
    ]
    assert len(sent) == mutations  # every probe is in the audit and the budget
    if not mutations:
        assert "not exercised" in verdict["operations"]["createReorder"]["observed"]


@pytest.mark.parametrize("stop", ["revoked", "kill switch", "budget"])
def test_no_new_effect_after_revocation_the_kill_switch_or_the_budget(
    stop: str, mandate: Mandate, tmp_path: Any
) -> None:
    from unbidden.connect.effects import authorize
    from unbidden.connect.registry import record
    from unbidden.guardian.killswitch import KillSwitch
    from unbidden.store import Store

    store = Store(tmp_path / "state.db")  # on disk: the kill switch lives beside the workspace's state
    mandate.connections = [grant(["read", "write:reorders"])]
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    conn = connected([])
    if stop == "revoked":
        conn.state = ConnectionState.REVOKED
    if stop == "budget":
        mandate.connections[0].limits["max_writes_per_day"] = 0
    record(store, conn, reason="test")
    if stop == "kill switch":
        KillSwitch.of(store).engage("stop")  # type: ignore[union-attr]
    counting = Counting()
    oracle(
        integration(["listItems", "createReorder", "cancelReorder"]),
        connected([]),
        mandate,
        store=store,
        transport=counting.transport(),
    )
    assert counting.mutations == 0
    ok, why = authorize(store, mandate, conn, "reorders", "test")
    assert not ok and (stop.split()[0] in why or "limit" in why)


def test_a_proactive_question_reaches_the_model_that_chooses_the_operations(mandate: Mandate, store: Any) -> None:
    """Stage 9 regression on Conduit: a proactive run states no goal, so the model choosing the operations saw
    "(none stated)", chose no read, and the integration Unbidden's own question needed was never built. The need now
    carries what waits for it, and the builder is told."""
    import asyncio

    from unbidden.connect.registry import record
    from unbidden.forge import integrate

    seen: list[str] = []

    class Brain:
        async def complete(self, request: Any) -> Any:
            seen.append(request.messages[0].content)
            return type("R", (), {"content": json.dumps({"operations": []}), "model": "test"})()

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DOC)

    mandate.connections = [grant(["read"])]
    conn = connected([])
    conn.state = ConnectionState.NEEDS_CAPABILITY
    record(store, conn, reason="test")
    question = "For the records GET /items returns, each count must equal what is stored. Change nothing."
    asyncio.run(integrate.build(Brain(), store, mandate, conn, transport=httpx.MockTransport(handle),
                                purposes=[question]))  # fmt: skip
    assert question in seen[0] and "asked by Unbidden itself" in seen[0] and "(none stated)" not in seen[0]


def test_a_read_outside_the_keys_scope_is_left_out_not_blamed_on_the_key(mandate: Mandate, store: Any) -> None:
    """Stage 9, LNbits: a wallet's read key answers the wallet's listings, and the account-wide one refuses it; the
    whole credential was reported as one a person must replace. The refused read is left out instead."""
    import asyncio
    import copy

    from unbidden.connect.registry import get, record
    from unbidden.forge import integrate

    doc = copy.deepcopy(DOC)
    responses = doc["paths"]["/v1/items"]["get"]["responses"]
    doc["paths"]["/v1/admin/items"] = {"get": {"operationId": "listAllItems", "responses": responses}}

    class Brain:
        async def complete(self, request: Any) -> Any:
            ops = [{"id": "listItems", "use": "read", "why": "x"}, {"id": "listAllItems", "use": "read", "why": "x"}]
            return type("R", (), {"content": json.dumps({"operations": ops}), "model": "test"})()

    items = [{"sku": "A1", "on_hand": 3}, {"sku": "B2", "on_hand": 5}]

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/o":
            return httpx.Response(200, json=doc)
        if request.url.path == "/v1/admin/items":
            return httpx.Response(401, json={"error": "an account key is needed"})
        return service(items).handle_request(request)

    mandate.connections = [grant(["read"])]
    conn = connected([])
    conn.state = ConnectionState.NEEDS_CAPABILITY
    record(store, conn, reason="test")
    built, decision, notes = asyncio.run(integrate.build(Brain(), store, mandate, conn,
                                                         transport=httpx.MockTransport(handle)))  # fmt: skip
    assert built is not None and decision == "built" and [o.id for o in built.operations] == ["listItems"]
    assert any("outside the credential's scope" in n and "listAllItems" in n for n in notes)
    stored = get(store, conn.id)
    assert stored is None or stored.state is not ConnectionState.NEEDS_AUTHORIZATION  # no person asked for a key
