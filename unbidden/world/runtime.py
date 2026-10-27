"""What the running system shows, read without changing it: containers, the live API and the database schema.

Every read is non-mutating: `docker compose ps`, HTTP GET of an API description on a published port, and SQL
in a read-only transaction through `psql` inside the database's own container (no credentials leave it).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import BlindSpot, Relation, Resource, WorldModel
from unbidden.observe.compose import DATA_IMAGES, deployed_compose_files, load_compose
from unbidden.world.connectors import COMPOSE_DOCKER, OPENAPI_HTTP, POSTGRES_READONLY

OBSERVED = EpistemicStatus.OBSERVED
OPENAPI_PATHS = ("/openapi.json", "/api/openapi.json", "/api/v1/openapi.json", "/v1/openapi.json", "/docs/openapi.json")
METHODS = ("get", "post", "put", "patch", "delete")

_SYSTEM_SCHEMAS = "('pg_catalog', 'information_schema', 'pg_toast')"
_PG_DATABASES = "SELECT datname FROM pg_database WHERE NOT datistemplate AND datallowconn ORDER BY 1"
_PG_TABLES = f"""
SELECT n.nspname, c.relname, GREATEST(c.reltuples, 0)::bigint, pg_total_relation_size(c.oid)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN {_SYSTEM_SCHEMAS} ORDER BY 1, 2
"""
_PG_INDEXES = f"""
SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname NOT IN {_SYSTEM_SCHEMAS} ORDER BY 1, 2, 3
"""
_PG_FKS = f"""
SELECT tc.table_schema, tc.table_name, kcu.column_name, ccu.table_schema, ccu.table_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema NOT IN {_SYSTEM_SCHEMAS}
"""


def table_id(database: str, default: str, schema: str, table: str) -> str:
    """`item` for public tables of the default database (as before); qualified names otherwise."""
    if database == default and schema == "public":
        return table
    return f"{schema}.{table}" if database == default else f"{database}/{schema}.{table}"


def _ref(kind: str, locator: str, note: str | None = None) -> EvidenceRef:
    return EvidenceRef(kind=kind, locator=locator, note=note)  # type: ignore[arg-type]


def running_containers(repo: Path) -> list[dict[str, Any]]:
    """Containers of this repository's compose project only (`--project-directory` scopes the query)."""
    out = subprocess.run(
        ["docker", "compose", "--project-directory", str(repo), "ps", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0 or not out.stdout.strip():
        return []
    text = out.stdout.strip()
    rows = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines()]
    return [r for r in rows if isinstance(r, dict)]


def host_ports(container: dict[str, Any]) -> list[int]:
    ports: list[int] = []
    for publisher in container.get("Publishers") or []:
        port = publisher.get("PublishedPort")
        if port:
            ports.append(int(port))
    return sorted(set(ports))


def fetch_openapi(port: int, *, timeout_s: float = 3.0) -> tuple[str, dict[str, Any]] | None:
    for path in OPENAPI_PATHS:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}{path}", timeout=timeout_s)
        except httpx.HTTPError:
            continue
        if response.status_code == 200 and "json" in response.headers.get("content-type", ""):
            data = response.json()
            if isinstance(data, dict) and "paths" in data:
                return path, data  # pyright: ignore[reportUnknownVariableType]
    return None


def psql(container: str, user: str, database: str, sql: str) -> list[list[str]] | None:
    out = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on",
            container,
            "psql",
            "-X",
            "-q",
            "-At",
            "-F",
            "\t",
            "-U",
            user,
            "-d",
            database,
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return None
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def _reconcile_endpoint(world: WorldModel, method: str, path: str, live: set[str]) -> dict[str, Any]:
    """Attach the code location of the inferred route this live endpoint is, and drop the guess.

    A route matches when the method agrees and the live path ends with the route's path; when several live
    endpoints could match, the route's file name must also appear in the path.
    """
    for rid, resource in list(world.resources.items()):
        if resource.kind != "endpoint" or resource.status is not EpistemicStatus.INFERRED:
            continue
        inferred_method, _, inferred_path = resource.name.partition(" ")
        if inferred_method != method or not path.endswith(inferred_path or "/"):
            continue
        rivals = [p for p in live if p.startswith(f"{method} ") and p.endswith(inferred_path or "/")]
        stem = Path(str(resource.attributes.get("file", ""))).stem
        if len(rivals) == 1 or (stem and f"/{stem}" in path):
            del world.resources[rid]
            return {"file": resource.attributes.get("file"), "line": resource.attributes.get("line")}
    return {}


