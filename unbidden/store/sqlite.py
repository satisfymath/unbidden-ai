"""All durable state of a workspace in one SQLite file.

One process owns the file, so jobs are claimed inside a transaction instead of with row locks. Events and
audit entries are append-only, enforced by triggers. Every payload is redacted before it is written.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import AuditEntry, Event
from unbidden.contracts.jobs import Job, JobStatus
from unbidden.guardian.scanner import redact_json

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    actor TEXT NOT NULL,
    entity_id TEXT,
    correlation_id TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_correlation ON events(correlation_id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    correlation_id TEXT,
    data TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;

CREATE TABLE IF NOT EXISTS docs (
    collection TEXT NOT NULL,
    id TEXT NOT NULL,
    key TEXT,
    status TEXT,
    doc TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (collection, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS docs_key ON docs(collection, key) WHERE key IS NOT NULL;
CREATE INDEX IF NOT EXISTS docs_status ON docs(collection, status);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    run_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status, priority, run_at);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

M = TypeVar("M", bound=BaseModel)


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _dump(model: BaseModel) -> str:
    return json.dumps(redact_json(model.model_dump(mode="json")), sort_keys=True)


class Store:
    def __init__(self, path: Path | None) -> None:
        """Open the workspace state at `path`, or an in-memory store when `path` is None."""
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        target = ":memory:" if path is None else str(path)
        self._conn = sqlite3.connect(target, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if path is not None:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        (version,) = self._conn.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"state was written by a newer unbidden (schema {version} > {SCHEMA_VERSION})")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    # Events and audit -------------------------------------------------------------------------------------

    def append_event(self, event: Event) -> Event:
        payload = json.dumps(redact_json(event.payload), sort_keys=True)
        cur = self._conn.execute(
            "INSERT INTO events (ts, type, actor, entity_id, correlation_id, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (_ts(event.ts), event.type.value, event.actor, event.entity_id, event.correlation_id, payload),
        )
        return event.model_copy(update={"seq": cur.lastrowid, "payload": json.loads(payload)})

    def events(self, *, after: int = 0, correlation_id: str | None = None, limit: int = 1000) -> list[Event]:
        sql = "SELECT * FROM events WHERE seq > ?"
        args: list[Any] = [after]
        if correlation_id is not None:
            sql += " AND correlation_id = ?"
            args.append(correlation_id)
        sql += " ORDER BY seq LIMIT ?"
        args.append(limit)
        return [
            Event(
                seq=row["seq"],
                ts=datetime.fromisoformat(row["ts"]),
                type=row["type"],
                actor=row["actor"],
                entity_id=row["entity_id"],
                correlation_id=row["correlation_id"],
                payload=json.loads(row["payload"]),
            )
            for row in self._conn.execute(sql, args)
        ]

    def append_audit(self, entry: AuditEntry) -> None:
        self._conn.execute(
            "INSERT INTO audit (ts, actor, kind, summary, correlation_id, data) VALUES (?, ?, ?, ?, ?, ?)",
            (
                _ts(entry.ts),
                entry.actor,
                entry.kind,
                str(redact_json(entry.summary)),
                entry.correlation_id,
                json.dumps(redact_json(entry.data), sort_keys=True),
            ),
        )

    # Documents --------------------------------------------------------------------------------------------

    def put(self, collection: str, model: BaseModel, *, key: str | None = None) -> None:
        doc_id: str = getattr(model, "id")  # noqa: B009 - every stored contract carries an id
        status = getattr(model, "status", None)
        self._conn.execute(
            """INSERT INTO docs (collection, id, key, status, doc, updated_at) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (collection, id) DO UPDATE SET
                 key = COALESCE(excluded.key, docs.key), status = excluded.status,
                 doc = excluded.doc, updated_at = excluded.updated_at""",
            (collection, doc_id, key, None if status is None else str(status), _dump(model), _ts(utc_now())),
        )

    def get(self, collection: str, doc_id: str, model: type[M]) -> M | None:
        row = self._conn.execute(
            "SELECT doc FROM docs WHERE collection = ? AND id = ?", (collection, doc_id)
        ).fetchone()
        return None if row is None else model.model_validate_json(row["doc"])

    def get_by_key(self, collection: str, key: str, model: type[M]) -> M | None:
        row = self._conn.execute("SELECT doc FROM docs WHERE collection = ? AND key = ?", (collection, key)).fetchone()
        return None if row is None else model.model_validate_json(row["doc"])

    def list(self, collection: str, model: type[M], *, status: str | None = None) -> list[M]:
        sql = "SELECT doc FROM docs WHERE collection = ?"
        args: list[Any] = [collection]
        if status is not None:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY updated_at"
        return [model.model_validate_json(row["doc"]) for row in self._conn.execute(sql, args)]

    # Jobs -------------------------------------------------------------------------------------------------

    def enqueue(self, job: Job) -> bool:
        """Queue a job unless one with the same idempotency key exists. Returns whether it was queued."""
        cur = self._conn.execute(
            """INSERT INTO jobs (id, type, status, priority, run_at, idempotency_key, doc)
               VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (idempotency_key) DO NOTHING""",
            (job.id, job.type, job.status.value, job.priority, _ts(job.run_at), job.idempotency_key, _dump(job)),
        )
        return cur.rowcount == 1

    def claim(self, *, now: datetime | None = None) -> Job | None:
        moment = _ts(now or utc_now())
        with self.transaction() as conn:
            row = conn.execute(
                """SELECT doc FROM jobs WHERE status = ? AND run_at <= ?
                   ORDER BY priority, run_at LIMIT 1""",
                (JobStatus.QUEUED.value, moment),
            ).fetchone()
            if row is None:
                return None
            job = Job.model_validate_json(row["doc"])
            job.status = JobStatus.RUNNING
            job.attempts += 1
            self._save_job(conn, job)
            return job

    def finish(self, job: Job, *, error: str | None = None, retry_in: timedelta | None = None) -> Job:
        if error is None:
            job.status = JobStatus.DONE
            job.last_error = None
        elif job.attempts < job.max_attempts and retry_in is not None:
            job.status = JobStatus.QUEUED
            job.last_error = error
            job.run_at = utc_now() + retry_in
        else:
            job.status = JobStatus.FAILED
            job.last_error = error
        with self.transaction() as conn:
            self._save_job(conn, job)
        return job

    def jobs(self, *, status: JobStatus | None = None) -> list[Job]:
        sql = "SELECT doc FROM jobs"
        args: list[Any] = []
        if status is not None:
            sql += " WHERE status = ?"
            args.append(status.value)
        return [Job.model_validate_json(row["doc"]) for row in self._conn.execute(sql + " ORDER BY run_at", args)]

    def requeue_running(self) -> int:
        """After a crash, jobs left running belong to no one; put them back in the queue."""
        stuck = self.jobs(status=JobStatus.RUNNING)
        with self.transaction() as conn:
            for job in stuck:
                job.status = JobStatus.QUEUED
                self._save_job(conn, job)
        return len(stuck)

    def _save_job(self, conn: sqlite3.Connection, job: Job) -> None:
        conn.execute(
            "UPDATE jobs SET status = ?, priority = ?, run_at = ?, doc = ? WHERE id = ?",
            (job.status.value, job.priority, _ts(job.run_at), _dump(job), job.id),
        )

    # Key-value --------------------------------------------------------------------------------------------

    def set_value(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(redact_json(value))),
        )

    def get_value(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    # Used by the secret-plant test: everything that was ever written, as text.
    def dump_all_text(self) -> Iterator[str]:
        for table in ("events", "audit", "docs", "jobs", "kv"):
            for row in self._conn.execute(f"SELECT * FROM {table}"):
                yield " ".join(str(v) for v in tuple(row))
