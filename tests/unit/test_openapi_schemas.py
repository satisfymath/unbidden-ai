"""OpenAPI schemas are read by the version the document declares (stage 6, fix A).

Found by the frozen stage 5 evaluation (2793504): Larder documents `next_cursor` as `type: string, nullable: true`
(OpenAPI 3.0); responses were validated as plain JSON Schema, `null` was "outside its documented schema", and the
integration was rejected in all four scenarios."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import ValidationError

from unbidden.forge import oas_schema
from unbidden.forge.api_client import CallFailed, documented
from unbidden.forge.oas_schema import UnsupportedSchema, read, validate

pytestmark = pytest.mark.unit


def doc(openapi: str, schemas: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"openapi": openapi, "info": {"title": "t", "version": "1"}, "paths": {},
            "components": {"schemas": schemas}, **extra}  # fmt: skip


THING_30 = {
    "type": "object",
    "required": ["id", "label"],
    "properties": {
        "id": {"type": "string", "readOnly": True},
        "label": {"type": "string", "nullable": True},
        "tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}},
        "kind": {"type": "string", "nullable": True, "enum": ["a", "b"]},
        "size": {"type": "integer", "minimum": 0, "exclusiveMinimum": True},
        "secret": {"type": "string", "writeOnly": True},
    },
}
TAG_30 = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "nullable": True}}}


def thing(direction: str = "response") -> dict[str, Any]:
    d = doc("3.0.3", {"Thing": THING_30, "Tag": TAG_30})
    return read(d, {"$ref": "#/components/schemas/Thing"}, direction)  # type: ignore[arg-type]


def test_a_documented_null_is_accepted_where_nullable_and_nowhere_else() -> None:
    schema = thing()
    validate({"id": "1", "label": None}, schema)  # present and null: documented
    validate({"id": "1", "label": "x", "tags": [{"name": None}]}, schema)  # nested, through a $ref
    with pytest.raises(ValidationError):
        validate({"id": "1"}, schema)  # absent is not null: `label` is required
    with pytest.raises(ValidationError):
        validate({"id": None, "label": "x"}, schema)  # `id` is not nullable
    with pytest.raises(ValidationError):
        validate({"id": "1", "label": 5}, schema)  # a real type error stays one
    with pytest.raises(ValidationError):
        validate({"id": "1", "label": "x", "tags": [{"name": 3}]}, schema)


def test_other_constraints_keep_their_meaning_beside_nullable() -> None:
    schema = thing()
    with pytest.raises(ValidationError):
        validate({"id": "1", "label": "x", "kind": None}, schema)  # the enum does not list null (OAS 3.0.3)
    validate({"id": "1", "label": "x", "kind": "a"}, schema)


def test_the_draft_05_exclusive_minimum_and_read_or_write_only() -> None:
    schema = thing()
    with pytest.raises(ValidationError):
        validate({"id": "1", "label": "x", "size": 0}, schema)  # exclusive: 0 is not above 0
    validate({"id": "1", "label": "x", "size": 1}, schema)
    validate({"label": "x"}, thing("request"))  # `id` is readOnly: not required in a request
    with pytest.raises(ValidationError):
        validate({"label": "x"}, thing("response"))


def test_openapi_3_1_reads_type_arrays_and_refuses_what_is_not_3_1() -> None:
    d = doc("3.1.0", {"T": {"type": "object", "properties": {"next": {"type": ["string", "null"]}}}})
    schema = read(d, {"$ref": "#/components/schemas/T"}, "response")
    validate({"next": None}, schema)
    with pytest.raises(ValidationError):
        validate({"next": 1}, schema)
    with pytest.raises(UnsupportedSchema, match="nullable"):
        read(doc("3.1.0", {}), {"type": "string", "nullable": True}, "response")
    with pytest.raises(UnsupportedSchema, match="one type"):
        read(doc("3.0.3", {}), {"type": ["string", "null"]}, "response")
    # 3.1: a $ref's siblings apply beside it; 3.0: they are ignored.
    ref = {"$ref": "#/components/schemas/S", "maxLength": 2}
    assert "allOf" in read(doc("3.1.0", {"S": {"type": "string"}}), ref, "response")
    assert read(doc("3.0.3", {"S": {"type": "string"}}), ref, "response") == {"type": "string"}


@pytest.mark.parametrize(
    ("document", "why"),
    [
        ({"swagger": "2.0", "paths": {}}, "Swagger"),
        ({"openapi": "4.0.0", "paths": {}}, "only 3.0.x and 3.1.x"),
        ({"openapi": "3.1.0", "jsonSchemaDialect": "https://example.com/other", "paths": {}}, "dialect"),
    ],
)
def test_documents_not_read_are_refused_with_why(document: dict[str, Any], why: str) -> None:
    with pytest.raises(UnsupportedSchema, match=why):
        oas_schema.version(document)


def test_remote_and_recursive_references_are_refused() -> None:
    with pytest.raises(UnsupportedSchema, match="inside the document"):
        read(doc("3.0.3", {}), {"$ref": "https://example.com/x.json"}, "response")
    with pytest.raises(UnsupportedSchema, match="itself"):
        read(doc("3.0.3", {"N": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/N"}}}}),
             {"$ref": "#/components/schemas/N"}, "response")  # fmt: skip


def test_larder_reads_whole_through_the_real_client() -> None:
    """The evaluation's failure, reproduced through `documented` and `call`: the last page's `next_cursor: null`."""
    from bench.ecosystem.larder import Larder, document, transport
    from bench.ecosystem.larder_lab import stock
    from unbidden.connect.pages import read_all
    from unbidden.contracts.connection import Connection, ConnectionState
    from unbidden.contracts.guardian import ConnectionGrant, Mandate
    from unbidden.forge.api_client import ApiIntegration, call
    from unbidden.guardian import credentials

    held = credentials.reset()
    held._values["T"] = "tok"  # pyright: ignore[reportPrivateUsage]
    held.grant("T", "connection:larder")
    try:
        ops = [o for o in documented(document()) if o.id == "listItems"]
        integration = ApiIntegration(source="x", title="Larder", api_version="2.1.0", document_url="x",
                                     document_sha256="x", signature="x", operations=ops,
                                     auth={"type": "apiKey", "in": "header", "name": "X-Api-Token"})  # fmt: skip
        conn = Connection(id="http_api:http://larder.test", project="p", kind="http_api", protocol="http",
                          location="http://larder.test", grant="larder", state=ConnectionState.CONNECTED)  # fmt: skip
        mandate = Mandate(workspace="w", connections=[ConnectionGrant(id="larder", kind="http_api",
                          location="http://larder.test", credential_ref="T", permissions=["read"])])  # fmt: skip
        items, _ = stock()
        service = transport(Larder({"tok"}, items))

        def fetch(params: dict[str, Any]) -> Any:
            return call(integration, conn, mandate, "listItems", params=params, transport=service, gate=False)[1]

        whole = read_all(fetch, ops[0].parameters)
        assert whole.completeness.value == "complete" and len(whole.records) == 37
        bad = Larder({"tok"}, items)
        bad.items["P-001"]["on_hand"] = "lots"  # a real schema violation is still one
        with pytest.raises(CallFailed, match="outside its documented schema"):
            read_all(lambda p: call(integration, conn, mandate, "listItems", params=p, transport=transport(bad),
                                    gate=False)[1], ops[0].parameters)  # fmt: skip
    finally:
        credentials.reset()


@pytest.mark.parametrize(
    ("path", "scope"),
    [
        ("/api/v2/transfers", "transfers"),  # Larder: read as "api" on c804aaf, so `write:transfers` never matched
        ("/v1/restocks/{restock_id}", "restocks"),
        ("/v3/deliveries", "deliveries"),
        ("/rest/v1.1/orders", "orders"),
        ("/reorders", "reorders"),
        ("/", "root"),
    ],
)
def test_a_write_scope_is_the_resource_not_the_api_prefix(path: str, scope: str) -> None:
    from unbidden.forge.api_client import _scope  # pyright: ignore[reportPrivateUsage]

    assert _scope(path) == scope


def test_a_listing_read_that_fails_says_why_in_the_verdict(store: object, mandate: object) -> None:
    """Regression a5 (Larder `bad_page`): the integration was rightly rejected, but its verdict read "read not at all
    ()", hiding the cause; a person needs the block itself."""
    from bench.ecosystem.larder import Larder, document, transport
    from bench.ecosystem.larder_lab import stock
    from unbidden.contracts.connection import Connection, ConnectionState
    from unbidden.contracts.guardian import ConnectionGrant, Mandate
    from unbidden.forge.api_client import ApiIntegration, oracle
    from unbidden.guardian import credentials
    from unbidden.store import Store

    assert isinstance(store, Store) and isinstance(mandate, Mandate)
    held = credentials.reset()
    held._values["T"] = "tok"  # pyright: ignore[reportPrivateUsage]
    held.grant("T", "connection:larder")
    try:
        mandate.connections = [ConnectionGrant(id="larder", kind="http_api", location="http://larder.test",
                                               credential_ref="T", permissions=["read"])]  # fmt: skip
        ops = [o for o in documented(document()) if o.id == "listItems"]
        integration = ApiIntegration(source="x", title="Larder", api_version="2.1.0", document_url="x",
                                     document_sha256="x", signature="x", operations=ops,
                                     auth={"type": "apiKey", "in": "header", "name": "X-Api-Token"})  # fmt: skip
        conn = Connection(id="http_api:http://larder.test", project="p", kind="http_api", protocol="http",
                          location="http://larder.test", grant="larder", state=ConnectionState.CONNECTED)  # fmt: skip
        items, _ = stock()
        verdict = oracle(integration, conn, mandate, store=store,
                         transport=transport(Larder({"tok"}, items, {"bad_page"})))  # fmt: skip
        observed = verdict["operations"]["listItems"]["observed"]
        assert not verdict["passed"] and observed.startswith("read failed:") and "documented schema" in observed
    finally:
        credentials.reset()
