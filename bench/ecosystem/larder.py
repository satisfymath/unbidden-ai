"""Larder: the stage 5 evaluation service for question A (an API never seen in development). Real HTTP when run;
the same handler in-process for tests. Written and frozen before the evaluation ran.

    python larder.py <port> <data dir>          (data dir: `tokens`, `items.json`)

Cursor pagination (`cursor`, `page_size` up to 10, `next_cursor` until the last page); an `X-Api-Token` header;
transfers created with an `Idempotency-Key` (a repeat returns the same transfer and applies nothing) and cancelled
with a documented DELETE that reverts them. Tokens and faults are read at every request.

Faults (stage 6, added after the evaluation for development regressions; `faults`, one per line):
- `bad_page`: the second page carries an item whose `on_hand` is not an integer (outside the document);
- `timeout_after_write`: the first transfer of 2 or more units is applied, then its answer never comes (the oracle's
  own probes move 1 unit, so the fault reaches an action, not the probe);
- `undo_noop`: a cancel answers 200 and reverts nothing.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

PAGE, MAX_QTY = 10, 30
ITEM = {
    "type": "object",
    "required": ["code", "shelf", "on_hand", "allocated", "inbound"],
    "properties": {
        "code": {"type": "string", "description": "the item's code"},
        "shelf": {"type": "string"},
        "on_hand": {"type": "integer"},
        "allocated": {"type": "integer", "description": "promised to scheduled hampers"},
        "inbound": {"type": "integer", "description": "units on their way from transfers"},
    },
}
TRANSFER = {
    "type": "object",
    "required": ["transfer_id", "code", "quantity", "status"],
    "properties": {
        "transfer_id": {"type": "string"},
        "code": {"type": "string"},
        "quantity": {"type": "integer"},
        "status": {"type": "string", "enum": ["requested", "cancelled"]},
    },
}
ERROR = {"type": "object", "properties": {"message": {"type": "string"}}}


def document() -> dict[str, Any]:
    def err(d: str) -> dict[str, Any]:
        return {"description": d, "content": {"application/json": {"schema": ERROR}}}

    return {
        "openapi": "3.0.3",
        "info": {"title": "Larder", "version": "2.1.0", "description": "Stock of a food bank's pantry items"},
        "components": {"securitySchemes": {"token": {"type": "apiKey", "in": "header", "name": "X-Api-Token"}}},
        "security": [{"token": []}],
        "paths": {
            "/api/v2/items": {
                "get": {
                    "operationId": "listItems",
                    "summary": "Pantry items and their stock, one page at a time",
                    "parameters": [
                        {"name": "cursor", "in": "query", "schema": {"type": "string"}},
                        {
                            "name": "page_size",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": PAGE},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "a page of items",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["data"],
                                        "properties": {
                                            "data": {"type": "array", "items": ITEM},
                                            "next_cursor": {"type": "string", "nullable": True},
                                        },
                                    }
                                }
                            },
                        },
                        "401": err("missing or unknown token"),
                    },
                }
            },
            "/api/v2/shelves": {
                "get": {
                    "operationId": "listShelves",
                    "summary": "Shelf names",
                    "responses": {
                        "200": {
                            "description": "shelves",
                            "content": {"application/json": {"schema": {"type": "array", "items": {"type": "string"}}}},
                        },
                        "401": err("missing or unknown token"),
                    },
                }
            },
            "/api/v2/transfers": {
                "post": {
                    "operationId": "requestTransfer",
                    "summary": "Request a transfer of units into an item's stock",
                    "description": "Adds the quantity to the item's `inbound`. Idempotent per Idempotency-Key. "
                    "Cancel with DELETE /api/v2/transfers/{transfer_id}.",
                    "parameters": [
                        {"name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string"}}
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["code", "quantity"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "code": {"type": "string"},
                                        "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_QTY},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "requested", "content": {"application/json": {"schema": TRANSFER}}},
                        "200": {
                            "description": "already requested with this key",
                            "content": {"application/json": {"schema": TRANSFER}},
                        },
                        "401": err("missing or unknown token"),
                        "404": err("no such item"),
                        "422": err("invalid"),
                    },
                }
            },
            "/api/v2/transfers/{transfer_id}": {
                "delete": {
                    "operationId": "cancelTransfer",
                    "summary": "Cancel a transfer",
                    "parameters": [
                        {"name": "transfer_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {"description": "cancelled", "content": {"application/json": {"schema": TRANSFER}}},
                        "401": err("missing or unknown token"),
                        "404": err("no such transfer"),
                    },
                }
            },
        },
    }


class Larder:
    def __init__(self, tokens: set[str], items: list[dict[str, Any]], faults: set[str] | None = None) -> None:
        self.tokens, self.faults, self.timed_out = tokens, faults or set(), False
        self.items = {i["code"]: dict(i) for i in items}
        self.transfers: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, str] = {}
        self.lock = threading.Lock()

    def handle(self, method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, Any]:
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        if path == "/openapi.json":
            return 200, document()
        lowered = {k.lower(): v for k, v in headers.items()}
        if lowered.get("x-api-token") not in self.tokens:
            return 401, {"message": "missing or unknown token"}
        with self.lock:
            if method == "GET" and path == "/api/v2/items":
                size = min(int(query.get("page_size", [str(PAGE)])[0]), PAGE)
                cursor = query.get("cursor", [""])[0]
                start = int(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else 0
                codes = sorted(self.items)
                batch = codes[start : start + size]
                following = start + size
                more = following < len(codes)
                token = base64.urlsafe_b64encode(str(following).encode()).decode() if more else None
                data = [dict(self.items[c]) for c in batch]
                if "bad_page" in self.faults and start > 0 and data:
                    data[0]["on_hand"] = "many"
                return 200, {"data": data, "next_cursor": token}
            if method == "GET" and path == "/api/v2/shelves":
                return 200, sorted({i["shelf"] for i in self.items.values()})
            if method == "POST" and path == "/api/v2/transfers":
                key = lowered.get("idempotency-key") or ""
                data = json.loads(body or b"{}")
                if key and key in self.by_key:
                    return 200, dict(self.transfers[self.by_key[key]])
                qty, code = data.get("quantity"), data.get("code")
                if not isinstance(qty, int) or not 1 <= qty <= MAX_QTY or set(data) - {"code", "quantity"}:
                    return 422, {"message": "invalid"}
                if code not in self.items:
                    return 404, {"message": "no such item"}
                transfer = {"transfer_id": f"tr_{uuid.uuid4().hex[:10]}", "code": code, "quantity": qty,
                            "status": "requested"}  # fmt: skip
                self.transfers[transfer["transfer_id"]] = transfer
                if key:
                    self.by_key[key] = transfer["transfer_id"]
                self.items[code]["inbound"] += qty
                if "timeout_after_write" in self.faults and qty >= 2 and not self.timed_out:
                    self.timed_out = True
                    return 201, {**transfer, "_timeout": True}
                return 201, dict(transfer)
            if method == "DELETE" and path.startswith("/api/v2/transfers/"):
                transfer = self.transfers.get(path.rsplit("/", 1)[-1])
                if transfer is None:
                    return 404, {"message": "no such transfer"}
                if transfer["status"] == "requested" and "undo_noop" not in self.faults:
                    self.items[transfer["code"]]["inbound"] -= transfer["quantity"]
                transfer["status"] = "cancelled"
                return 200, dict(transfer)
        return 404, {"message": "no such path"}


def transport(larder: Larder) -> Any:
    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        status, body = larder.handle(request.method, str(request.url), dict(request.headers), request.content)
        if isinstance(body, dict) and body.pop("_timeout", False):
            raise httpx.ReadTimeout("the answer never came", request=request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def main() -> None:
    port, home = int(sys.argv[1]), Path(sys.argv[2])
    larder = Larder(set((home / "tokens").read_text().split()), json.loads((home / "items.json").read_text()))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            sys.stdout.write(f"{self.command} {self.path}\n")

        def _serve(self) -> None:
            larder.tokens = set((home / "tokens").read_text().split())
            larder.faults = set((home / "faults").read_text().split()) if (home / "faults").exists() else set()
            length = int(self.headers.get("Content-Length") or 0)
            status, body = larder.handle(self.command, self.path, dict(self.headers), self.rfile.read(length))
            if isinstance(body, dict) and body.pop("_timeout", False):
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
