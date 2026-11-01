"""Carrier: a freight service for the stage 3 *evaluation* lab (written before the evaluation ran; never in dev).

    python carrier.py <port> <data dir>

Unlike Stockroom: offset/limit pagination with a total, a different auth header, regions instead of SKUs, kilograms
instead of units, bookings instead of reorders. Lanes per region: capacity and booked kilograms. Bookings take an
`Idempotency-Key`, at most 500 kg, and are withdrawn by DELETE. Keys are read from `<data>/keys` per request.
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

MAX_KG = 500
LOCK = threading.Lock()
REGIONS = [
    "andes",
    "atacama",
    "biobio",
    "coquimbo",
    "los-lagos",
    "maule",
    "nuble",
    "valparaiso",
    "araucania",
    "aysen",
    "magallanes",
    "tarapaca",
    "antofagasta",
    "metropolitana",
]
LANE = {
    "type": "object",
    "required": ["region", "capacity_kg", "booked_kg"],
    "properties": {
        "region": {"type": "string"},
        "capacity_kg": {"type": "integer", "minimum": 0},
        "booked_kg": {"type": "integer", "minimum": 0},
    },
}
BOOKING = {
    "type": "object",
    "required": ["booking_id", "region", "kg", "state"],
    "properties": {
        "booking_id": {"type": "string"},
        "region": {"type": "string"},
        "kg": {"type": "integer", "minimum": 1, "maximum": MAX_KG},
        "state": {"type": "string", "enum": ["confirmed", "withdrawn"]},
    },
}
ERR = {"type": "object", "properties": {"message": {"type": "string"}}}


def document(depot: str) -> dict[str, object]:
    def err(d: str) -> dict[str, object]:
        return {"description": d, "content": {"application/json": {"schema": ERR}}}

    return {
        "openapi": "3.0.3",
        "info": {"title": "Carrier", "version": "3.0.1", "description": f"Freight lanes of the {depot} depot."},
        "components": {"securitySchemes": {"token": {"type": "apiKey", "in": "header", "name": "X-Carrier-Token"}}},
        "security": [{"token": []}],
        "paths": {
            "/api/v2/lanes": {
                "get": {
                    "operationId": "listLanes",
                    "summary": "Capacity and booked weight of each lane, by region",
                    "parameters": [
                        {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 5}},
                    ],
                    "responses": {
                        "200": {
                            "description": "lanes",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["data", "total"],
                                        "properties": {
                                            "data": {"type": "array", "items": LANE},
                                            "total": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        },
                        "401": err("bad token"),
                    },
                }
            },
            "/api/v2/bookings": {
                "post": {
                    "operationId": "bookCapacity",
                    "summary": "Book extra capacity on a region's lane",
                    "description": f"At most {MAX_KG} kg per booking; repeat-safe with Idempotency-Key; withdraw with "
                    "DELETE /api/v2/bookings/{booking_id}.",
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
                                    "required": ["region", "kg"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "region": {"type": "string"},
                                        "kg": {"type": "integer", "minimum": 1, "maximum": MAX_KG},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {"description": "booked", "content": {"application/json": {"schema": BOOKING}}},
                        "200": {
                            "description": "already booked with this key",
                            "content": {"application/json": {"schema": BOOKING}},
                        },
                        "401": err("bad token"),
                        "404": err("no such region"),
                        "422": err("invalid"),
                    },
                }
            },
            "/api/v2/bookings/{booking_id}": {
                "delete": {
                    "operationId": "withdrawBooking",
                    "summary": "Withdraw a booking",
                    "parameters": [
                        {"name": "booking_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {"description": "withdrawn", "content": {"application/json": {"schema": BOOKING}}},
                        "401": err("bad token"),
                        "404": err("no such booking"),
                    },
                }
            },
        },
    }


class State:
    def __init__(self, data: Path, depot: str) -> None:
        self.data, self.depot = data, depot
        path = data / "state.json"
        if path.exists():
            saved = json.loads(path.read_text())
            self.lanes, self.bookings, self.keys = saved["lanes"], saved["bookings"], saved["keys"]
        else:
            rng = random.Random(f"carrier-{depot}")
            self.lanes = {
                r: {
                    "region": r,
                    "capacity_kg": rng.choice([800, 1200, 2000, 3000]),
                    "booked_kg": rng.choice([0, 200, 600, 900, 1500]),
                }
                for r in REGIONS
            }
            for lane in self.lanes.values():
                lane["booked_kg"] = min(lane["booked_kg"], lane["capacity_kg"])
            self.bookings, self.keys = {}, {}
            self.save()

    def save(self) -> None:
        (self.data / "state.json").write_text(
            json.dumps({"lanes": self.lanes, "bookings": self.bookings, "keys": self.keys})
        )

    def lane(self, region: str) -> dict[str, object]:
        extra = sum(b["kg"] for b in self.bookings.values() if b["region"] == region and b["state"] == "confirmed")
        base = self.lanes[region]
        return {**base, "capacity_kg": base["capacity_kg"] + extra}


def handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            sys.stdout.write(f"{self.command} {self.path}\n")

        def reply(self, status: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def ok(self) -> bool:
            keys = set((state.data / "keys").read_text().split())
            if self.headers.get("X-Carrier-Token") in keys:
                return True
            self.reply(401, {"message": "bad token"})
            return False

        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            if path == "/openapi.json":
                return self.reply(200, document(state.depot))
            if path != "/api/v2/lanes":
                return self.reply(404, {"message": "no such path"})
            if not self.ok():
                return None
            offset = int(m.group(1)) if (m := re.search(r"offset=(\d+)", query)) else 0
            limit = min(int(m.group(1)), 5) if (m := re.search(r"limit=(\d+)", query)) else 5
            with LOCK:
                regions = sorted(state.lanes)
                return self.reply(
                    200, {"data": [state.lane(r) for r in regions[offset : offset + limit]], "total": len(regions)}
                )

        def do_POST(self) -> None:
            if self.path != "/api/v2/bookings":
                return self.reply(404, {"message": "no such path"})
            if not self.ok():
                return None
            key = self.headers.get("Idempotency-Key") or ""
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            with LOCK:
                if len(key) < 8:
                    return self.reply(422, {"message": "Idempotency-Key required"})
                if key in state.keys:
                    return self.reply(200, state.bookings[state.keys[key]])
                kg, region = body.get("kg"), body.get("region")
                if set(body) - {"region", "kg"} or not isinstance(kg, int) or not 1 <= kg <= MAX_KG:
                    return self.reply(422, {"message": f"kg from 1 to {MAX_KG}"})
                if region not in state.lanes:
                    return self.reply(404, {"message": "no such region"})
                booking = {"booking_id": f"bk-{uuid.uuid4().hex[:8]}", "region": region, "kg": kg, "state": "confirmed"}
                state.bookings[booking["booking_id"]] = booking
                state.keys[key] = booking["booking_id"]
                state.save()
            return self.reply(201, booking)

        def do_DELETE(self) -> None:
            found = re.fullmatch(r"/api/v2/bookings/([\w-]+)", self.path)
            if not found:
                return self.reply(404, {"message": "no such path"})
            if not self.ok():
                return None
            with LOCK:
                booking = state.bookings.get(found.group(1))
                if booking is None:
                    return self.reply(404, {"message": "no such booking"})
                booking["state"] = "withdrawn"
                state.save()
            return self.reply(200, booking)

    return Handler


def main() -> None:
    port, data = int(sys.argv[1]), Path(sys.argv[2])
    depot = (data / "depot").read_text().strip() if (data / "depot").exists() else "santiago"
    ThreadingHTTPServer(("0.0.0.0", port), handler(State(data, depot))).serve_forever()


if __name__ == "__main__":
    main()
