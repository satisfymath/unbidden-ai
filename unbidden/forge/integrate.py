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
from unbidden.forge.oas_schema import UnsupportedSchema
from unbidden.guardian.policy import PolicyEngine, grant_host
from unbidden.guardian.scanner import redact_text
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
        verdict = oracle(candidate, conn, mandate, store=store, transport=transport)
        if verdict["passed"]:
            candidate.quality = verdict
            return candidate, [f"reused {existing.id} (signature {existing.signature}); the oracle passed here"]
        notes.append(
            f"{existing.id} has the same shapes but failed here: "
            + "; ".join(f"{k}: {r['observed']}" for k, r in verdict["operations"].items() if not r["passed"])
        )
    return None, notes


async def build(
    brain: Any,
    store: Store,
    mandate: Mandate,
    conn: Connection,
    transport: httpx.BaseTransport | None = None,
    purposes: list[str] | None = None,
) -> tuple[ApiIntegration | None, str, list[str]]:
    """Reuse, else build; record what was decided and why. Returns (integration or None, decision, notes).
    `purposes`: what waits for it beyond the mandate's goals (Unbidden's own questions in a proactive run, stage 9:
    with no goal stated, the model chose no read operation and the integration was never built)."""
    grant = _grant(mandate, conn)
    document = read_document(mandate, grant, transport)
    try:
        documented(document)
    except UnsupportedSchema as exc:  # a document this reader does not interpret: said, not guessed
        return None, "unsupported", [f"{conn.id}'s documentation: {exc}"]
    adopted, notes = reuse(store, mandate, conn, document, transport)
    if adopted is not None:
        _register(store, adopted, "reuse")
        return adopted, f"reuse:{adopted.provenance['reused_from']}", notes
    operations = documented(document)
    prompt = load_prompt("forge_api_client")
    stated = [f"- {g.statement} (bounds: {json.dumps(g.bounds)})" for g in mandate.goals]
    stated += [f"- {p} (asked by Unbidden itself; read-only)" for p in purposes or [] if p not in
               {g.statement for g in mandate.goals}]  # fmt: skip
    goals = "\n".join(stated) or "- (none stated)"
    request = LLMRequest(
        purpose="forge.api_client",
        tier=Tier.LOCAL,
        response_schema=SELECTION_SCHEMA,
        max_tokens=1500,
        prompt_sha256=prompt.sha256,
        messages=[
            Message(
                role="user",
                # Values that look like credentials in the documentation (an example `api_key = ...`) are masked, as
                # in a lab's prompt; Guardian still scans what is sent (stage 9, LNbits).
                content=redact_text(prompt.render(**selection_prompt(goals, grant.permissions, operations))),
                # Documentation of this connection: remote only if its grant says its content may leave.
                source="synthetic" if grant.content_may_leave else "runtime",
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
        documented=_documented(operations),
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
    verdict = oracle(integration, conn, mandate, store=store, transport=transport)
    refused = [
        k
        for k, r in verdict["operations"].items()
        if integration.op(k).effect == "read"
        and (r.get("status") in (401, 403) or str(r.get("observed", "")).startswith(("401", "403")))
    ]
    reads = [o.id for o in integration.operations if o.effect == "read"]
    if refused and len(refused) < len(reads):
        # Some reads answer with this credential and these do not: they are outside its scope (stage 9, LNbits: a
        # wallet's read key, refused by the account-wide `assets` listing, was reported as a key a person must
        # replace). They are left out, said so, and what remains is judged again; no person is asked for anything.
        notes.append(f"outside the credential's scope (refused while other reads answer): {', '.join(refused)}")
        integration = integration.model_copy(update={
            "operations": [o for o in integration.operations if o.id not in refused],
            "signature": signature(document, [o for o in integration.operations if o.id not in refused]),
        })  # fmt: skip
        verdict = oracle(integration, conn, mandate, store=store, transport=transport)
        refused = []
    if refused:
        # The service refused the credential itself: nothing is known about the document's truth, and the problem
        # is access, for a person to fix. The connection says so; the integration is not condemned.
        from unbidden.connect.registry import record

        conn.state, conn.blocked = ConnectionState.NEEDS_AUTHORIZATION, f"{', '.join(refused)} refused the credential"
        conn.next_step = f"a person checks the key stored as {grant.credential_ref}: the service refuses it"
        record(store, conn, reason=conn.blocked)
        return None, "credential_refused", [*notes, conn.blocked]
    integration.quality = verdict
    integration.status = "validated" if verdict["passed"] else "rejected"
    _register(store, integration, "built")
    failed = [
        f"{k}: {r['observed']} {r['error'] or ''}".strip() for k, r in verdict["operations"].items() if not r["passed"]
    ]
    return (integration if verdict["passed"] else None), "built" if verdict["passed"] else "rejected", [*notes, *failed]


def _documented(operations: list[Any]) -> list[dict[str, str]]:
    return [
        {"id": o.id, "method": o.method, "path": o.path, "summary": o.summary, "effect": o.effect} for o in operations
    ]


async def extend(
    store: Store, mandate: Mandate, conn: Connection, wanted: list[str], transport: httpx.BaseTransport | None = None
) -> tuple[ApiIntegration | None, str, list[str]]:
    """Add documented, permitted operations to a connection's integration, validated before they are enabled.

    The existing operations are kept and judged again; the new version is enabled only if every operation passes
    (a write only where its effect could be exercised, which needs authorization to change the service). The
    previous version stays, marked superseded, so nothing valid is lost if the extension fails. No model call: the
    operations are named by the plan and taken from the document."""
    from unbidden.forge.api_client import choose

    current = store.get(COLLECTION, conn.capability_id or "", ApiIntegration) if conn.capability_id else None
    if current is None or current.status not in ("validated", "approved"):
        return None, "blocked", [f"{conn.id} has no integration in use to extend"]
    grant = _grant(mandate, conn)
    document = read_document(mandate, grant, transport)
    try:
        operations = documented(document)
    except UnsupportedSchema as exc:
        return None, "blocked", [f"{conn.id}'s documentation: {exc}"]
    by_id = {o.id: o for o in operations}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        return None, "blocked", [f"not in the documentation of {conn.id}: {', '.join(missing)}"]
    answer = {
        "operations": [{"id": o.id, "use": o.effect, "why": "kept"} for o in current.operations]
        + [{"id": w, "use": by_id[w].effect, "why": "needed by a goal's plan"} for w in wanted]
    }
    chosen, notes = choose(answer, operations, grant)
    refused = [w for w in wanted if w not in {o.id for o in chosen}]
    if refused:
        return None, "blocked", [*notes, f"the grant {grant.id} does not allow {', '.join(refused)}"]
    extended = current.model_copy(
        update={
            "id": f"int_{hashlib.sha256((current.id + ','.join(sorted(wanted))).encode()).hexdigest()[:16]}",
            "version": current.version + 1,
            "operations": chosen,
            "documented": _documented(operations),
            "signature": signature(document, chosen),
            "status": "validated",
            "created_at": utc_now(),
            "document_sha256": hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest(),
            "provenance": {
                **current.provenance,
                "extends": current.id,
                "added": wanted,
                "extended_at": utc_now().isoformat(),
            },
        }
    )
    verdict = oracle(extended, conn, mandate, store=store, transport=transport)
    extended.quality = verdict
    new = {w: verdict["operations"].get(w, {}) for w in wanted}
    unproven = {w: r.get("observed", "not judged") for w, r in new.items() if not r.get("passed")}
    if unproven and all(str(v).startswith("not exercised") for v in unproven.values()):
        # Validating a write changes the service: without that authorization the extension waits, it is not wrong.
        return None, "blocked", [*notes, "; ".join(f"{k}: {v}" for k, v in unproven.items())]
    if unproven or not all(r["passed"] for k, r in verdict["operations"].items() if extended.op(k).effect == "read"):
        extended.status = "rejected"
        _register(store, extended, "extension")
        why = "; ".join(f"{k}: {v}" for k, v in unproven.items()) or "an existing read no longer passes"
        return None, "rejected", [*notes, why]
    current.status, current.superseded_by = "superseded", extended.id
    store.put(COLLECTION, current)
    _register(store, extended, "extension")
    return extended, f"extended:{current.id}", [*notes, f"added {', '.join(wanted)} to {current.id}"]


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
    from unbidden.forge.api_client import Degraded

    # As the oracle reads (stage 8): an accessory field that differs from the document is recorded, not fatal; one
    # that identifies, relates or counts still fails the check (stage 9: Conduit's documented-as-string nulls left
    # its validated integration unusable, every read refused as "not observed to be allowed").
    seen = Degraded()
    try:
        status, _ = call(integration, conn, mandate, listing.id, gate=False, transport=transport, degraded=seen)
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
        f"{integration.title} {integration.api_version} through {integration.id}: {listing.id} answered {status}"
        + (f" ({len(seen.log)} documented-vs-observed deviation(s) recorded)" if seen.log else ""),
        effective=effective,
        abilities=found,
    )
