"""Block 1.3: a collection is read whole or said not to be, and the oracle does not share the reader's trust."""

from __future__ import annotations

from typing import Any

import pytest

from bench.ecosystem.depot import Depot, document, transport
from unbidden.connect.pages import Completeness, cross_check, read_all
from unbidden.contracts.connection import Ability, Connection, ConnectionState
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.forge.api_client import ApiIntegration, documented, oracle, read_collection, signature
from unbidden.guardian import credentials

pytestmark = pytest.mark.unit
KEY = "depot-key-" + "x" * 12


@pytest.fixture(autouse=True)
def held() -> Any:
    fresh = credentials.reset()
    fresh._values["DEPOT_KEY"] = KEY  # pyright: ignore[reportPrivateUsage]
    fresh.grant("DEPOT_KEY", "connection:depot")
    yield
    credentials.reset()


def setup(mandate: Mandate, *faults: str) -> tuple[ApiIntegration, Connection, Any]:
    mandate.connections = [
        ConnectionGrant(
            id="depot",
            kind="http_api",
            location="http://depot.test",
            docs="x",
            credential_ref="DEPOT_KEY",
            permissions=["read"],
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
    )
    conn = Connection(
        id="http_api:http://depot.test",
        project="p",
        kind="http_api",
        protocol="http",
        location="http://depot.test",
        grant="depot",
        state=ConnectionState.CONNECTED,
        abilities=[Ability(kind="read", operations=["listBins"], known_by="checked: oracle")],
    )
    return integration, conn, transport(Depot({KEY}, set(faults)))


def test_offset_pagination_is_followed_to_its_declared_total(mandate: Mandate) -> None:
    integration, conn, t = setup(mandate)
    read = read_collection(integration, conn, mandate, "listBins", transport=t)
    assert read.completeness is Completeness.COMPLETE and len(read.records) == 11 and read.style == "offset"


@pytest.mark.parametrize(
    ("fault", "why"), [("skip_page", "already read"), ("repeat_page", "already read"), ("short_total", "declared 9")]
)
def test_a_read_that_cannot_be_whole_says_so(fault: str, why: str, mandate: Mandate) -> None:
    integration, conn, t = setup(mandate, fault)
    read = read_collection(integration, conn, mandate, "listBins", transport=t)
    assert read.completeness is Completeness.INCOMPLETE and why in read.why


def test_a_service_that_hides_a_page_fools_the_reader_but_not_the_oracle(mandate: Mandate, store: Any) -> None:
    integration, conn, t = setup(mandate, "hide_page")
    read = read_collection(integration, conn, mandate, "listBins", transport=t)
    assert read.completeness is Completeness.COMPLETE  # consistent lies are invisible to one reading
    agrees, _ = cross_check(
        read,
        lambda p: __import__("unbidden.forge.api_client", fromlist=["call"]).call(
            integration, conn, mandate, "listBins", params=p, transport=t
        )[1],
        integration.op("listBins").parameters,
    )
    assert not agrees
    verdict = oracle(integration, conn, mandate, store=store, transport=t)
    assert not verdict["passed"] and "differ" in verdict["operations"]["listBins"]["observed"]


def test_cursor_and_page_styles_and_their_failures() -> None:
    pages = {
        None: {"items": [{"id": 1}], "next": "a"},
        "a": {"items": [{"id": 2}], "next": "b"},
        "b": {"items": [{"id": 3}]},
    }
    cursor = [{"name": "cursor", "in": "query"}]
    assert read_all(lambda p: pages[p.get("cursor")], cursor).completeness is Completeness.COMPLETE
    looping = {None: {"items": [{"id": 1}], "next": "a"}, "a": {"items": [{"id": 2}], "next": "a"}}
    assert read_all(lambda p: looping[p.get("cursor")], cursor).completeness is Completeness.INCOMPLETE
    numbered = [{"name": "page", "in": "query"}]
    data = {1: {"items": [{"id": 1}], "pages": 2}, 2: {"items": [{"id": 2}], "pages": 2}}
    assert read_all(lambda p: data[p["page"]], numbered).completeness is Completeness.COMPLETE
    unbounded = read_all(lambda p: {"items": [{"id": p["page"]}]}, numbered, max_pages=5)
    assert unbounded.completeness is Completeness.INCOMPLETE and "read bound" in unbounded.why
    by_records = read_all(lambda p: {"items": [{"id": 3 * p["page"] + i} for i in range(3)]}, numbered, max_records=7)
    assert by_records.completeness is Completeness.INCOMPLETE and by_records.requests == 3  # records, not requests
