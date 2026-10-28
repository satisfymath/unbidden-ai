"""Depot: a development fixture service for stage 4 (not Dispatch). Real HTTP when run, and the same handler
in-process for tests. Offset/limit/total pagination; restocks with an `Idempotency-Key` and a documented cancel.

    python depot.py <port> <data dir>          (data dir: `keys`, `faults`, `state.json`)

`faults` (one per line) makes it misbehave in ways a client must not be fooled by:
- `skip_page`: the second batch skips ahead (the total stays true);
- `repeat_page`: the second batch repeats the first;
- `short_total`: the declared total is smaller than the collection;
- `hide_page`: a batch is never served and the declared total agrees with what is served: a reader that trusts
  the service is fooled; only a second read with another page size shows it;
- `no_effect`: a restock answers 201 and changes nothing;
- `wrong_field`: a restock changes `reserved` instead of `incoming`;
- `undo_noop`: a cancel answers 200 and reverts nothing;
- `duplicate_on_repeat`: a repeated key returns the same restock and applies it again;
- `timeout_after_write`: the first restock is applied, then the answer never comes.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

MAX_LIMIT, MAX_UNITS = 4, 40
BIN = {
    "type": "object",
    "required": ["bin", "quantity", "reserved", "incoming"],
    "properties": {
        "bin": {"type": "string"},
        "quantity": {"type": "integer"},
        "reserved": {"type": "integer"},
        "incoming": {"type": "integer"},
    },
}
RESTOCK = {
    "type": "object",
    "required": ["restock_id", "bin", "units", "state"],
    "properties": {
        "restock_id": {"type": "string"},
        "bin": {"type": "string"},
        "units": {"type": "integer"},
        "state": {"type": "string", "enum": ["open", "cancelled"]},
    },
}
ERR = {"type": "object", "properties": {"detail": {"type": "string"}}}


def document() -> dict[str, Any]:
    def err(d: str) -> dict[str, Any]:
        return {"description": d, "content": {"application/json": {"schema": ERR}}}

    return {
        "openapi": "3.0.3",
        "info": {"title": "Depot", "version": "1.4.0"},
        "components": {"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Depot-Key"}}},
        "paths": {
            "/v1/bins": {
                "get": {
                    "operationId": "listBins",
                    "summary": "Bins and their stock, a batch at a time",
                    "parameters": [
                        {"name": "offset", "in": "query", "schema": {"type": "integer"}},
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "bins",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["bins", "total"],
                                        "properties": {
                                            "bins": {"type": "array", "items": BIN},
                                            "total": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        },
                        "401": err("bad key"),
                    },
                }
            },
            "/v1/restocks": {
                "post": {
                    "operationId": "requestRestock",
                    "summary": "Ask for units to be restocked",
                    "description": "Adds the units to the bin's `incoming`. Cancel with "
                    "DELETE /v1/restocks/{restock_id}.",
                    "parameters": [
                        {"name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string"}}
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["bin", "units"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "bin": {"type": "string"},
                                        "units": {"type": "integer", "minimum": 1, "maximum": MAX_UNITS},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "requested", "content": {"application/json": {"schema": RESTOCK}}},
                        "200": {
                            "description": "already requested with this key",
                            "content": {"application/json": {"schema": RESTOCK}},
                        },
                        "401": err("bad key"),
                        "404": err("no such bin"),
                        "422": err("invalid"),
                    },
                }
            },
            "/v1/restocks/{restock_id}": {
                "delete": {
                    "operationId": "cancelRestock",
                    "summary": "Cancel a restock",
                    "parameters": [
                        {"name": "restock_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {"description": "cancelled", "content": {"application/json": {"schema": RESTOCK}}},
                        "401": err("bad key"),
                        "404": err("no such restock"),
                    },
                }
            },
        },
    }


class Depot:
    """The service's state and behaviour, independent of how requests arrive."""

    def __init__(self, keys: set[str], faults: set[str] | None = None, bins: int = 11) -> None:
        self.keys, self.faults = keys, faults or set()
        self.bins = {
            f"B{i:02d}": {"bin": f"B{i:02d}", "quantity": (i * 7) % 23, "reserved": i % 3, "incoming": 0}
            for i in range(1, bins + 1)
        }
        self.restocks: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, str] = {}
        self.lock = threading.Lock()
        self.timed_out_once = False

    def handle(self, method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, Any, str | None]:
        """(status, body, special) where special is "timeout" when the answer must never arrive."""
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        if path == "/openapi.json":
            return 200, document(), None
        if {k.lower(): v for k, v in headers.items()}.get("x-depot-key") not in self.keys:
            return 401, {"detail": "bad key"}, None
        with self.lock:
            if method == "GET" and path == "/v1/bins":
                offset = int(query.get("offset", ["0"])[0])
                limit = min(int(query.get("limit", [str(MAX_LIMIT)])[0]), MAX_LIMIT)
                ordered = sorted(self.bins)
                start = offset
                if "skip_page" in self.faults and offset == limit:
                    start = offset + limit
                if "repeat_page" in self.faults and offset == limit:
                    start = 0
                if "hide_page" in self.faults and offset >= limit:
                    start = offset + limit  # one batch never served, and the total below agrees with what is served
                total = len(ordered) - (2 if "short_total" in self.faults else 0)
                if "hide_page" in self.faults:
                    total = len(ordered) - min(limit, max(0, len(ordered) - limit))
                return 200, {"bins": [dict(self.bins[b]) for b in ordered[start : start + limit]], "total": total}, None
            if method == "POST" and path == "/v1/restocks":
                key = {k.lower(): v for k, v in headers.items()}.get("idempotency-key") or ""
                data = json.loads(body or b"{}")
                if key in self.by_key:
                    restock = self.restocks[self.by_key[key]]
                    if "duplicate_on_repeat" in self.faults:
                        self._apply(restock["bin"], restock["units"])
                    return 200, dict(restock), None
                units, name = data.get("units"), data.get("bin")
                if not isinstance(units, int) or not 1 <= units <= MAX_UNITS or set(data) - {"bin", "units"}:
                    return 422, {"detail": "invalid"}, None
                if name not in self.bins:
                    return 404, {"detail": "no such bin"}, None
                restock = {"restock_id": f"rs-{uuid.uuid4().hex[:8]}", "bin": name, "units": units, "state": "open"}
                self.restocks[restock["restock_id"]] = restock
                self.by_key[key] = restock["restock_id"]
                if "no_effect" not in self.faults:
                    self._apply(name, units)
                if "timeout_after_write" in self.faults and not self.timed_out_once:
                    self.timed_out_once = True
                    return 201, dict(restock), "timeout"
                return 201, dict(restock), None
            if method == "DELETE" and path.startswith("/v1/restocks/"):
                restock = self.restocks.get(path.rsplit("/", 1)[-1])
                if restock is None:
                    return 404, {"detail": "no such restock"}, None
                if restock["state"] == "open" and "undo_noop" not in self.faults:
                    self._apply(restock["bin"], -restock["units"])
                restock["state"] = "cancelled"
                return 200, dict(restock), None
        return 404, {"detail": "no such path"}, None

    def _apply(self, name: str, units: int) -> None:
        field = "reserved" if "wrong_field" in self.faults else "incoming"
        self.bins[name][field] += units


def transport(depot: Depot) -> Any:
    """The same service in-process, for tests: an httpx transport. A "timeout" answer raises a read timeout."""
    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        status, body, special = depot.handle(request.method, str(request.url), dict(request.headers), request.content)
        if special == "timeout":
            raise httpx.ReadTimeout("the answer never came", request=request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def main() -> None:
    port, home = int(sys.argv[1]), Path(sys.argv[2])
    keys = set((home / "keys").read_text().split())
    faults = set((home / "faults").read_text().split()) if (home / "faults").exists() else set()
    depot = Depot(keys, faults)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            sys.stdout.write(f"{self.command} {self.path}\n")

        def _serve(self) -> None:
            # Keys and faults are read on every request, so a revocation or a fault takes effect without a restart
            # (a restart would lose the restocks already made).
            depot.keys = set((home / "keys").read_text().split())
            depot.faults = set((home / "faults").read_text().split()) if (home / "faults").exists() else set()
            length = int(self.headers.get("Content-Length") or 0)
            status, body, special = depot.handle(self.command, self.path, dict(self.headers), self.rfile.read(length))
            if special == "timeout":
                time.sleep(60)
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_DELETE = _serve

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
