"""PostgreSQL over the network: a database outside the observed compose project, reached with a granted role.

What the role can do is observed, not assumed: `check` logs in, reads its identity, whether TLS is in use, and its
privileges on every table it can see (`has_table_privilege`). Reads are bounded: one statement, `SELECT` or `WITH`
only, wrapped in a row limit, inside a read-only transaction with a statement timeout; the role's own privileges
are the second fence. A role that holds more than the grant asks (INSERT on a table granted read) is reported, never
used. The password comes from the broker for this connection only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import psycopg

from unbidden.connect.base import CheckResult, Failure, purpose
from unbidden.contracts.connection import Ability, Connection, ConnectionState
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.guardian.credentials import broker

LOCATION = re.compile(r"^(?P<host>[^:/]+):(?P<port>\d+)/(?P<database>[\w.-]+)$")
MAX_ROWS = 1000
TIMEOUT_MS = 5000
_SELECT = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_PRIVILEGES = """
SELECT n.nspname, c.relname,
       has_table_privilege(c.oid, 'SELECT'), has_table_privilege(c.oid, 'INSERT'),
       has_table_privilege(c.oid, 'UPDATE'), has_table_privilege(c.oid, 'DELETE')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2"""
_CATALOG = """
SELECT n.nspname, c.relname, greatest(c.reltuples, 0)::bigint,
       (SELECT json_agg(json_build_object('column', a.attname, 'type', format_type(a.atttypid, a.atttypmod))
                        ORDER BY a.attnum)
          FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND has_table_privilege(c.oid, 'SELECT')
ORDER BY 1, 2"""


class QueryRefused(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    database: str


def target(location: str) -> Target | None:
    match = LOCATION.match(location)
    return Target(match["host"], int(match["port"]), match["database"]) if match else None


def _connect(grant: ConnectionGrant, password: str) -> psycopg.Connection[Any]:
    where = target(grant.location)
    assert where is not None
    return psycopg.connect(
        host=where.host,
        port=where.port,
        dbname=where.database,
        user=grant.username,
        password=password,
        sslmode=grant.tls,
        connect_timeout=5,
        application_name="unbidden",
        options=f"-c default_transaction_read_only=on -c statement_timeout={TIMEOUT_MS}",
    )


def _classify(exc: psycopg.Error) -> tuple[Failure, str]:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    lowered = text.lower()
    if "password authentication failed" in lowered or ("role" in lowered and "does not exist" in lowered):
        return Failure.AUTH, text
    if "permission denied" in lowered or "not permitted" in lowered:
        return Failure.PERMISSION, text
    if "database" in lowered and "does not exist" in lowered:
        return Failure.NOT_FOUND, text
    return Failure.UNREACHABLE, text


class PostgresConnector:
    kind = "postgres"

    def validate(self, grant: ConnectionGrant) -> list[str]:
        problems = [] if target(grant.location) else ["location must be host:port/database"]
        if not grant.username:
            problems.append("the role to log in as (username)")
        if not grant.credential_ref:
            problems.append("a credential reference for its password")
        return problems

    def check(self, grant: ConnectionGrant) -> CheckResult:
        password = broker().get(grant.credential_ref or "", purpose(grant.id))
        if not password:
            return CheckResult(
                ConnectionState.NEEDS_AUTHORIZATION,
                f"{grant.credential_ref} is not held by the broker",
                failure=Failure.AUTH,
                next_step=f"a person stores the password of role {grant.username} as {grant.credential_ref} "
                "in Unbidden's .env; read-only privileges are enough for what is granted",
            )
        try:
            with _connect(grant, password) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT current_user, version(), (SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())"
                )
                user, version, ssl = cur.fetchone() or ("?", "?", None)
                cur.execute(_PRIVILEGES)
                rows = cur.fetchall()
        except psycopg.Error as exc:
            failure, text = _classify(exc)
            state = {
                Failure.AUTH: ConnectionState.NEEDS_AUTHORIZATION,
                Failure.NOT_FOUND: ConnectionState.NEEDS_CONFIGURATION,
                Failure.PERMISSION: ConnectionState.NEEDS_AUTHORIZATION,
            }.get(failure, ConnectionState.DEGRADED)
            return CheckResult(state, text, failure=failure, next_step=_next(failure, grant))
        readable = [f"{s}.{t}" for s, t, sel, *_ in rows if sel]
        writable = [f"{s}.{t}" for s, t, _, ins, upd, dele in rows if ins or upd or dele]
        if not readable:
            return CheckResult(
                ConnectionState.NEEDS_AUTHORIZATION,
                f"{user} can log in but read no table",
                failure=Failure.PERMISSION,
                next_step=f"GRANT SELECT to {user} on the tables needed",
            )
        abilities = [
            Ability(
                kind="read",
                operations=["catalog", *(f"select {t}" for t in readable)],
                known_by=f"checked: has_table_privilege SELECT as {user}",
            )
        ]
        effective = ["read"]
        detail = f"{user} on {version.split(',')[0]}, TLS {'on' if ssl else 'off'}; reads {len(readable)} tables"
        if writable:
            # Observed so a person can tighten it; never used: the grant is what may be done, and reads run in
            # read-only transactions whatever the role holds.
            effective.append(
                "write (held by the role, not granted)" if "write" not in " ".join(grant.permissions) else "write"
            )
            detail += f"; the role can also change {len(writable)} tables ({', '.join(writable[:3])})"
        return CheckResult(
            ConnectionState.CONNECTED,
            detail,
            effective=effective,
            abilities=abilities,
            facts={"user": user, "version": version, "tls": bool(ssl), "writable": writable},
        )


def _next(failure: Failure, grant: ConnectionGrant) -> str:
    return {
        Failure.AUTH: f"the password stored as {grant.credential_ref} was refused for role {grant.username}: a person "
        "renews it or restores the role",
        Failure.NOT_FOUND: f"no database at {grant.location}: correct the grant's location",
        Failure.PERMISSION: f"role {grant.username} needs CONNECT and SELECT for what is granted",
    }.get(failure, f"{grant.location} did not answer: checked again at the next survey")


def query(
    conn: Connection, mandate: Mandate, sql: str, params: dict[str, Any] | None = None, *, limit: int = 200
) -> list[dict[str, Any]]:
    """One bounded read through a usable connection. Raises `Unavailable` or `QueryRefused`."""
    from unbidden.connect.base import require

    require(conn, mandate, "read", None, f"query {conn.id}")
    statement = sql.strip().rstrip(";")
    if not _SELECT.match(statement) or ";" in statement:
        raise QueryRefused("only one SELECT or WITH statement is read")
    grant = next(g for g in mandate.connections if g.id == conn.grant)
    password = broker().get(grant.credential_ref or "", purpose(grant.id)) or ""
    bounded = f"SELECT * FROM ({statement}) AS q LIMIT {min(limit, MAX_ROWS)}"
    with _connect(grant, password) as pg, pg.cursor() as cur:
        cur.execute(bounded, params or {})  # type: ignore[arg-type]
        columns = [d.name for d in cur.description or []]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def catalog(conn: Connection, mandate: Mandate) -> list[dict[str, Any]]:
    """Tables the role can read, their estimated rows and columns."""
    rows = query(conn, mandate, _CATALOG, limit=MAX_ROWS)
    return [
        {"schema": r["nspname"], "table": r["relname"], "rows": r["greatest"], "columns": r["json_agg"] or []}
        for r in rows
    ]
