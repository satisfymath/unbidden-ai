"""Stockroom: a warehouse service for the ecosystem lab. Real HTTP, standard library only, run in a container.

    python stockroom.py <port> <data dir>      (the lab starts it; Unbidden is never told how it works)

It is what Unbidden has no connector for: it learns it from `GET /openapi.json`, the documentation the mandate
authorizes. Behaviour: API key in `X-Stockroom-Key` (keys read from `<data>/keys` on every request, so a key can be
revoked while it runs); items paginated; reorders created with a required `Idempotency-Key` (the same key returns the
same reorder), bounded units, cancelled by `DELETE` (the documented compensation); `<data>/flaky` lists SKUs whose
item reads fail with 503 and `Retry-After` (a partial failure). State lives in `<data>/state.json`.
"""

from __future__ import annotations

import json
import random
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_UNITS = 50
PAGE = 15
LOCK = threading.Lock()

ITEM = {
    "type": "object",
    "required": ["sku", "on_hand", "reserved", "reorder_point"],
    "properties": {
        "sku": {"type": "string"},
        "on_hand": {"type": "integer", "minimum": 0},
        "reserved": {"type": "integer", "minimum": 0},
        "reorder_point": {"type": "integer", "minimum": 0},
        "incoming": {"type": "integer", "minimum": 0, "description": "units in pending reorders"},
    },
}
REORDER = {
    "type": "object",
    "required": ["id", "sku", "units", "status"],
    "properties": {
        "id": {"type": "string"},
        "sku": {"type": "string"},
        "units": {"type": "integer", "minimum": 1, "maximum": MAX_UNITS},
        "status": {"type": "string", "enum": ["pending", "cancelled"]},
    },
}
ERROR = {"type": "object", "required": ["error"], "properties": {"error": {"type": "string"}}}


def document(warehouse: str) -> dict[str, object]:
    def err(description: str) -> dict[str, object]:
        return {"description": description, "content": {"application/json": {"schema": ERROR}}}

    sku = {"name": "sku", "in": "path", "required": True, "schema": {"type": "string", "pattern": "^SKU-[0-9]{3}$"}}
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Stockroom",
            "version": "2.1.0",
            "description": f"Warehouse {warehouse}: stock and reorders.",
        },
        "servers": [{"url": "/"}],
        "components": {
            "securitySchemes": {"stockroomKey": {"type": "apiKey", "in": "header", "name": "X-Stockroom-Key"}},
            "schemas": {"Item": ITEM, "Reorder": REORDER, "Error": ERROR},
        },
        "security": [{"stockroomKey": []}],
        "paths": {
            "/v1/items": {
                "get": {
                    "operationId": "listItems",
                    "summary": "Stock of every item, a page at a time",
                    "parameters": [{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}}],
                    "responses": {
                        "200": {
                            "description": "a page",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["items", "page", "pages"],
                                        "properties": {
                                            "items": {"type": "array", "items": ITEM},
                                            "page": {"type": "integer"},
                                            "pages": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        },
                        "401": err("missing or unknown key"),
                    },
                }
            },
            "/v1/items/{sku}": {
                "get": {
                    "operationId": "getItem",
                    "summary": "Stock of one item",
                    "parameters": [sku],
                    "responses": {
                        "200": {"description": "the item", "content": {"application/json": {"schema": ITEM}}},
                        "401": err("missing or unknown key"),
                        "404": err("no such item"),
                        "503": err("temporarily unavailable; retry after the Retry-After seconds"),
                    },
                }
            },
            "/v1/reorders": {
                "get": {
                    "operationId": "listReorders",
                    "summary": "Reorders placed with this warehouse",
                    "responses": {
                        "200": {
                            "description": "reorders",
                            "content": {"application/json": {"schema": {"type": "array", "items": REORDER}}},
                        },
                        "401": err("missing or unknown key"),
                    },
                },
                "post": {
                    "operationId": "createReorder",
                    "summary": "Ask the warehouse to restock an item",
                    "description": f"At most {MAX_UNITS} units. The same Idempotency-Key returns the reorder it "
                    "created first. Cancel with DELETE /v1/reorders/{id}.",
                    "parameters": [
                        {
                            "name": "Idempotency-Key",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string", "minLength": 8},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["sku", "units"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "sku": {"type": "string"},
                                        "units": {"type": "integer", "minimum": 1, "maximum": MAX_UNITS},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {"description": "created", "content": {"application/json": {"schema": REORDER}}},
                        "200": {
                            "description": "already created with this key",
                            "content": {"application/json": {"schema": REORDER}},
                        },
                        "401": err("missing or unknown key"),
                        "404": err("no such item"),
                        "422": err("units out of bounds"),
                    },
                },
            },
            "/v1/reorders/{id}": {
                "delete": {
                    "operationId": "cancelReorder",
                    "summary": "Cancel a pending reorder",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "cancelled", "content": {"application/json": {"schema": REORDER}}},
                        "401": err("missing or unknown key"),
                        "404": err("no such reorder"),
                    },
                }
            },
        },
    }