def _postgres(world: WorldModel, service: str, container: str, user: str, default: str) -> bool:
    """Tables, indexes and foreign keys of every database and schema the server holds. False if nothing was read."""
    databases = [row[0] for row in psql(container, user, default, _PG_DATABASES) or []] or [default]
    read_any, empty = False, True
    for database in databases:
        tables = psql(container, user, database, _PG_TABLES)
        if tables is None:
            world.blind_spots.append(
                BlindSpot(what=f"tables of {service}/{database}", why="read-only SQL inside its container failed")
            )
            continue
        read_any = True
        locator = f"psql {service}/{database} (read-only)"
        for schema, table, rows, size in tables:
            empty = False
            tid = f"table:{table_id(database, default, schema, table)}"
            world.add(
                Resource(
                    id=tid,
                    kind="table",
                    name=table_id(database, default, schema, table),
                    attributes={
                        "database": service,
                        "db": database,
                        "schema": schema,
                        "rows_estimate": int(rows),
                        "bytes": int(size),
                        "indexes": [],
                    },
                    status=OBSERVED,
                    confidence=1.0,
                    evidence=[_ref("config", locator)],
                    source=POSTGRES_READONLY.ref,
                )
            )
            world.relate(
                Relation(
                    src=f"service:{service}",
                    dst=tid,
                    predicate="defines",
                    status=OBSERVED,
                    confidence=1.0,
                    evidence=[_ref("config", locator)],
                    source=POSTGRES_READONLY.ref,
                )
            )
        for schema, table, index, definition in psql(container, user, database, _PG_INDEXES) or []:
            resource = world.resources.get(f"table:{table_id(database, default, schema, table)}")
            if resource is not None:
                columns = re.search(r"\(([^)]*)\)", definition)
                resource.attributes["indexes"] = [
                    *resource.attributes.get("indexes", []),
                    {"name": index, "columns": columns.group(1) if columns else ""},
                ]
        for schema, table, column, target_schema, target in psql(container, user, database, _PG_FKS) or []:
            src = table_id(database, default, schema, table)
            dst = table_id(database, default, target_schema, target)
            world.relate(
                Relation(
                    src=f"table:{src}",
                    dst=f"table:{dst}",
                    predicate="references",
                    status=OBSERVED,
                    confidence=1.0,
                    evidence=[_ref("config", locator, f"{src}.{column} -> {dst}")],
                    source=POSTGRES_READONLY.ref,
                )
            )
    if read_any and empty:
        world.blind_spots.append(
            BlindSpot(what=f"tables of {service}", why="no database holds tables yet (migrations not applied?)")
        )
    return read_any


