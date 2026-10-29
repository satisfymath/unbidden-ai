"""Controlled compatibility of API reads (stage 8): a document and its responses may differ; what that may decide.

Found on Conduit (frozen run 9ef6a60): its FastAPI document declares optional fields as non-null strings and the
API returns null for them; one such null rejected the whole integration. A degraded read may continue past an
accessory deviation, recorded; a deviation on what a conclusion needs blocks it; a count that contradicts the next
page makes the read incomplete; writes stay strict. The service here is synthetic (Conduit-like), not Conduit."""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest

from unbidden.connect.pages import Completeness
from unbidden.contracts.connection import Connection, ConnectionState
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.forge.api_client import (
    ApiIntegration,
    CallFailed,
    Degraded,
    DeviationBlocked,
    call,
    documented,
    read_collection,
)
from unbidden.guardian import credentials

pytestmark = pytest.mark.unit
AUTHOR = {"type": "object", "required": ["username", "bio", "image"],
          "properties": {"username": {"type": "string"}, "bio": {"type": "string"},
                         "image": {"type": "string"}}}  # fmt: skip
ARTICLE = {"type": "object", "required": ["id", "slug", "favoritesCount", "author"],
           "properties": {"id": {"type": "integer"}, "slug": {"type": "string"}, "favoritesCount": {"type": "integer"},
                          "author": AUTHOR}}  # fmt: skip
DOC: dict[str, Any] = {
    "openapi": "3.0.2", "info": {"title": "Blog", "version": "1"},
    "paths": {
        "/api/articles": {"get": {"operationId": "listArticles", "parameters": [
            {"name": "offset", "in": "query", "schema": {"type": "integer"}},
            {"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 2}}],
            "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {
                "type": "object", "required": ["articles", "count"],
                "properties": {"articles": {"type": "array", "items": ARTICLE}, "count": {"type": "integer"}}}}}}}}},
        "/api/articles/{slug}/favorite": {"post": {"operationId": "favorite", "parameters": [
            {"name": "slug", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": ARTICLE}}}}}},
    },
}  # fmt: skip


def article(i: int, **change: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"id": i, "slug": f"a-{i}", "favoritesCount": i,
                           "author": {"username": "u", "bio": "", "image": None}}  # fmt: skip
    for path, value in change.items():
        target, *rest = path.split("__")
        if rest:
            if value is ABSENT:
                out[target].pop(rest[0])
            else:
                out[target][rest[0]] = value
        elif value is ABSENT:
            out.pop(target)
        else:
            out[target] = value
    return out


ABSENT = object()


def service(rows: list[dict[str, Any]], *, count: str = "true") -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=article(1))  # author.image null: a write's answer
        offset, limit = int(request.url.params.get("offset", 0)), int(request.url.params.get("limit", 2))
        batch = rows[offset : offset + limit]
        total = len(rows) if count == "true" else len(batch)  # "page": the page's own length, as Conduit's
        return httpx.Response(200, json={"articles": batch, "count": total})

    return httpx.MockTransport(handle)


@pytest.fixture
def setup() -> Any:
    held = credentials.reset()
    held._values["T"] = "tok"  # pyright: ignore[reportPrivateUsage]
    held.grant("T", "connection:blog")
    doc = copy.deepcopy(DOC)
    ops = documented(doc)
    auth = {"type": "apiKey", "in": "header", "name": "K"}
    integration = ApiIntegration(source="x", title="Blog", api_version="1", document_url="x", document_sha256="x",
                                 signature="x", operations=ops, auth=auth)  # fmt: skip
    conn = Connection(id="http_api:http://blog.test", project="p", kind="http_api", protocol="http",
                      location="http://blog.test", grant="blog", state=ConnectionState.CONNECTED)  # fmt: skip
    mandate = Mandate(workspace="w", connections=[ConnectionGrant(id="blog", kind="http_api",
                      location="http://blog.test", credential_ref="T", permissions=["read", "write"])])  # fmt: skip
    yield integration, conn, mandate, doc
    credentials.reset()


def read(setup: Any, rows: list[dict[str, Any]], degraded: Degraded | None, count: str = "true") -> Any:
    integration, conn, mandate, _ = setup
    transport = service(rows, count=count)
    return read_collection(integration, conn, mandate, "listArticles", gate=False, transport=transport,
                           degraded=degraded)  # fmt: skip


def test_an_accessory_null_degrades_the_read_recorded_and_the_document_is_untouched(setup: Any) -> None:
    rows = [article(i) for i in range(1, 4)]
    with pytest.raises(CallFailed):  # without the allowance: strict, as before
        read(setup, rows, None)
    log = Degraded()
    whole = read(setup, rows, log)
    assert whole.completeness is Completeness.COMPLETE and len(whole.records) == 3
    assert whole.records[0]["author"]["image"] is None  # nothing invented
    (dev,) = {(d["field"], d["observed"], d["decision"][:14]) for d in log.log}
    assert dev[0].endswith("image") and dev[1] == "null" and dev[2] == "read continues"
    assert all(d["declared"] == "type string" and d["at"] and "GET /api/articles" in d["source"] for d in log.log)
    assert setup[3] == DOC  # the published document is kept as it was


@pytest.mark.parametrize(
    ("change", "why"),
    [({"slug": None}, "slug"), ({"id": "seven"}, "id"), ({"id": ABSENT}, "id"),
     ({"favoritesCount": None}, "favoritesCount")],
)  # fmt: skip
def test_a_deviation_on_what_identifies_or_counts_blocks(setup: Any, change: dict[str, Any], why: str) -> None:
    with pytest.raises(DeviationBlocked, match=why):
        read(setup, [article(1, **change), article(2)], Degraded())


def test_an_absent_accessory_field_degrades_and_a_compared_field_blocks(setup: Any) -> None:
    whole = read(setup, [article(1, author__bio=ABSENT), article(2)], Degraded())
    assert len(whole.records) == 2 and "bio" not in whole.records[0]["author"]
    # A goal that compares `bio` names it critical: the same deviation now blocks its conclusion.
    with pytest.raises(DeviationBlocked, match="bio"):
        read(setup, [article(1, author__bio=ABSENT), article(2)], Degraded(critical={"bio"}))


def test_a_count_that_is_the_pages_own_length_makes_the_read_incomplete(setup: Any) -> None:
    rows = [article(i) for i in range(1, 6)]
    page_count = read(setup, rows, Degraded(), count="page")
    assert page_count.completeness is Completeness.INCOMPLETE and "contradicted" in page_count.why
    assert read(setup, rows, Degraded()).completeness is Completeness.COMPLETE


def test_writes_stay_strict_even_when_a_read_may_degrade(setup: Any, tmp_path: Any) -> None:
    from unbidden.connect.registry import record
    from unbidden.contracts.guardian import Autonomy
    from unbidden.store import Store

    integration, conn, mandate, _ = setup
    store = Store(tmp_path / "state.db")
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    record(store, conn, reason="test")
    with pytest.raises(CallFailed, match="outside its documented schema") as raised:
        call(integration, conn, mandate, "favorite", params={"slug": "a-1"}, gate=False, transport=service([]),
             store=store, degraded=Degraded())  # fmt: skip
    assert not isinstance(raised.value, DeviationBlocked)  # strict, not a degraded read
