"""Integrations with HTTP APIs, built from their own documentation, accepted only against the live service.

An integration is data, never code: the operations a need requires, copied from the API's OpenAPI document with
their parameter, body and response schemas, each marked read or write, plus the credential's *reference*, the
destination, limits, the checks it passed, its version and provenance. One fixed executor (`call`) runs it, and the
connection gate and the broker apply there, at each call, so nothing built here can widen what it may reach or do.

The local model's part is small and checked: choosing which documented operations a goal needs. It cannot invent
one (ids are checked against the document) nor change a schema (schemas come from the document). Acceptance is the
oracle's, without the model: calls against the live service, responses validated against the document's own
schemas, list and get agreeing, the key's absence refused as documented, and, only where the mandate grants writes
in a non-production environment, each write made, repeated with its idempotency key, and undone by its
compensation, each step observed. A write whose undo was not observed is never enabled.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
import jsonschema
from pydantic import Field

from unbidden.connect.base import Unavailable, purpose, require
from unbidden.contracts.common import Contract, new_id, utc_now
from unbidden.contracts.connection import Ability, Connection
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.guardian.credentials import broker

COLLECTION = "integrations"
ORACLE_VERSION = 1
MAX_PAGES = 10
METHODS = ("get", "post", "put", "patch", "delete")


class Operation(Contract):
    id: str
    method: str
    path: str
    summary: str = ""
    effect: str  # read | write
    scope: str  # the resource it acts on ("reorders"), what a grant's `write:<scope>` names
    parameters: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    body_schema: dict[str, Any] | None = None
    responses: dict[str, dict[str, Any] | None] = Field(default_factory=dict[str, dict[str, Any] | None])
    undo: str | None = None  # the operation that compensates this write, when one was observed to
    why: str = ""


class ApiIntegration(Contract):
    id: str = Field(default_factory=lambda: new_id("int"))
    kind: str = "api_client"
    source: str  # the connection it was validated against
    title: str
    api_version: str
    document_url: str
    document_sha256: str
    signature: str  # what makes another instance compatible: title, major version, the operations' shapes
    auth: dict[str, str]  # {"type": "apiKey", "in": "header", "name": ...}; the value stays with the broker
    operations: list[Operation]
    limits: dict[str, float] = Field(default_factory=lambda: {"timeout_s": 10.0, "retries": 2.0})
    version: int = 1
    status: str = "validated"  # validated | rejected | approved | disabled
    approved_by: str | None = None
    quality: dict[str, Any] = Field(default_factory=dict[str, Any])
    provenance: dict[str, Any] = Field(default_factory=dict[str, Any])
    disable_when: list[str] = Field(
        default_factory=lambda: [
            "the document's signature changes (checked at each survey)",
            "an oracle re-run fails",
            "a person disables it",
        ]
    )
    created_at: datetime = Field(default_factory=utc_now)

    def op(self, op_id: str) -> Operation:
        found = next((o for o in self.operations if o.id == op_id), None)
        if found is None:
            raise Unavailable(f"{self.id} has no operation {op_id}")
        return found


def _resolve(document: dict[str, Any], schema: Any) -> Any:
    """Inline local `$ref`s so each schema stands alone."""
    if isinstance(schema, dict):
        if "$ref" in schema and str(schema["$ref"]).startswith("#/"):
            target: Any = document
            for part in str(schema["$ref"])[2:].split("/"):
                target = target[part]
            return _resolve(document, target)
        return {k: _resolve(document, v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve(document, v) for v in schema]
    return schema


def _scope(path: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{") and not re.fullmatch(r"v\d+", p)]
    return parts[0] if parts else "root"


def documented(document: dict[str, Any]) -> list[Operation]:
    """Every operation the document declares, typed from it."""
    found = []
    for path, item in (document.get("paths") or {}).items():
        for method in METHODS:
            spec = item.get(method)
            if not isinstance(spec, dict):
                continue
            body = (((spec.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")
            responses = {
                code: _resolve(document, ((r.get("content") or {}).get("application/json") or {}).get("schema"))
                for code, r in (spec.get("responses") or {}).items()
            }
            found.append(
                Operation(
                    id=spec.get("operationId") or f"{method} {path}",
                    method=method.upper(),
                    path=path,
                    summary=spec.get("summary", ""),
                    effect="read" if method == "get" else "write",
                    scope=_scope(path),
                    parameters=[_resolve(document, p) for p in spec.get("parameters") or []],
                    body_schema=_resolve(document, body) if body else None,
                    responses=responses,
                )
            )
    return found


def signature(document: dict[str, Any], operations: list[Operation]) -> str:
    info = document.get("info") or {}
    shapes = sorted(
        (o.method, o.path, json.dumps(o.responses, sort_keys=True), json.dumps(o.body_schema, sort_keys=True))
        for o in operations
    )
    major = str(info.get("version", "0")).split(".")[0]
    return hashlib.sha256(json.dumps([info.get("title"), major, shapes]).encode()).hexdigest()[:16]


SELECTION_SCHEMA = {
    "type": "object",
    "required": ["operations"],
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "use", "why"],
                "properties": {"id": {"type": "string"}, "use": {"enum": ["read", "write"]}, "why": {"type": "string"}},
            },
        }
    },
}


def selection_prompt(goals: str, permissions: list[str], operations: list[Operation]) -> dict[str, str]:
    listing = "\n".join(
        f"- {o.id}: {o.method} {o.path} — {o.summary} (parameters: "
        f"{', '.join(p.get('name', '?') for p in o.parameters) or 'none'}{'; body' if o.body_schema else ''})"
        for o in operations
    )
    return {
        "goals": goals,
        "permissions": ", ".join(permissions),
        "operations": listing,
        "schema": json.dumps(SELECTION_SCHEMA),
    }


def choose(
    answer: dict[str, Any], operations: list[Operation], grant: ConnectionGrant
) -> tuple[list[Operation], list[str]]:
    """The model's choice, checked: documented ids only; a write only where the grant allows its scope, and only
    with the operation that undoes it (a DELETE on the written resource) when the document has one."""
    by_id = {o.id: o for o in operations}
    notes: list[str] = []
    chosen: dict[str, Operation] = {}
    for pick in answer.get("operations") or []:
        op = by_id.get(str(pick.get("id")))
        if op is None:
            notes.append(f"ignored {pick.get('id')!r}: not in the document")
            continue
        if op.effect == "write" and f"write:{op.scope}" not in grant.permissions and "write" not in grant.permissions:
            notes.append(f"ignored {op.id}: the grant does not allow writing {op.scope}")
            continue
        chosen[op.id] = op.model_copy(update={"why": str(pick.get("why", ""))[:200]})
    for op in list(chosen.values()):
        if op.effect == "write" and op.method == "POST":
            undo = next((o for o in operations if o.method == "DELETE" and o.path.startswith(op.path + "/{")), None)
            if undo is not None:
                chosen.setdefault(undo.id, undo.model_copy(update={"why": f"undoes {op.id}"}))
                chosen[op.id] = chosen[op.id].model_copy(update={"undo": undo.id})
    return list(chosen.values()), notes


# The executor -----------------------------------------------------------------------------------------------------


class CallFailed(RuntimeError):
    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status


def _headers(integration: ApiIntegration, grant: ConnectionGrant, *, with_key: bool = True) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "unbidden"}
    if with_key and integration.auth.get("in") == "header":
        key = broker().get(grant.credential_ref or "", purpose(grant.id))
        if not key:
            raise Unavailable(f"{grant.credential_ref} is not held by the broker")
        headers[integration.auth["name"]] = key
    return headers


def _validate_params(op: Operation, params: dict[str, Any]) -> None:
    declared = {p["name"]: p for p in op.parameters}
    unknown = set(params) - set(declared)
    if unknown:
        raise CallFailed(None, f"{op.id} has no parameters {sorted(unknown)}")
    for name, p in declared.items():
        if name not in params:
            if p.get("required") and p.get("in") != "header":
                raise CallFailed(None, f"{op.id} needs {name}")
            continue
        jsonschema.validate(params[name], p.get("schema") or {})


def call(
    integration: ApiIntegration,
    conn: Connection,
    mandate: Mandate,
    op_id: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
    with_key: bool = True,
    transport: httpx.BaseTransport | None = None,
    gate: bool = True,
) -> tuple[int, Any]:
    """One call of one integration operation. The gate checks the connection, the checked ability, the grant and
    the policy at this moment; the request is built from the document's operation only; the response is validated
    against the document. Returns (status, body); raises `Unavailable` or `CallFailed`."""
    op = integration.op(op_id)
    if gate:
        require(conn, mandate, op.effect, op.id, f"{op.id} on {conn.id}", scope=op.scope)
    grant = next((g for g in mandate.connections if g.id == conn.grant), None)
    if grant is None:
        raise Unavailable(f"{conn.id} is not granted")
    params = dict(params or {})
    _validate_params(op, params)
    if op.body_schema is not None:
        jsonschema.validate(body, op.body_schema)
    path = op.path
    query: dict[str, Any] = {}
    headers = _headers(integration, grant, with_key=with_key)
    for p in op.parameters:
        name, where = p["name"], p.get("in")
        if where == "header" and name.lower() == "idempotency-key":
            headers[name] = idempotency_key or ""
        elif name in params and where == "path":
            path = path.replace("{" + name + "}", quote(str(params[name]), safe=""))
        elif name in params and where == "query":
            query[name] = params[name]
    url = conn.location.rstrip("/") + path
    timeout = float(integration.limits.get("timeout_s", 10.0))
    response: httpx.Response | None = None
    for attempt in range(int(integration.limits.get("retries", 2)) + 1):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                response = client.request(op.method, url, params=query, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise CallFailed(None, f"{op.id}: {exc}") from exc
        if response.status_code in (429, 503) and attempt < int(integration.limits.get("retries", 2)):
            time.sleep(min(float(response.headers.get("Retry-After", "1") or 1), 5.0))
            continue
        break
    assert response is not None
    status = response.status_code
    try:
        data: Any = response.json()
    except ValueError:
        data = response.text
    schema = op.responses.get(str(status))
    if str(status) not in op.responses:
        raise CallFailed(status, f"{op.id} answered {status}, which its document does not declare")
    if schema is not None:
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            raise CallFailed(status, f"{op.id} answered {status} outside its documented schema: {exc.message}") from exc
    if status >= 400:
        # Documented or not, an error is not data: a refused key read as an empty answer would look like nothing to do.
        raise CallFailed(status, f"{op.id} answered {status}: {str(data)[:200]}")
    return status, data


# The oracle -------------------------------------------------------------------------------------------------------


def _list_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    return []


def oracle(
    integration: ApiIntegration,
    conn: Connection,
    mandate: Mandate,
    *,
    store: Any,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Judge an integration against the live service, without a model. Returns per-operation results; an
    operation passes only on what was observed. Its writes are effects like any other: each mutating request is
    authorized immediately before it is sent (`connect/effects.py`) and recorded."""
    from unbidden.connect.effects import authorize

    results: dict[str, Any] = {}
    seen: list[dict[str, Any]] = []
    reads = [o for o in integration.operations if o.effect == "read"]
    listing = [o for o in reads if not any(p.get("in") == "path" for p in o.parameters)]
    keyed = [o for o in reads if any(p.get("in") == "path" for p in o.parameters)]

    def run(op: Operation, **kw: Any) -> tuple[int | None, Any, str | None]:
        try:
            status, data = call(integration, conn, mandate, op.id, gate=False, transport=transport, **kw)
            return status, data, None
        except (CallFailed, Unavailable, jsonschema.ValidationError) as exc:
            return getattr(exc, "status", None), None, str(exc)[:300]

    for op in listing:
        status, data, error = run(op)
        items = _list_items(data)
        pages = int(data.get("pages", 1)) if isinstance(data, dict) and isinstance(data.get("pages"), int) else 1
        if error is None and pages > 1 and any(p["name"] == "page" for p in op.parameters):
            for page in range(2, min(pages, MAX_PAGES) + 1):
                _, d2, e2 = run(op, params={"page": page})
                if e2 is not None:
                    error = f"page {page}: {e2}"
                    break
                items += _list_items(d2)
        seen += items
        anonymous = None
        try:
            anonymous = call(integration, conn, mandate, op.id, gate=False, with_key=False, transport=transport)[0]
        except CallFailed as exc:
            anonymous = exc.status
        except Unavailable:
            anonymous = None
        refused = anonymous in (401, 403)
        results[op.id] = {
            "passed": error is None and status == 200 and refused,
            "observed": f"{status}, {len(items)} records, {pages} page(s); without the key: {anonymous}",
            "error": error,
        }
    for op in keyed:
        names = [p["name"] for p in op.parameters if p.get("in") == "path"]
        sample = next((i for i in seen if all(n in i for n in names)), None)
        if sample is None:
            results[op.id] = {
                "passed": False,
                "observed": "no listed record carries its path parameters",
                "error": None,
            }
            continue
        status, data, error = run(op, params={n: sample[n] for n in names})
        agrees = isinstance(data, dict) and all(data.get(k) == v for k, v in sample.items() if k in data)
        results[op.id] = {
            "passed": error is None and status == 200 and agrees,
            "observed": f"{status}; agrees with the listed record: {agrees}",
            "error": error,
        }
    writes = [o for o in integration.operations if o.effect == "write" and o.method == "POST"]
    allowed: dict[str, bool] = {}
    for op in writes:
        ok, why = authorize(store, mandate, conn, op.scope, f"oracle probe of {op.id} on {conn.id}")
        allowed[op.id] = ok
        if not ok:
            results[op.id] = {"passed": False, "observed": f"not exercised: {why}", "error": None}
            continue
        results[op.id] = _exercise_write(integration, conn, mandate, op, seen, transport, store)
        if op.undo:
            results[op.undo] = {
                "passed": results[op.id]["passed"],
                "observed": f"undid {op.id}: {results[op.id]['observed']}",
                "error": results[op.id]["error"],
            }
    return {
        "version": ORACLE_VERSION,
        "at": utc_now().isoformat(),
        "operations": results,
        # Reads must pass; a write counts only where it was authorized to be exercised (otherwise it stays disabled).
        "passed": all(
            r["passed"]
            for k, r in results.items()
            if integration.op(k).effect == "read" or allowed.get(k) or allowed.get(_undone_by(integration, k), False)
        ),
    }


