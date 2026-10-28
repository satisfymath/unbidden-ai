"""The project's connections: found, granted, checked, and kept current.

`survey` gathers candidates from four places, within what the mandate lets Unbidden look at (no network scan, no
account exploration):
- the mandate's grants: what a person authorized, checked by the kind's connector;
- the repository's configuration: compose services' environment values that point outside the compose project
  (`postgres://…@host:port/db`, `http://host:port`), recorded as discovered, never connected on that alone;
- the repository's git remote on GitHub;
- the sources the map already reads (the compose project, databases inside it, OpenAPI of its services, Prometheus,
  Jaeger), connected as far as the map observed them, read only.
A connection seen before and not found now is `gone`; a granted one whose grant is withdrawn is `revoked`. Every
change of state is recorded with its reason and as an event; anything that uses a connection goes through
`connect.base.require`, so a change takes effect at the next use.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from unbidden.connect.base import CheckResult, Connector, Failure, purpose
from unbidden.contracts.common import utc_now
from unbidden.contracts.connection import USABLE, Ability, Connection, ConnectionState, Environment
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.contracts.world import WorldModel
from unbidden.guardian.credentials import broker
from unbidden.guardian.policy import grant_host
from unbidden.store import Store

COLLECTION = "connections"
_URL = re.compile(
    r"^(?P<scheme>postgres(?:ql)?|https?)://(?:[^@/]+@)?(?P<host>[^:/?#]+)(?::(?P<port>\d+))?(?P<path>/[^?#]*)?"
)
LOCAL_ALIASES = {"host.docker.internal": "127.0.0.1", "localhost": "127.0.0.1"}


def connection_id(kind: str, location: str) -> str:
    return f"{kind}:{location}"


def _location(scheme: str, host: str, port: str | None, path: str | None) -> tuple[str, str]:
    host = LOCAL_ALIASES.get(host, host)
    if scheme.startswith("postgres"):
        database = (path or "/").strip("/").split("/")[0] or "postgres"
        return "postgres", f"{host}:{port or 5432}/{database}"
    return "http_api", f"{scheme}://{host}:{port or (443 if scheme == 'https' else 80)}"


def _same(location: str, grant: ConnectionGrant) -> bool:
    return grant_host(location) == grant_host(grant.location) or location == grant.location


def config_hints(repo: Path, rev: str = "HEAD") -> list[tuple[str, str, str]]:
    """(kind, location, evidence) for configuration values pointing outside the compose project."""
    from unbidden.observe.compose import load_compose

    compose = load_compose(repo, rev)
    if compose is None:
        return []
    inside = set(compose.services)
    found = []
    for service in compose.services.values():
        for key, value in sorted(service.environment.items()):
            match = _URL.match(str(value))
            if match is None or match["host"] in inside:
                continue
            kind, location = _location(match["scheme"], match["host"], match["port"], match["path"])
            found.append((kind, location, f"{compose.path} service {service.name} {key}"))
    return found


def github_remote(repo: Path) -> str | None:
    out = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True)
    match = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", out.stdout.strip())
    return match.group(1) if match else None


def _from_world(world: WorldModel | None) -> list[tuple[Connection, str]]:
    """Sources the map already reads, connected as far as it observed them: read only, never written by Unbidden."""
    if world is None:
        return []
    found: list[tuple[Connection, str]] = []
    containers = world.of_kind("container")
    if containers:
        project = str(containers[0].attributes.get("project") or "compose")
        found.append(
            (
                Connection(
                    id=connection_id("compose", project),
                    project="",
                    kind="compose",
                    protocol="docker",
                    location=project,
                    state=ConnectionState.CONNECTED,
                    effective=["read"],
                    network="local docker socket",
                    abilities=[
                        Ability(
                            kind="read",
                            operations=["ps", "inspect", "logs"],
                            known_by=f"checked: the map listed {len(containers)} containers",
                        )
                    ],
                ),
                "the map's compose connector",
            )
        )
    for database in world.of_kind("database"):
        tables = [r for r in world.current_relations() if r.src == database.id and r.predicate == "defines"]
        if database.source and database.source.startswith("postgres-readonly") and tables:
            found.append(
                (
                    Connection(
                        id=connection_id("postgres", f"container:{database.name}"),
                        project="",
                        kind="postgres",
                        protocol="docker exec psql",
                        location=f"container:{database.name}",
                        state=ConnectionState.CONNECTED,
                        effective=["read"],
                        network="inside its container",
                        abilities=[
                            Ability(
                                kind="read",
                                operations=["catalog", "row estimates", "scan counters"],
                                known_by=f"checked: the map read {len(tables)} tables",
                            )
                        ],
                    ),
                    "the map's in-container Postgres reader",
                )
            )
    for kind, source in (("prometheus", "prometheus-metrics"), ("jaeger", "jaeger-traces")):
        stamped = [f for f in [*world.resources.values(), *world.relations] if (f.source or "").startswith(source)]
        if stamped:
            found.append(
                (
                    Connection(
                        id=connection_id(kind, "compose"),
                        project="",
                        kind=kind,
                        protocol="http",
                        location="compose",
                        state=ConnectionState.CONNECTED,
                        effective=["read"],
                        abilities=[
                            Ability(
                                kind="measure",
                                operations=["fixed queries"],
                                known_by=f"checked: the map took {len(stamped)} facts from it",
                            )
                        ],
                    ),
                    f"the map's {kind} connector",
                )
            )
    return found


def record(store: Store, conn: Connection, *, reason: str) -> Connection:
    """Store a connection; a change of state is kept in its history and published as an event. A credential
    refused where it used to work is a revocation (see `survey`)."""
    old = store.get(COLLECTION, conn.id, Connection)
    if old is not None:
        conn.history = old.history
        conn.discovered_by = sorted({*old.discovered_by, *conn.discovered_by})
        conn.capability_id = conn.capability_id or old.capability_id
    if old is None or old.state is not conn.state:
        conn.history = [*conn.history, {"at": utc_now().isoformat(), "state": conn.state.value, "why": reason}][-30:]
        store.append_event(
            Event(
                type=EventType.CONNECTION_CHANGED,
                actor="connect",
                entity_id=conn.id,
                payload={"from": old.state.value if old else None, "to": conn.state.value, "why": reason[:300]},
            )
        )
    conn.updated_at = utc_now()
    store.put(COLLECTION, conn)
    return conn


def apply(conn: Connection, result: CheckResult) -> Connection:
    conn.state, conn.check_detail, conn.checked_at = result.state, result.detail, utc_now()
    conn.effective, conn.abilities = result.effective, result.abilities
    conn.blocked = None if result.state is ConnectionState.CONNECTED else result.detail
    conn.next_step = result.next_step
    return conn


def survey(
    repo: Path,
    store: Store,
    mandate: Mandate,
    world: WorldModel | None,
    connectors: Mapping[str, Connector],
    *,
    check: bool = True,
) -> list[Connection]:
    project = mandate.workspace
    seen: dict[str, Connection] = {}
    for grant in mandate.connections:
        if grant.credential_ref:
            broker().grant(grant.credential_ref, purpose(grant.id))
        conn = Connection(
            id=connection_id(grant.kind, grant.location),
            project=project,
            kind=grant.kind,
            grant=grant.id,
            protocol={"postgres": "postgresql", "http_api": "http", "github": "https"}[grant.kind],
            location=grant.location,
            environment=Environment(grant.environment),
            credential_ref=grant.credential_ref,
            requested=list(grant.permissions),
            limits=dict(grant.limits),
            network=grant_host(grant.location),
            discovered_by=["mandate grant"],
        )
        connector = connectors.get(grant.kind)
        problems = connector.validate(grant) if connector else []
        if connector is None:
            conn.state, conn.blocked = ConnectionState.NEEDS_CAPABILITY, f"no connector for {grant.kind} yet"
            conn.next_step = "a capability for it is built when a task needs it"
        elif problems:
            conn.state, conn.blocked = ConnectionState.NEEDS_CONFIGURATION, "; ".join(problems)
            conn.next_step = "complete the grant in the mandate: " + "; ".join(problems)
        elif check:
            before = store.get(COLLECTION, conn.id, Connection)
            result = connector.check(grant)
            integrated = _integration(store, before)
            if integrated is not None and result.state is ConnectionState.NEEDS_CAPABILITY:
                # Reached and documented; with a validated integration, an authenticated read decides the state.
                from unbidden.forge.integrate import live_check

                conn.capability_id = integrated.id
                result = live_check(integrated, conn, mandate)
            if result.failure is Failure.AUTH and before is not None and before.state in USABLE:
                # It worked and now its credential is refused: revoked, not a configuration that was never right.
                result.state = ConnectionState.REVOKED
            apply(conn, result)
        else:
            previous = store.get(COLLECTION, conn.id, Connection)
            if previous is not None:
                conn.state, conn.effective, conn.abilities = previous.state, previous.effective, previous.abilities
                conn.checked_at, conn.check_detail = previous.checked_at, previous.check_detail
        seen[conn.id] = conn
    for kind, location, evidence in config_hints(repo):
        cid = connection_id(kind, location)
        granted = next(
            (c for c in seen.values() if c.kind == kind and grant_host(c.location) == grant_host(location)), None
        )
        if granted is not None:
            granted.discovered_by = sorted({*granted.discovered_by, evidence})
            continue
        seen[cid] = Connection(
            id=cid,
            project=project,
            kind=kind,
            protocol=kind,
            location=location,
            discovered_by=[evidence],
            network=grant_host(location),
            blocked="not granted by the mandate",
            next_step=f"to use it, a person adds a connection grant: kind {kind}, location {location}, a "
            "credential reference, and the permissions it may use",
        )
    slug = github_remote(repo)
    if slug and not any(c.kind == "github" and c.location == slug for c in seen.values()):
        configured = mandate.egress.github.repository == slug
        seen[connection_id("github", slug)] = Connection(
            id=connection_id("github", slug),
            project=project,
            kind="github",
            protocol="https",
            location=slug,
            discovered_by=["git remote origin"],
            network="api.github.com",
            state=ConnectionState.NEEDS_AUTHORIZATION if configured else ConnectionState.DISCOVERED,
            blocked=None if configured else "the mandate names no GitHub repository",
            next_step=None if configured else f"set egress.github.repository to {slug} and grant a token reference",
        )
    for conn, evidence in _from_world(world):
        conn.project, conn.discovered_by = project, [evidence]
        seen.setdefault(conn.id, conn)
    for old in store.list(COLLECTION, Connection):
        if old.id in seen or old.state is ConnectionState.GONE:
            continue
        lost = old.model_copy()
        if old.grant:
            lost.state, lost.blocked = ConnectionState.REVOKED, "its grant was withdrawn from the mandate"
        else:
            lost.state, lost.blocked = ConnectionState.GONE, "not found where it was any more"
        seen[old.id] = lost
    return [record(store, c, reason=c.blocked or c.check_detail or "checked") for c in seen.values()]


def _integration(store: Store, before: Connection | None) -> Any:
    """The validated integration a connection is used through, if it has one."""
    if before is None or not before.capability_id:
        return None
    from unbidden.forge.api_client import COLLECTION as INTEGRATIONS
    from unbidden.forge.api_client import ApiIntegration

    found = store.get(INTEGRATIONS, before.capability_id, ApiIntegration)
    return found if found is not None and found.status == "validated" else None


def get(store: Store, connection: str) -> Connection | None:
    return store.get(COLLECTION, connection, Connection)


def by_grant(store: Store, grant_id: str) -> Connection | None:
    return next((c for c in store.list(COLLECTION, Connection) if c.grant == grant_id), None)


def summary(connections: list[Connection]) -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "environment": c.environment.value,
            "state": c.state.value,
            "read": [
                o
                for a in c.abilities
                if a.kind in ("read", "measure") and a.known_by.startswith("checked")
                for o in a.operations
            ],
            "write": [
                o for a in c.abilities if a.kind == "write" and a.known_by.startswith("checked") for o in a.operations
            ],
            "requested": c.requested,
            "effective": c.effective,
            "blocked": c.blocked,
            "next_step": c.next_step,
            "found_by": c.discovered_by,
            "checked_at": c.checked_at.isoformat() if c.checked_at else None,
        }
        for c in sorted(connections, key=lambda c: (c.state.value, c.id))
    ]
