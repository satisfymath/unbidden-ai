"""The canvas and the conversation, persisted apart from the engine's state.

One SQLite file owned by the web server process. Layouts are versioned: undo and redo move a pointer along the
versions kept (the last 50); a save on a stale base is refused so two tabs cannot overwrite each other blindly.
Deleting a widget removes a widget; undoing a card reverts a card. No experiment, deploy or audit is touched.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from unbidden.contracts.common import utc_now
from unbidden.web.contracts import ChatMessage, Presentation, PresentationUpdate

HISTORY = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS layouts (
    source TEXT NOT NULL, version INTEGER NOT NULL, doc TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (source, version)
);
CREATE TABLE IF NOT EXISTS pointer (source TEXT PRIMARY KEY, version INTEGER NOT NULL, top INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, id TEXT NOT NULL UNIQUE, doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_source ON messages(source, seq);
"""


class StaleVersion(RuntimeError):
    def __init__(self, current: int) -> None:
        super().__init__(f"the canvas changed elsewhere (version {current}); reload before saving")
        self.current = current


class PresentationStore:
    def __init__(self, path: Path | None) -> None:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            ":memory:" if path is None else str(path), isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        if path is not None:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    # Layouts ---------------------------------------------------------------------------------------------------

    def current(self, source: str) -> Presentation:
        with self._lock:
            ptr = self._conn.execute("SELECT version FROM pointer WHERE source = ?", (source,)).fetchone()
            if ptr is None:
                return Presentation(workspace=source, version=0)
            row = self._conn.execute(
                "SELECT doc FROM layouts WHERE source = ? AND version = ?", (source, ptr["version"])
            ).fetchone()
            return Presentation.model_validate_json(row["doc"])

    def history(self, source: str) -> dict[str, int | bool]:
        with self._lock:
            ptr = self._conn.execute("SELECT version, top FROM pointer WHERE source = ?", (source,)).fetchone()
            if ptr is None:
                return {"version": 0, "top": 0, "can_undo": False, "can_redo": False}
            oldest = self._conn.execute("SELECT MIN(version) FROM layouts WHERE source = ?", (source,)).fetchone()[0]
            return {
                "version": ptr["version"],
                "top": ptr["top"],
                "can_undo": ptr["version"] > (oldest or 0),
                "can_redo": ptr["version"] < ptr["top"],
            }

    def save(self, source: str, update: PresentationUpdate) -> Presentation:
        with self._lock:
            now = self.current(source)
            if update.base_version != now.version:
                raise StaleVersion(now.version)
            version = now.version + 1
            doc = Presentation(
                workspace=source,
                version=version,
                widgets=update.widgets,
                edges=update.edges,
                viewport=update.viewport,
                config=update.config,
                updated_at=utc_now(),
            )
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # A save after an undo drops the redo branch, as every editor does.
                self._conn.execute("DELETE FROM layouts WHERE source = ? AND version >= ?", (source, version))
                self._conn.execute(
                    "INSERT INTO layouts (source, version, doc, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                    (source, version, doc.model_dump_json(by_alias=True), update.reason, utc_now().isoformat()),
                )
                self._conn.execute(
                    "INSERT INTO pointer (source, version, top) VALUES (?, ?, ?) ON CONFLICT (source) DO UPDATE SET "
                    "version = excluded.version, top = excluded.top",
                    (source, version, version),
                )
                self._conn.execute(
                    "DELETE FROM layouts WHERE source = ? AND version < ?", (source, max(0, version - HISTORY))
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            return doc

    def _move(self, source: str, delta: int) -> Presentation | None:
        with self._lock:
            ptr = self._conn.execute("SELECT version, top FROM pointer WHERE source = ?", (source,)).fetchone()
            if ptr is None:
                return None
            target = ptr["version"] + delta
            row = self._conn.execute(
                "SELECT doc FROM layouts WHERE source = ? AND version = ?", (source, target)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("UPDATE pointer SET version = ? WHERE source = ?", (target, source))
            return Presentation.model_validate_json(row["doc"])

    def undo(self, source: str) -> Presentation | None:
        return self._move(source, -1)

    def redo(self, source: str) -> Presentation | None:
        return self._move(source, +1)

    def reasons(self, source: str, limit: int = 20) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT version, reason, created_at FROM layouts WHERE source = ? ORDER BY version DESC LIMIT ?",
            (source, limit),
        )
        return [dict(r) for r in rows]

    # Conversation ----------------------------------------------------------------------------------------------

    def messages(self, source: str, *, limit: int = 200) -> list[ChatMessage]:
        rows = self._conn.execute(
            "SELECT doc FROM messages WHERE source = ? ORDER BY seq DESC LIMIT ?", (source, limit)
        ).fetchall()
        return [ChatMessage.model_validate_json(r["doc"]) for r in reversed(rows)]

    def add_message(self, source: str, message: ChatMessage) -> ChatMessage:
        self._conn.execute(
            "INSERT INTO messages (source, id, doc) VALUES (?, ?, ?) ON CONFLICT (id) DO UPDATE SET doc = excluded.doc",
            (source, message.id, message.model_dump_json(by_alias=True)),
        )
        return message

    def clear_messages(self, source: str) -> int:
        cur = self._conn.execute("DELETE FROM messages WHERE source = ?", (source,))
        return cur.rowcount

    def dump(self, source: str) -> str:
        return json.dumps(
            {
                "layout": self.current(source).model_dump(mode="json", by_alias=True),
                "messages": [m.model_dump(mode="json", by_alias=True) for m in self.messages(source)],
            }
        )
