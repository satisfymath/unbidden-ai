"""Where the board's numbers come from: the picks database and the Depot service."""

from __future__ import annotations

import os
from typing import Any

import httpx
import psycopg


def picks_7d() -> dict[str, int]:
    with psycopg.connect(os.environ["PICKS_DB"]) as conn:
        rows = conn.execute(
            "SELECT bin, sum(units) FROM picks WHERE picked_at > now() - interval '7 days' GROUP BY bin"
        ).fetchall()
    return {str(b): int(u) for b, u in rows}


def bins() -> list[dict[str, Any]]:
    base, key = os.environ["DEPOT_API"].rstrip("/"), os.environ["DEPOT_KEY"]
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = httpx.get(
            f"{base}/v1/bins", params={"offset": offset, "limit": 4}, headers={"X-Depot-Key": key}, timeout=10
        ).json()
        out += page["bins"]
        offset += len(page["bins"])
        if not page["bins"] or offset >= page["total"]:
            return out
