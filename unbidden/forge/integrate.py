"""From a connection Unbidden cannot use yet to one it can: reuse or build an integration, judge it, enable it.

need observed → an existing integration compatible with this API's document? (reuse, judged again here) → the
authorized document read → the local model selects the operations the goals need → the integration assembled from
the document → the oracle against the live service → registered → enabled by the mandate's use gate → the
connection's checked abilities updated, its waiting work resumed (by the need, `forge/needs.py`).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from unbidden.brain.prompts import load_prompt
from unbidden.connect.base import CheckResult, Failure
from unbidden.connect.http_api import fetch_document
from unbidden.contracts.common import utc_now
from unbidden.contracts.connection import Connection, ConnectionState
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, ConnectionGrant, Mandate
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.forge.api_client import (
    COLLECTION,
    SELECTION_SCHEMA,
    ApiIntegration,
    CallFailed,
    abilities,
    call,
    choose,
    documented,
    oracle,
    selection_prompt,
    signature,
)
from unbidden.guardian.policy import PolicyEngine, grant_host
from unbidden.store import Store


class IntegrationFailed(RuntimeError):
    pass


def _grant(mandate: Mandate, conn: Connection) -> ConnectionGrant:
    grant = next((g for g in mandate.connections if g.id == conn.grant), None)
    if grant is None or not grant.docs:
        raise IntegrationFailed(f"{conn.id}: no grant with documentation to build from")
    return grant


def read_document(
    mandate: Mandate, grant: ConnectionGrant, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    """The documentation the grant authorizes, read through the policy (a read of a granted host)."""
    verdict = PolicyEngine(mandate).evaluate(
        ActionRequest(
            capability="connection.read",
            purpose=f"read the documentation of {grant.id}",
            destinations=[grant_host(grant.docs or "")],
        )
    )
    if not verdict.allowed:
        raise IntegrationFailed("; ".join(verdict.reasons))
    return fetch_document(grant.docs or "", transport=transport)


def _auth(document: dict[str, Any]) -> dict[str, str]:
    schemes = (document.get("components") or {}).get("securitySchemes") or {}
    for scheme in schemes.values():
        if scheme.get("type") == "apiKey":
            return {"type": "apiKey", "in": str(scheme.get("in")), "name": str(scheme.get("name"))}
    return {"type": "none"}


def reuse(
    store: Store,
    mandate: Mandate,
    conn: Connection,
    document: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> tuple[ApiIntegration | None, list[str]]:
    """A validated integration of another instance whose operations have the same shapes in this document,
    judged again on this connection. No model call."""
    notes = []
    here = {o.id: o for o in documented(document)}
    for existing in sorted(store.list(COLLECTION, ApiIntegration), key=lambda i: i.created_at, reverse=True):
        if existing.status != "validated" or existing.source == conn.id:
            continue
        same = [here[o.id] for o in existing.operations if o.id in here]
        if len(same) != len(existing.operations) or signature(document, same) != existing.signature:
            continue
        candidate = existing.model_copy(
            update={
                "id": f"int_{hashlib.sha256((existing.id + conn.id).encode()).hexdigest()[:16]}",
                "source": conn.id,
                "document_sha256": hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest(),
                "provenance": {**existing.provenance, "reused_from": existing.id, "reused_at": utc_now().isoformat()},
                "created_at": utc_now(),
            }
        )
        verdict = oracle(candidate, conn, mandate, transport=transport)
        if verdict["passed"]:
            candidate.quality = verdict
            return candidate, [f"reused {existing.id} (signature {existing.signature}); the oracle passed here"]
        notes.append(
            f"{existing.id} has the same shapes but failed here: "
            + "; ".join(f"{k}: {r['observed']}" for k, r in verdict["operations"].items() if not r["passed"])
        )
    return None, notes


async def build(
    brain: Any, store: Store, mandate: Mandate, conn: Connection, transport: httpx.BaseTransport | None = None
) -> tuple[ApiIntegration | None, str, list[str]]:
    """Reuse, else build; record what was decided and why. Returns (integration or None, decision, notes)."""
    grant = _grant(mandate, conn)
    document = read_document(mandate, grant, transport)
    adopted, notes = reuse(store, mandate, conn, document, transport)
    if adopted is not None:
        _register(store, adopted, "reuse")
        return adopted, f"reuse:{adopted.provenance['reused_from']}", notes
    operations = documented(document)
    prompt = load_prompt("forge_api_client")
    goals = "\n".join(f"- {g.statement} (bounds: {json.dumps(g.bounds)})" for g in mandate.goals) or "- (none stated)"
    request = LLMRequest(
        purpose="forge.api_client",
        tier=Tier.LOCAL,
        response_schema=SELECTION_SCHEMA,
        max_tokens=1500,
        prompt_sha256=prompt.sha256,
        messages=[
            Message(
                role="user",
                content=prompt.render(**selection_prompt(goals, grant.permissions, operations)),
                source="runtime",
            )
        ],
    )
    response = await brain.complete(request)
    try:
        answer = json.loads(response.content)
    except json.JSONDecodeError:
        return None, "failed", [*notes, "the model's answer was not JSON"]
    chosen, choice_notes = choose(answer, operations, grant)
    notes += choice_notes
    if not any(o.effect == "read" for o in chosen):
        return None, "failed", [*notes, "no documented read operation was chosen"]
    info = document.get("info") or {}
    integration = ApiIntegration(
        source=conn.id,
        title=str(info.get("title", "?")),
        api_version=str(info.get("version", "?")),
        document_url=grant.docs or "",
        document_sha256=hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest(),
        signature=signature(document, chosen),
        auth=_auth(document),
        operations=chosen,
        provenance={
            "model": getattr(response, "model", None),
            "prompt_sha256": prompt.sha256,
            "document": grant.docs,
            "built_at": utc_now().isoformat(),
            "goals": [g.id for g in mandate.goals],
        },
    )
    verdict = oracle(integration, conn, mandate, transport=transport)
    integration.quality = verdict
    integration.status = "validated" if verdict["passed"] else "rejected"
    _register(store, integration, "built")
    failed = [
        f"{k}: {r['observed']} {r['error'] or ''}".strip() for k, r in verdict["operations"].items() if not r["passed"]
    ]
    return (integration if verdict["passed"] else None), "built" if verdict["passed"] else "rejected", [*notes, *failed]


def _register(store: Store, integration: ApiIntegration, how: str) -> None:
    store.put(COLLECTION, integration)
    store.append_event(
        Event(
            type=EventType.CAPABILITY_BUILT,
            actor="forge",
            entity_id=integration.id,
            payload={
                "kind": "api_client",
                "how": how,
                "source": integration.source,
                "status": integration.status,
                "operations": [o.id for o in integration.operations],
            },
        )
    )


def live_check(
    integration: ApiIntegration, conn: Connection, mandate: Mandate, transport: httpx.BaseTransport | None = None
) -> CheckResult:
    """An integrated connection's check: an authenticated read through the integration, now."""
    listing = next(
        (
            o
            for o in integration.operations
            if o.effect == "read" and not any(p.get("in") == "path" for p in o.parameters)
        ),
        None,
    )
    if listing is None:
        return CheckResult(ConnectionState.DEGRADED, "the integration has no parameterless read to check with")
    try:
        status, _ = call(integration, conn, mandate, listing.id, gate=False, transport=transport)
    except CallFailed as exc:
        if exc.status in (401, 403):
            return CheckResult(
                ConnectionState.NEEDS_AUTHORIZATION,
                f"{listing.id} refused the key ({exc.status})",
                failure=Failure.AUTH,
                next_step=f"a person renews the key stored as {conn.credential_ref}",
            )
        return CheckResult(ConnectionState.DEGRADED, str(exc), failure=Failure.UNREACHABLE)
    except Exception as exc:  # the broker or the network
        return CheckResult(ConnectionState.NEEDS_AUTHORIZATION, str(exc), failure=Failure.AUTH)
    verdict = integration.quality
    found = abilities(integration, verdict)
    effective = ["read"] + (["write"] if any(a.kind == "write" for a in found) else [])
    return CheckResult(
        ConnectionState.CONNECTED,
        f"{integration.title} {integration.api_version} through {integration.id}: {listing.id} answered {status}",
        effective=effective,
        abilities=found,
    )
