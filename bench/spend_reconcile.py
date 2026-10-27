"""Reconcile remote model spend: the machine ledger against every workspace's own record of its model runs.

    uv run python -m bench.spend_reconcile <dir> [<dir> ...] --out docs/bench/<name>

Each directory is searched for `.unbidden/state.db` files (the evidence archive included). A remote model run is
counted once per workspace state, by its id: a state copied into the archive is not counted twice. Runs before the
ledger existed are the historical spend; runs after it must each have a ledger row, and the ledger may hold calls no
workspace records (a script's, a refused call's). Costs are list price times reported tokens, never a bill.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any


def workspace_runs(roots: list[Path]) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for root in roots:
        for db in sorted(root.expanduser().rglob(".unbidden/state.db")):
            try:
                with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
                    rows = conn.execute("SELECT doc FROM docs WHERE collection = 'model_runs'").fetchall()
            except sqlite3.Error:
                continue
            for (doc,) in rows:
                run = json.loads(doc)
                if run["tier"] in ("frontier", "code") and run["id"] not in runs:
                    runs[run["id"]] = {**run, "state": str(db)}
    return runs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from unbidden.brain.spend import SpendLedger

    ledger = SpendLedger().rows()
    started = datetime.fromisoformat(ledger[0]["created_at"]) if ledger else None
    runs = workspace_runs([Path(r) for r in args.roots])
    before = [r for r in runs.values() if started is None or datetime.fromisoformat(r["created_at"]) < started]
    after = [r for r in runs.values() if started is not None and datetime.fromisoformat(r["created_at"]) >= started]
    sent_after = [r for r in after if r.get("egress_attempt_id")]
    charged = sum(float(r["charged"]) for r in ledger)
    by_status: dict[str, int] = {}
    for r in ledger:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    data = {
        "ledger_started": ledger[0]["created_at"] if ledger else None,
        "historical": {
            "calls": len(before),
            "tokens_in": sum(r["cost"]["tokens_in"] for r in before),
            "tokens_out": sum(r["cost"]["tokens_out"] for r in before),
            "usd": round(sum(r["cost"]["usd_remote"] for r in before), 4),
            "first": min((r["created_at"] for r in before), default=None),
        },
        "ledger": {"rows": len(ledger), "by_status": by_status, "usd": round(charged, 4)},
        "workspaces_since_ledger": {
            "runs": len(after),
            "runs_that_reached_the_provider": len(sent_after),
            "usd": round(sum(r["cost"]["usd_remote"] for r in after), 4),
        },
        "total_usd": round(sum(r["cost"]["usd_remote"] for r in before) + charged, 4),
        "basis": "list price x reported tokens (US$1.25 / US$4.25 per million for muse-spark-1.3); not a bill",
    }
    Path(f"{args.out}.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
