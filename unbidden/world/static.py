"""What the repository says about the system, read from git without running anything. Everything here is
`observed` when it is literally declared (a compose service) and `inferred` when it is read from code."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import BlindSpot, Relation, Resource, WorldModel
from unbidden.observe.ci import ci_test_plan
from unbidden.observe.compose import Compose, Service, load_compose
from unbidden.observe.stack import Stack

OBSERVED, INFERRED = EpistemicStatus.OBSERVED, EpistemicStatus.INFERRED

_TABLE_CLASS = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", re.MULTILINE)
_TABLENAME = re.compile(r"__tablename__\s*=\s*[\"'](\w+)[\"']")
_ROUTE = re.compile(r"@(?P<obj>\w+)\.(?P<method>get|post|put|patch|delete)\(\s*[\"'](?P<path>[^\"']*)[\"']")
_HOST_KEY = re.compile(r"(?:^|_)(?:HOST|HOSTNAME|SERVER)$", re.IGNORECASE)
_ROUTER = re.compile(r"^(?P<obj>\w+)\s*=\s*\w*Router\((?P<args>[^)]*)\)", re.MULTILINE)
_PREFIX = re.compile(r"prefix\s*=\s*[\"'](?P<prefix>[^\"']+)[\"']")


def _ref(kind: str, locator: str, note: str | None = None) -> EvidenceRef:
    return EvidenceRef(kind=kind, locator=locator, note=note)  # type: ignore[arg-type]


def _files(repo: Path, rev: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", rev], capture_output=True, text=True)
    return out.stdout.splitlines()


def _show(repo: Path, rev: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True).stdout


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def service_references(compose: Compose, service: Service) -> list[tuple[str, str, str]]:
    """(key, other service, value) for each environment value that addresses another service of the project:
    `host:port`, a URL with that host, or exactly the service's name under a key that says it is a host
    (`FLAGD_HOST=flagd`, `ADMINER_DEFAULT_SERVER=db`). Any other bare word is not an address
    (`SERVICE_NAME=cart` names, it does not call)."""
    found: list[tuple[str, str, str]] = []
    for key, value in sorted(service.environment.items()):
        for other in compose.services:
            if other == service.name:
                continue
            name = re.escape(other)
            hostish = _HOST_KEY.search(key) is not None and value.strip() == other
            if hostish or re.search(rf"(?:^|[\s,;=@/])({name}):\d+|://{name}(?:[:/]|$)", value):
                found.append((key, other, value))
    return found


def discover_static(
    repo: Path, rev: str, stack: Stack, world: WorldModel, compose_files: list[str] | None = None
) -> None:
    files = _files(repo, rev)
    world.add(
        Resource(
            id=f"repo:{repo.name}",
            kind="repo",
            name=repo.name,
            attributes={"rev": rev, "languages": stack.languages},
            status=OBSERVED,
            confidence=1.0,
            evidence=[_ref("commit", rev)],
        )
    )

    compose = load_compose(repo, rev, compose_files)
    if compose is None:
        world.blind_spots.append(
            BlindSpot(what="services", why="no compose file; services are not declared in the repository")
        )
    else:
        for service in compose.services.values():
            kind = "database" if service.data_kind in ("postgres", "mysql", "mariadb", "mongo") else "service"
            world.add(
                Resource(
                    id=f"service:{service.name}",
                    kind=kind,
                    name=service.name,
                    attributes={
                        "image": service.image,
                        "build": service.dockerfile or service.build_context,
                        "ports": list(service.ports),
                        "engine": service.data_kind,
                    },
                    status=OBSERVED,
                    confidence=1.0,
                    evidence=[_ref("config", f"{compose.path}#services.{service.name}")],
                )
            )
        for service in compose.services.values():
            for dep in service.depends_on:
                world.relate(
                    Relation(
                        src=f"service:{service.name}",
                        dst=f"service:{dep}",
                        predicate="depends_on",
                        status=OBSERVED,
                        confidence=1.0,
                        evidence=[_ref("config", f"{compose.path}#services.{service.name}.depends_on")],
                    )
                )
            for key, value in service.environment.items():
                for other in compose.data_services():
                    if re.search(rf"@{re.escape(other.name)}(?::\d+)?/", value):
                        world.relate(
                            Relation(
                                src=f"service:{service.name}",
                                dst=f"service:{other.name}",
                                predicate="uses_database",
                                status=OBSERVED,
                                confidence=1.0,
                                evidence=[_ref("config", f"{compose.path}#services.{service.name}.environment.{key}")],
                            )
                        )
        for service in compose.services.values():
            for key, other, value in service_references(compose, service):
                world.relate(
                    Relation(
                        src=f"service:{service.name}",
                        dst=f"service:{other}",
                        predicate="uses_database" if compose.services[other].data_kind else "calls",
                        status=INFERRED,
                        confidence=0.8,
                        evidence=[
                            _ref("config", f"{compose.path}#services.{service.name}.environment.{key}", value[:120])
                        ],
                    )
                )
        proxies = [s.name for s in compose.services.values() if "traefik" in (s.image or "").split("/")[-1]]
        for service in compose.services.values():
            rule = next((label for label in service.labels if label.startswith("traefik.http.routers.")), None)
            if not proxies or rule is None or "traefik.enable=false" in service.labels:
                continue
            for proxy in proxies:
                world.relate(
                    Relation(
                        src=f"service:{proxy}",
                        dst=f"service:{service.name}",
                        predicate="calls",
                        status=INFERRED,
                        confidence=0.8,
                        evidence=[_ref("config", f"{compose.path}#services.{service.name}.labels", rule[:120])],
                    )
                )
        if compose.unresolved:
            world.blind_spots.append(
                BlindSpot(
                    what="compose variables " + ", ".join(compose.unresolved),
                    why="not defined in the tracked .env; their values are unknown",
                )
            )

    for language in stack.languages:
        plan = ci_test_plan(repo, rev, language)
        if plan is not None:
            world.add(
                Resource(
                    id=f"ci_job:{plan.workflow}#{plan.job}",
                    kind="ci_job",
                    name=plan.job,
                    attributes={"steps": [s.command for s in plan.steps], "services": list(plan.services)},
                    status=OBSERVED,
                    confidence=1.0,
                    evidence=[_ref("config", f".github/workflows/{plan.workflow}")],
                )
            )

    py_files = [f for f in files if f.endswith(".py") and "/tests/" not in f and not f.startswith("tests/")]
    for path in py_files:
        text = _show(repo, rev, path)
        if "table=True" in text or "__tablename__" in text:
            for match in _TABLE_CLASS.finditer(text):
                cls, bases = match.group(1), match.group(2)
                body = text[match.end() : match.end() + 2000]
                explicit = _TABLENAME.search(body.split("\nclass ", 1)[0])
                if "table=True" not in bases and explicit is None:
                    continue
                table = explicit.group(1) if explicit else cls.lower()
                world.add(
                    Resource(
                        id=f"table:{table}",
                        kind="table",
                        name=table,
                        attributes={"model": cls, "file": path},
                        status=INFERRED,
                        confidence=0.8,
                        evidence=[_ref("file", f"{path}:{text[: match.start()].count(chr(10)) + 1}", f"class {cls}")],
                    )
                )
        if _ROUTE.search(text):
            prefixes = {  # each router's own prefix: one file may declare several
                m.group("obj"): p.group("prefix") if (p := _PREFIX.search(m.group("args"))) else ""
                for m in _ROUTER.finditer(text)
            }
            for match in _ROUTE.finditer(text):
                route_path = prefixes.get(match.group("obj"), "") + match.group("path")
                if not route_path:  # the router's mount point alone: nothing in the file says where that is
                    continue
                route = f"{match.group('method').upper()} {route_path}"
                line = text[: match.start()].count("\n") + 1
                world.add(
                    Resource(
                        id=f"endpoint:{route}",
                        kind="endpoint",
                        name=route,
                        attributes={"file": path, "line": line, "prefix_known": False},
                        status=INFERRED,
                        confidence=0.7,
                        evidence=[_ref("file", f"{path}:{line}")],
                    )
                )
    if any(r.kind == "endpoint" for r in world.resources.values()):
        world.blind_spots.append(
            BlindSpot(
                what="full endpoint paths",
                why="mount prefixes are set at runtime; read from the live OpenAPI when the app runs",
            )
        )
    if stack.node is None and any(f.endswith(("package.json",)) for f in files):
        world.blind_spots.append(BlindSpot(what="frontend", why="its JavaScript package was not analyzed"))
