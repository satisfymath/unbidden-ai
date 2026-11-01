"""A read-only view of a workspace's state, without the migrations `Store.__init__` runs.

`Store.__init__` opens the file, sets the journal mode and migrates the schema: right for the one process that owns
the state, wrong for a viewer. `ReadOnlyStore` opens `file:...?mode=ro` (SQLite reads the WAL itself; a copy of the
file alone would miss it), checks the schema version is one it understands, and inherits every read method, so the
engine's own report (`director.activity.build`) runs on it unchanged. Any write raises at the SQLite level.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from unbidden.store.sqlite import SCHEMA_VERSION, Store

SUPPORTED = frozenset({1, 2})


class ReaderError(RuntimeError):
    pass


class ReadOnlyStore(Store):
    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise ReaderError(f"{path} does not exist")
        self.path = path
        self.lock = threading.RLock()
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            (version,) = self._conn.execute("PRAGMA user_version").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ReaderError(f"{path}: not a state database ({exc})") from exc
        if version > SCHEMA_VERSION or version not in SUPPORTED:
            raise ReaderError(f"{path}: schema {version} is not one this viewer understands ({sorted(SUPPORTED)})")
        self.schema_version = int(version)
        tables = {r[0] for r in self._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = {"events", "docs", "kv"} - tables
        if missing:
            raise ReaderError(f"{path}: tables missing: {', '.join(sorted(missing))}")

    # Reads the engine's Store lacks, for paging and counting ---------------------------------------------------

    def count(self, collection: str, *, status: str | None = None) -> int:
        sql, args = "SELECT COUNT(*) FROM docs WHERE collection = ?", [collection]
        if status is not None:
            sql += " AND status = ?"
            args.append(status)
        return int(self._conn.execute(sql, args).fetchone()[0])

    def last_seq(self) -> int:
        row = self._conn.execute("SELECT MAX(seq) FROM events").fetchone()
        return int(row[0] or 0)

    def event_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def event_types(self) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in self._conn.execute("SELECT type, COUNT(*) FROM events GROUP BY type")}

    def raw_docs(self, collection: str, *, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Documents as stored, for contracts the viewer does not import (Forge cards, verdicts)."""
        import json

        rows = self._conn.execute(
            "SELECT doc FROM docs WHERE collection = ? ORDER BY updated_at LIMIT ? OFFSET ?",
            (collection, limit, offset),
        )
        return [json.loads(r["doc"]) for r in rows]

    def kv_keys(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT key FROM kv ORDER BY key")]

    def job_counts(self) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in self._conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}

    def round_summary(self) -> list[dict[str, Any]]:
        return [
            {"target": r[0], "deploys": int(r[1]), "rounds": int(r[2])}
            for r in self._conn.execute("SELECT target, COUNT(DISTINCT deploy), COUNT(*) FROM rounds GROUP BY target")
        ]


def open_workspace_state(workspace: Path) -> ReadOnlyStore:
    return ReadOnlyStore(workspace / ".unbidden" / "state.db")