def compose_files(repo: Path) -> list[str]:
    """The compose files this project's running containers were started with, relative to the repository."""
    from unbidden.operate.ledger import _docker_json  # pyright: ignore[reportPrivateUsage]

    ids = [str(r["ID"]) for r in running_containers(repo) if r.get("ID")]
    labels = [
        str(((item.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.project.config_files", ""))
        for item in (_docker_json("inspect", *ids) if ids else [])
    ]
    return deployed_compose_files(repo, [label for label in labels if label])


def discover_runtime(repo: Path, world: WorldModel, rev: str = "HEAD", files: list[str] | None = None) -> set[str]:
    """Add what the running system shows. Returns the sources that actually ran, so facts they no longer see can
    be marked obsolete, and facts of sources that could not run are kept as they were."""
    containers = running_containers(repo)
    if not containers:
        world.blind_spots.append(
            BlindSpot(what="the running system", why="no container of this compose project is running")
        )
        return set()
    ran = {COMPOSE_DOCKER.ref}
    compose = load_compose(repo, rev, files)
    undeclared: list[str] = []
    for container in containers:
        service = container.get("Service", "")
        name = container.get("Name", "")
        if f"service:{service}" not in world.resources:
            # Running, but declared in a compose file not read (an override, `-f` files): known from Docker only.
            undeclared.append(service)
            data = DATA_IMAGES.match(str(container.get("Image", "")))
            world.add(
                Resource(
                    id=f"service:{service}",
                    kind="database" if data and data.group(1) not in ("redis", "valkey") else "service",
                    name=service,
                    attributes={"image": container.get("Image"), "engine": data.group(1) if data else None},
                    status=OBSERVED,
                    confidence=1.0,
                    evidence=[_ref("config", f"docker compose ps#{name}")],
                    source=COMPOSE_DOCKER.ref,
                )
            )
        world.add(
            Resource(
                id=f"container:{name}",
                kind="container",
                name=name,
                attributes={
                    "service": service,
                    "state": container.get("State"),
                    "image": container.get("Image"),
                    "ports": host_ports(container),
                    "health": container.get("Health"),
                },
                status=OBSERVED,
                confidence=1.0,
                evidence=[_ref("config", f"docker compose ps#{name}")],
                source=COMPOSE_DOCKER.ref,
            )
        )
        world.relate(
            Relation(
                src=f"container:{name}",
                dst=f"service:{service}",
                predicate="runs",
                status=OBSERVED,
                confidence=1.0,
                evidence=[_ref("config", f"docker compose ps#{name}")],
                source=COMPOSE_DOCKER.ref,
            )
        )

        published = host_ports(container)
        described = False
        for port in host_ports(container):
            found = fetch_openapi(port)
            if found is None:
                continue
            path, spec = found
            described = True
            ran.add(OPENAPI_HTTP.ref)
            locator = f"http://127.0.0.1:{port}{path}"
            live = {f"{m.upper()} {r}" for r, ops in spec["paths"].items() for m in METHODS if m in ops}
            world.blind_spots = [b for b in world.blind_spots if b.what != "full endpoint paths"]
            for route, operations in sorted(spec["paths"].items()):
                for method in METHODS:
                    if method not in operations:
                        continue
                    label = f"{method.upper()} {route}"
                    extra = _reconcile_endpoint(world, method.upper(), route, live)
                    world.add(
                        Resource(
                            id=f"endpoint:{label}",
                            kind="endpoint",
                            name=label,
                            attributes={
                                "service": service,
                                "port": port,
                                "tags": operations[method].get("tags", []),
                                "auth": bool(operations[method].get("security")),
                                **extra,
                            },
                            status=OBSERVED,
                            confidence=1.0,
                            evidence=[_ref("config", locator)],
                            source=OPENAPI_HTTP.ref,
                        )
                    )
                    world.relate(
                        Relation(
                            src=f"service:{service}",
                            dst=f"endpoint:{label}",
                            predicate="serves",
                            status=OBSERVED,
                            confidence=1.0,
                            evidence=[_ref("config", locator)],
                            source=OPENAPI_HTTP.ref,
                        )
                    )
        declared = compose.services.get(service) if compose else None
        if published and not described and (declared is None or declared.data_kind is None):
            world.blind_spots.append(
                BlindSpot(
                    what=f"endpoints of {service}",
                    why=f"ports {', '.join(map(str, published))} are published but describe no OpenAPI; "
                    "its interface (HTTP, gRPC, GraphQL...) is unknown",
                )
            )

        data = compose.services.get(service) if compose else None
        if data is not None and data.data_kind == "postgres":
            user = data.environment.get("POSTGRES_USER", "postgres")
            default = data.environment.get("POSTGRES_DB", user)
            if _postgres(world, service, name, user, default):
                ran.add(POSTGRES_READONLY.ref)
    if undeclared:
        world.blind_spots.append(
            BlindSpot(
                what="services " + ", ".join(sorted(set(undeclared))),
                why=f"running, but not declared in {compose.path if compose else 'any compose file read'}: "
                "their environment, build and dependencies are unknown",
            )
        )
    return ran
