"""An HTTP API Unbidden has no integration for yet: what can be known without one.

The check reaches the base URL and reads the documentation the grant authorizes (an OpenAPI document), and reports
how the API authenticates. Until an integration is built and validated for it (Forge, `api_client`), the connection
is `needs_capability`: reachable, documented, and nothing Unbidden can yet read or change through it.
"""

from __future__ import annotations

from typing import Any

import httpx

from unbidden.connect.base import CheckResult, Failure
from unbidden.contracts.connection import ConnectionState
from unbidden.contracts.guardian import ConnectionGrant
from unbidden.guardian.policy import grant_host


def fetch_document(url: str, *, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=10, transport=transport) as client:
        response = client.get(url)
    response.raise_for_status()
    document = response.json()
    if not isinstance(document, dict) or "paths" not in document:
        raise ValueError(f"{url} is not an OpenAPI document")
    return document


class HttpApiConnector:
    kind = "http_api"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def validate(self, grant: ConnectionGrant) -> list[str]:
        problems = [] if grant.location.startswith(("http://", "https://")) else ["location must be a base URL"]
        if grant.docs and grant_host(grant.docs) != grant_host(grant.location):
            problems.append("its documentation must be served by the granted host")
        return problems + ([] if grant.docs else ["where its documentation may be read (docs)"])

    def check(self, grant: ConnectionGrant) -> CheckResult:
        try:
            document = fetch_document(grant.docs or "", transport=self.transport)
        except (httpx.HTTPError, ValueError) as exc:
            return CheckResult(
                ConnectionState.DEGRADED, f"documentation unreadable: {exc}", failure=Failure.UNREACHABLE
            )
        schemes = (document.get("components") or {}).get("securitySchemes") or {}
        auth = ", ".join(f"{s.get('type')} {s.get('name') or s.get('scheme') or ''}".strip() for s in schemes.values())
        title = (document.get("info") or {}).get("title", "?")
        operations = sum(len(v) for v in document["paths"].values())
        return CheckResult(
            ConnectionState.NEEDS_CAPABILITY,
            f"{title}: {operations} operations documented, authenticated by {auth or 'nothing'}; no integration yet",
            next_step="Forge builds an integration from its documentation when a task needs it",
            facts={"title": title, "version": (document.get("info") or {}).get("version"), "auth": auth},
        )