class State:
    def __init__(self, data: Path, warehouse: str) -> None:
        self.data, self.warehouse = data, warehouse
        path = data / "state.json"
        if path.exists():
            saved = json.loads(path.read_text())
            self.items, self.reorders, self.keys = saved["items"], saved["reorders"], saved["idempotency"]
        else:
            rng = random.Random(f"stockroom-{warehouse}")
            self.items = {
                f"SKU-{i:03d}": {
                    "sku": f"SKU-{i:03d}",
                    "on_hand": rng.choice([0, 3, 8, 15, 30, 60, 120]),
                    "reserved": rng.choice([0, 0, 1, 2]),
                    "reorder_point": rng.choice([5, 10, 20]),
                }
                for i in range(1, 41)
            }
            self.reorders, self.keys = {}, {}
            self.save()

    def save(self) -> None:
        (self.data / "state.json").write_text(
            json.dumps({"items": self.items, "reorders": self.reorders, "idempotency": self.keys})
        )

    def item(self, sku: str) -> dict[str, object]:
        incoming = sum(r["units"] for r in self.reorders.values() if r["sku"] == sku and r["status"] == "pending")
        return {**self.items[sku], "incoming": incoming}


def handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            sys.stdout.write(f"{self.command} {self.path}\n")
            sys.stdout.flush()

        def reply(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def authorized(self) -> bool:
            keys = {k.strip() for k in (state.data / "keys").read_text().split() if k.strip()}
            if self.headers.get("X-Stockroom-Key") in keys:
                return True
            self.reply(401, {"error": "missing or unknown key"})
            return False

        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            if path == "/openapi.json":
                return self.reply(200, document(state.warehouse))
            if not self.authorized():
                return None
            with LOCK:
                if path == "/v1/items":
                    match = re.search(r"page=(\d+)", query)
                    page = max(1, int(match.group(1))) if match else 1
                    skus = sorted(state.items)
                    pages = (len(skus) + PAGE - 1) // PAGE
                    chunk = [state.item(s) for s in skus[(page - 1) * PAGE : page * PAGE]]
                    return self.reply(200, {"items": chunk, "page": page, "pages": pages})
                if found := re.fullmatch(r"/v1/items/(SKU-\d{3})", path):
                    sku = found.group(1)
                    flaky = (state.data / "flaky").read_text().split() if (state.data / "flaky").exists() else []
                    if sku in flaky:
                        return self.reply(503, {"error": "temporarily unavailable"}, {"Retry-After": "1"})
                    if sku not in state.items:
                        return self.reply(404, {"error": "no such item"})
                    return self.reply(200, state.item(sku))
                if path == "/v1/reorders":
                    return self.reply(200, list(state.reorders.values()))
            return self.reply(404, {"error": "no such path"})

        def do_POST(self) -> None:
            if self.path != "/v1/reorders" or not self.authorized():
                return None if self.path == "/v1/reorders" else self.reply(404, {"error": "no such path"})
            key = self.headers.get("Idempotency-Key") or ""
            if len(key) < 8:
                return self.reply(422, {"error": "an Idempotency-Key of at least 8 characters is required"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except json.JSONDecodeError:
                return self.reply(422, {"error": "body is not JSON"})
            with LOCK:
                if key in state.keys:
                    return self.reply(200, state.reorders[state.keys[key]])
                sku, units = body.get("sku"), body.get("units")
                if set(body) - {"sku", "units"} or not isinstance(units, int) or not 1 <= units <= MAX_UNITS:
                    return self.reply(422, {"error": f"units must be an integer from 1 to {MAX_UNITS}"})
                if sku not in state.items:
                    return self.reply(404, {"error": "no such item"})
                reorder = {"id": f"ro_{uuid.uuid4().hex[:10]}", "sku": sku, "units": units, "status": "pending"}
                state.reorders[reorder["id"]] = reorder
                state.keys[key] = reorder["id"]
                state.save()
            return self.reply(201, reorder)

        def do_DELETE(self) -> None:
            found = re.fullmatch(r"/v1/reorders/([\w-]+)", self.path)
            if not found or not self.authorized():
                return None if found else self.reply(404, {"error": "no such path"})
            with LOCK:
                reorder = state.reorders.get(found.group(1))
                if reorder is None:
                    return self.reply(404, {"error": "no such reorder"})
                reorder["status"] = "cancelled"
                state.save()
            return self.reply(200, reorder)

    return Handler


def main() -> None:
    port, data = int(sys.argv[1]), Path(sys.argv[2])
    warehouse = (data / "warehouse").read_text().strip() if (data / "warehouse").exists() else "north"
    ThreadingHTTPServer(("0.0.0.0", port), handler(State(data, warehouse))).serve_forever()


if __name__ == "__main__":
    main()