def _undone_by(integration: ApiIntegration, op_id: str) -> str:
    """The write an undo operation compensates, when it is one."""
    return next((o.id for o in integration.operations if o.undo == op_id), "")


def _exercise_write(
    integration: ApiIntegration,
    conn: Connection,
    mandate: Mandate,
    op: Operation,
    seen: list[dict[str, Any]],
    transport: httpx.BaseTransport | None,
    store: Any,
) -> dict[str, Any]:
    """Make the smallest valid write, repeat it with the same idempotency key, undo it, and observe each step."""
    schema = op.body_schema or {}
    properties = schema.get("properties") or {}
    body: dict[str, Any] = {}
    for name in schema.get("required") or []:
        prop = properties.get(name) or {}
        if prop.get("type") == "integer":
            body[name] = int(prop.get("minimum", 1))
        elif any(name in i for i in seen):
            body[name] = next(i[name] for i in seen if name in i)
        else:
            return {"passed": False, "observed": f"no value known for {name}", "error": None}
    from unbidden.connect.effects import authorize, record_effect
    from unbidden.contracts.action import ActionStatus

    key = f"unbidden-oracle-{uuid.uuid4().hex[:12]}"

    def send(operation: Operation, **kw: Any) -> tuple[int, Any]:
        """One mutating request: authorized now (revocation, kill switch, approval, budget), then recorded."""
        ok, why = authorize(store, mandate, conn, operation.scope, f"oracle probe of {operation.id}")
        if not ok:
            raise Unavailable(why)
        try:
            status, data = call(integration, conn, mandate, operation.id, gate=False, transport=transport, **kw)
        except CallFailed as exc:
            record_effect(
                store,
                conn,
                operation.id,
                kw.get("body"),
                kind="oracle_probe",
                status=ActionStatus.FAILED,
                result={"status": exc.status},
                reason=str(exc)[:200],
                key=key,
            )
            raise
        record_effect(
            store,
            conn,
            operation.id,
            kw.get("body"),
            kind="oracle_probe",
            status=ActionStatus.EXECUTED,
            result={"status": status, "body": data},
            reason=f"oracle probe of {integration.id}",
            key=key,
        )
        return status, data

    try:
        first = send(op, body=body, idempotency_key=key)
        again = send(op, body=body, idempotency_key=key)
        same = isinstance(first[1], dict) and isinstance(again[1], dict) and first[1].get("id") == again[1].get("id")
        undone = None
        if op.undo and isinstance(first[1], dict) and first[1].get("id"):
            undo = integration.op(op.undo)
            names = [p["name"] for p in undo.parameters if p.get("in") == "path"]
            undone = send(undo, params={names[0]: first[1]["id"]})
    except (CallFailed, Unavailable, jsonschema.ValidationError) as exc:
        return {"passed": False, "observed": "write failed or stopped", "error": str(exc)[:300]}
    observed = (
        f"created {first[0]}, repeated with the same key {again[0]} (same record: {same}), "
        f"undone {undone[0] if undone else 'no undo documented'}"
    )
    return {
        "passed": first[0] in (200, 201) and same and undone is not None and undone[0] == 200,
        "observed": observed,
        "error": None,
        "body": body,
    }


def abilities(integration: ApiIntegration, verdict: dict[str, Any]) -> list[Ability]:
    passed = {k for k, r in verdict["operations"].items() if r["passed"]}
    found = []
    reads = [o.id for o in integration.operations if o.effect == "read" and o.id in passed]
    if reads:
        found.append(
            Ability(
                kind="read", operations=reads, known_by=f"checked: oracle v{ORACLE_VERSION} on {integration.source}"
            )
        )
    writes = [o.id for o in integration.operations if o.effect == "write" and o.id in passed]
    if writes:
        found.append(
            Ability(
                kind="write",
                operations=writes,
                known_by="checked: written, repeated with its idempotency key and undone, each observed",
            )
        )
    return found
