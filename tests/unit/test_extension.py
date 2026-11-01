"""Block 1.4: an integration gains a documented, permitted operation only once it is validated, keeping the rest."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bench.ecosystem.depot import Depot, document, transport
from unbidden.connect.registry import record
from unbidden.contracts.connection import Connection, ConnectionState
from unbidden.contracts.guardian import Autonomy, ConnectionGrant, Mandate
from unbidden.forge import integrate
from unbidden.forge.api_client import COLLECTION, ApiIntegration, abilities, documented, oracle, signature
from unbidden.guardian import credentials
from unbidden.store import Store

pytestmark = pytest.mark.unit
KEY = "depot-key-" + "x" * 12


@pytest.fixture(autouse=True)
def held() -> Any:
    fresh = credentials.reset()
    fresh._values["DEPOT_KEY"] = KEY  # pyright: ignore[reportPrivateUsage]
    fresh.grant("DEPOT_KEY", "connection:depot")
    yield
    credentials.reset()


def read_only(mandate: Mandate, store: Store, depot: Depot, permissions: list[str]) -> Connection:
    mandate.connections = [
        ConnectionGrant(
            id="depot",
            kind="http_api",
            location="http://depot.test",
            docs="http://depot.test/openapi.json",
            credential_ref="DEPOT_KEY",
            permissions=permissions,
        )
    ]
    ops = [o for o in documented(document()) if o.id == "listBins"]
    integration = ApiIntegration(
        source="http_api:http://depot.test",
        title="Depot",
        api_version="1.4.0",
        document_url="x",
        document_sha256="x",
        signature=signature(document(), ops),
        auth={"type": "apiKey", "in": "header", "name": "X-Depot-Key"},
        operations=ops,
        documented=integrate._documented(documented(document())),
    )  # pyright: ignore[reportPrivateUsage]
    conn = Connection(
        id="http_api:http://depot.test",
        project="p",
        kind="http_api",
        protocol="http",
        location="http://depot.test",
        grant="depot",
        state=ConnectionState.CONNECTED,
    )
    integration.quality = oracle(integration, conn, mandate, store=store, transport=transport(depot))
    store.put(COLLECTION, integration)
    conn.capability_id, conn.abilities = integration.id, abilities(integration, integration.quality)
    record(store, conn, reason="test")
    return conn


def extend(
    store: Store, mandate: Mandate, conn: Connection, depot: Depot, wanted: list[str]
) -> tuple[Any, str, list[str]]:
    return asyncio.run(integrate.extend(store, mandate, conn, wanted, transport=transport(depot)))


def test_a_documented_permitted_write_is_added_validated_and_the_rest_kept(mandate: Mandate, store: Store) -> None:
    depot = Depot({KEY})
    conn = read_only(mandate, store, depot, ["read", "write:restocks"])
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    first = conn.capability_id
    extended, decision, _ = extend(store, mandate, conn, depot, ["requestRestock"])
    assert extended is not None and decision == f"extended:{first}" and extended.version == 2
    assert {o.id for o in extended.operations} == {"listBins", "requestRestock", "cancelRestock"}
    assert extended.op("requestRestock").observed_effect is not None
    old = store.get(COLLECTION, first or "", ApiIntegration)
    assert old is not None and old.status == "superseded" and old.superseded_by == extended.id


@pytest.mark.parametrize(
    ("permissions", "autonomy", "wanted", "why"),
    [
        (["read", "write:restocks"], Autonomy.ALLOW, ["deleteEverything"], "not in the documentation"),
        (["read"], Autonomy.ALLOW, ["requestRestock"], "does not allow"),
        (["read", "write:restocks"], Autonomy.REQUIRE_APPROVAL, ["requestRestock"], "approval"),
    ],
)
def test_an_extension_that_cannot_be_made_says_exactly_why(
    permissions: list[str], autonomy: Autonomy, wanted: list[str], why: str, mandate: Mandate, store: Store
) -> None:
    depot = Depot({KEY})
    conn = read_only(mandate, store, depot, permissions)
    mandate.autonomy.act_on_connections = autonomy
    extended, decision, notes = extend(store, mandate, conn, depot, wanted)
    assert extended is None and decision == "blocked" and why in " ".join(notes)
    assert depot.restocks == {}  # nothing was written to find out


def test_an_extension_that_fails_validation_is_not_enabled_and_the_old_version_stays(
    mandate: Mandate, store: Store
) -> None:
    depot = Depot({KEY})
    conn = read_only(mandate, store, depot, ["read", "write:restocks"])
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    depot.faults = {"no_effect"}
    extended, decision, _ = extend(store, mandate, conn, depot, ["requestRestock"])
    assert extended is None and decision == "rejected"
    kept = store.get(COLLECTION, conn.capability_id or "", ApiIntegration)
    assert kept is not None and kept.status == "validated"
