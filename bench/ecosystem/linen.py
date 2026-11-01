"""Linen: the stage 6 evaluation service for question A (never used in development). A hotel laundry's floor
stations and towel deliveries. Written and frozen before the evaluation ran.

    python linen.py <port> <data dir>          (data dir: `keys`, `stations.json`)

OpenAPI 3.1 (nullable fields as type arrays); page-number pagination (`page`, `per_page` up to 8, `total_pages`);
an `X-Linen-Key` header; deliveries created with an `Idempotency-Key` (a repeat returns the same delivery and applies
nothing) and cancelled with a documented DELETE that reverts them. Keys are read at every request.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

PER_PAGE, MAX_BUNDLES = 8, 25
STATION = {
    "type": "object",
    "required": ["station", "floor", "clean", "held", "en_route", "note"],
    "properties": {
        "station": {"type": "string", "description": "the floor station's code"},
        "floor": {"type": "integer"},
        "clean": {"type": "integer", "description": "clean towel bundles on the shelf"},
        "held": {"type": "integer", "description": "bundles held back for rooms already booked"},
        "en_route": {"type": "integer", "description": "bundles on their way from deliveries"},
        "note": {"type": ["string", "null"]},
    },
}
DELIVERY = {
    "type": "object",
    "required": ["delivery_id", "station", "bundles", "state"],
    "properties": {
        "delivery_id": {"type": "string"},
        "station": {"type": "string"},
        "bundles": {"type": "integer"},
        "state": {"type": "string", "enum": ["scheduled", "cancelled"]},
        "eta": {"type": ["string", "null"]},
    },
}
PROBLEM = {"type": "object", "properties": {"title": {"type": "string"}, "status": {"type": "integer"}}}


def document() -> dict[str, Any]:
    def problem(d: str) -> dict[str, Any]:
        return {"description": d, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Problem"}}}}

    return {
        "openapi": "3.1.0",
        "info": {"title": "Linen", "version": "3.0.2", "summary": "Towels for a hotel's floor stations"},
        "components": {
            "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Linen-Key"}},
            "schemas": {"Station": STATION, "Delivery": DELIVERY, "Problem": PROBLEM},
        },
        "security": [{"key": []}],
        "paths": {
            "/v3/stations": {
                "get": {
                    "operationId": "listStations",
                    "summary": "Floor stations and their towel stock, by page",
                    "parameters": [
                        {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                        {"name": "per_page", "in": "query",
                         "schema": {"type": "integer", "minimum": 1, "maximum": PER_PAGE}},
                    ],
                    "responses": {
                        "200": {"description": "a page", "content": {"application/json": {"schema": {
                            "type": "object", "required": ["stations", "page", "total_pages"],
                            "properties": {
                                "stations": {"type": "array", "items": {"$ref": "#/components/schemas/Station"}},
                                "page": {"type": "integer"}, "total_pages": {"type": "integer"}}}}}},
                        "401": problem("no key, or a key it does not know"),
                    },
                }
            },
            "/v3/deliveries": {
                "post": {
                    "operationId": "scheduleDelivery",
                    "summary": "Schedule a delivery of towel bundles to a floor station",
                    "description": "Adds the bundles to the station's `en_route`. Idempotent per Idempotency-Key. "
                    "Cancel with DELETE /v3/deliveries/{delivery_id}.",
                    "parameters": [
                        {"name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string"}}
                    ],
                    "requestBody": {"content": {"application/json": {"schema": {
                        "type": "object", "required": ["station", "bundles"], "additionalProperties": False,
                        "properties": {"station": {"type": "string"},
                                       "bundles": {"type": "integer", "minimum": 1, "maximum": MAX_BUNDLES}}}}}},
                    "responses": {
                        "201": {"description": "scheduled",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Delivery"}}}},
                        "200": {"description": "already scheduled with this key",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Delivery"}}}},
                        "401": problem("no key"), "404": problem("no such station"), "422": problem("invalid"),
                    },
                }
            },
            "/v3/deliveries/{delivery_id}": {
                "delete": {
                    "operationId": "cancelDelivery",
                    "summary": "Cancel a delivery",
                    "parameters": [{"name": "delivery_id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "cancelled",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Delivery"}}}},
                        "401": problem("no key"), "404": problem("no such delivery"),
                    },
                }
            },
        },
    }  # fmt: skip


class Linen:
    def __init__(self, keys: set[str], stations: list[dict[str, Any]]) -> None:
        self.keys = keys
        self.stations = {s["station"]: dict(s) for s in stations}
        self.deliveries: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, str] = {}
        self.lock = threading.Lock()

    def handle(self, method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, Any]:
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        if path == "/openapi.json":
            return 200, document()
        lowered = {k.lower(): v for k, v in headers.items()}
        if lowered.get("x-linen-key") not in self.keys:
            return 401, {"title": "no key, or a key it does not know", "status": 401}
        with self.lock:
            if method == "GET" and path == "/v3/stations":
                per = min(int(query.get("per_page", [str(PER_PAGE)])[0]), PER_PAGE)
                page = max(1, int(query.get("page", ["1"])[0]))
                codes = sorted(self.stations)
                total = max(1, math.ceil(len(codes) / per))
                batch = codes[(page - 1) * per : page * per]
                return 200, {"stations": [dict(self.stations[c]) for c in batch], "page": page, "total_pages": total}
            if method == "POST" and path == "/v3/deliveries":
                key = lowered.get("idempotency-key") or ""
                data = json.loads(body or b"{}")
                if key and key in self.by_key:
                    return 200, dict(self.deliveries[self.by_key[key]])
                bundles, station = data.get("bundles"), data.get("station")
                if (
                    not isinstance(bundles, int)
                    or not 1 <= bundles <= MAX_BUNDLES
                    or set(data) - {"station", "bundles"}
                ):
                    return 422, {"title": "invalid", "status": 422}
                if station not in self.stations:
                    return 404, {"title": "no such station", "status": 404}
                delivery = {"delivery_id": f"dl-{uuid.uuid4().hex[:9]}", "station": station, "bundles": bundles,
                            "state": "scheduled", "eta": None}  # fmt: skip
                self.deliveries[delivery["delivery_id"]] = delivery
                if key:
                    self.by_key[key] = delivery["delivery_id"]
                self.stations[station]["en_route"] += bundles
                return 201, dict(delivery)
            if method == "DELETE" and path.startswith("/v3/deliveries/"):
                delivery = self.deliveries.get(path.rsplit("/", 1)[-1])
                if delivery is None:
                    return 404, {"title": "no such delivery", "status": 404}
                if delivery["state"] == "scheduled":
                    self.stations[delivery["station"]]["en_route"] -= delivery["bundles"]
                delivery["state"] = "cancelled"
                return 200, dict(delivery)
        return 404, {"title": "no such path", "status": 404}


def transport(linen: Linen) -> Any:
    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        status, body = linen.handle(request.method, str(request.url), dict(request.headers), request.content)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def main() -> None:
    port, home = int(sys.argv[1]), Path(sys.argv[2])
    linen = Linen(set((home / "keys").read_text().split()), json.loads((home / "stations.json").read_text()))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            sys.stdout.write(f"{self.command} {self.path}\n")

        def _serve(self) -> None:
            linen.keys = set((home / "keys").read_text().split())
            length = int(self.headers.get("Content-Length") or 0)
            status, body = linen.handle(self.command, self.path, dict(self.headers), self.rfile.read(length))
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
