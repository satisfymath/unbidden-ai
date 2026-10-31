"""One anonymous read of a documented endpoint: whether the service answers without the credential its document
declares (stage 10, codex-lb). GET only, no parameters, no body, a short timeout; nothing is sent but the request."""

from __future__ import annotations

import re

import httpx

TIMEOUT_S = 5.0


def answers_without_credential(base: str, endpoint: str, *, client: httpx.Client | None = None) -> int | None:
    """The status the endpoint ("GET /path") returns to an anonymous request, or None when it is not a plain GET
    (a method with a body, a path with parameters) or the service did not answer."""
    method, _, path = endpoint.partition(" ")
    if method.upper() != "GET" or not path.startswith("/") or re.search(r"[{}]", path):
        return None
    url = base.rstrip("/") + path
    try:
        own = client or httpx.Client(timeout=TIMEOUT_S)
        try:
            return own.get(url, headers={"Accept": "application/json"}).status_code
        finally:
            if client is None:
                own.close()
    except httpx.HTTPError:
        return None
