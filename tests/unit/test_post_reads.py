"""Reads by POST (stage 10): Prefect reads with `POST .../filter`, and stage 9 treated every POST as a write.

A POST is read as a read only when its document says so in every way that can be checked (a listing or a count
answered 200, a body made only of query fields, read words and no word of a change), and then only once the same
request answered the same twice and the collection's documented count did not move around it. Anything less stays a
write. Pages are followed through the body; the count, read before and after, decides completeness."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from unbidden.connect.pages import Completeness
from unbidden.contracts.connection import Ability, Connection, ConnectionState
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.forge.api_client import ApiIntegration, documented, observe_post_read, read_collection, signature

pytestmark = pytest.mark.unit

RUN = {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}, "required": ["id"]}
FILTER = {"type": "object", "description": "Filter criteria for runs", "properties": {"name": {"type": "string"}}}


def op(summary: str, body: dict[str, Any], answer: dict[str, Any], *, code: str = "200") -> dict[str, Any]:
    return {"summary": summary, "operationId": summary.lower().replace(" ", "_"),
            "requestBody": {"content": {"application/json": {"schema": body}}},
            "responses": {code: {"content": {"application/json": {"schema": answer}}}}}  # fmt: skip


PAGED = {"type": "object", "properties": {"offset": {"type": "integer"}, "limit": {"type": "integer", "maximum": 10},
                                          "runs": FILTER, "sort": {"type": "string"}}}  # fmt: skip
DOCUMENT = {
    "openapi": "3.1.0",
    "info": {"title": "Runs", "version": "1.0.0"},
    "paths": {
        "/runs/filter": {"post": op("Read Runs", PAGED, {"type": "array", "items": RUN})},
        "/runs/count": {"post": op("Count Runs", {"type": "object", "properties": {"runs": FILTER}},
                                   {"type": "integer"})},
        "/runs/{id}/set_state": {"post": op("Set Run State", {"type": "object"}, RUN)},
        "/documents/filter": {"post": op("Read Documents", {
            "type": "object", "properties": {"include_secrets": {"type": "boolean"}, "limit": {"type": "integer"}}},
            {"type": "array", "items": RUN})},
        "/runs": {"post": op("Create Run", {"type": "object", "properties": {"name": {"type": "string"}},
                                            "required": ["name"]}, RUN, code="201")},
        "/queue/filter": {"post": op("Read Queue", PAGED, {"type": "array", "items": RUN})},
    },
}  # fmt: skip


def test_only_a_post_the_document_describes_as_a_read_in_every_way_is_one() -> None:
    effects = {o.path: o.effect for o in documented(DOCUMENT)}
    assert effects["/runs/filter"] == "read" and effects["/runs/count"] == "read"
    assert effects["/runs/{id}/set_state"] == "write"  # a change in its name
    assert effects["/documents/filter"] == "write"  # `include_secrets` is not a query field
    assert effects["/runs"] == "write"  # 201, a required field of the record


class Service:
    """Runs served by POST; `faults` make it misbehave the ways a read must notice."""

    def __init__(self, n: int = 23, *faults: str) -> None:
        self.rows = [{"id": f"r{i:03}", "name": f"run {i}"} for i in range(n)]
        self.faults = set(faults)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.calls += 1
        if request.url.path == "/runs/count":
            return httpx.Response(200, json=len(self.rows))
        if request.url.path == "/queue/filter":  # documented as a read; claims what it returns
            self.rows = self.rows[1:]
            return httpx.Response(200, json=self.rows[:1])
        offset, limit = int(body.get("offset", 0)), int(body.get("limit", 10))
        if "repeat" in self.faults and offset >= 10:
            offset -= 10  # the second page again
        if "grow" in self.faults and offset >= 10:
            self.rows.append({"id": f"x{len(self.rows)}", "name": "late"})
        if "short" in self.faults and offset >= 10:
            return httpx.Response(200, json=[])
        if "wrong" in self.faults:
            return httpx.Response(200, json={"unexpected": True})
        return httpx.Response(200, json=self.rows[offset : offset + limit])


def setup(mandate: Mandate, service: Service) -> tuple[ApiIntegration, Connection, httpx.MockTransport]:
    mandate.connections = [ConnectionGrant(id="runs", kind="http_api", location="http://runs.test", docs="x",
                                           permissions=["read"])]  # fmt: skip
    ops = documented(DOCUMENT)
    integration = ApiIntegration(source="http_api:http://runs.test", title="Runs", api_version="1.0.0",
                                 document_url="x", document_sha256="x", signature=signature(DOCUMENT, ops),
                                 auth={}, operations=ops)  # fmt: skip
    conn = Connection(id="http_api:http://runs.test", project="p", kind="http_api", protocol="http",
                      location="http://runs.test", grant="runs", state=ConnectionState.CONNECTED,
                      abilities=[Ability(kind="read", operations=[o.id for o in ops if o.effect == "read"],
                                         known_by="checked: oracle")])  # fmt: skip
    return integration, conn, httpx.MockTransport(service)


def read(mandate: Mandate, *faults: str) -> Any:
    integration, conn, transport = setup(mandate, Service(23, *faults))
    return read_collection(integration, conn, mandate, "read_runs", transport=transport, page_size=10)


def test_pages_are_followed_through_the_body_and_the_count_confirms_the_whole(mandate: Mandate) -> None:
    got = read(mandate)
    assert len(got.records) == 23 and got.completeness is Completeness.COMPLETE
    assert "count_runs says 23 before and after" in got.why


@pytest.mark.parametrize(
    ("fault", "state", "why"),
    [
        ("repeat", Completeness.INCOMPLETE, "already read"),  # a repeated page
        ("grow", Completeness.UNKNOWN, "the collection changed"),  # a change between pages
        ("short", Completeness.INCOMPLETE, "count_runs says 23; 10 distinct"),  # an end before the count's
    ],
)
def test_a_read_that_cannot_be_whole_says_so(mandate: Mandate, fault: str, state: Completeness, why: str) -> None:
    got = read(mandate, fault)
    assert got.completeness is state and why in got.why


def test_an_answer_outside_the_document_is_refused(mandate: Mandate) -> None:
    from unbidden.forge.api_client import CallFailed

    with pytest.raises(CallFailed, match="outside its documented schema"):
        read(mandate, "wrong")


def test_without_a_count_the_read_is_not_called_complete_and_a_bound_is_partial(mandate: Mandate) -> None:
    integration, conn, transport = setup(mandate, Service(23))
    integration.operations = [o for o in integration.operations if o.path != "/runs/count"]
    got = read_collection(integration, conn, mandate, "read_runs", transport=transport, page_size=10)
    assert got.completeness is not Completeness.COMPLETE or "short page" in got.why
    from unbidden.connect.pages import MAX_PAGES

    integration, conn, transport = setup(mandate, Service(10 * MAX_PAGES + 5))
    bounded = read_collection(integration, conn, mandate, "read_runs", transport=transport, page_size=10)
    assert bounded.completeness is Completeness.INCOMPLETE and "bound" in bounded.why  # a limit reached


def test_a_documented_read_that_changes_what_it_reads_is_caught(mandate: Mandate) -> None:
    integration, conn, transport = setup(mandate, Service(23))
    honest = observe_post_read(integration, conn, mandate, integration.op("read_runs"), transport=transport)
    assert honest[0] and "unchanged (23)" in honest[1]
    lying = observe_post_read(integration, conn, mandate, integration.op("read_queue"), transport=transport)
    assert not lying[0] and "answered differently" in lying[1]
