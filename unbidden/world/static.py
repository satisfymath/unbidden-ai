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
_INCLUDE = re.compile(r"(?P<obj>\w+)\.include_router\(\s*(?P<target>[\w.]+)")
_FROM_IMPORT = re.compile(r"^from\s+(?P<mod>\.*[\w.]*)\s+import\s+(?:\((?P<group>[^)]*)\)|(?P<line>[^\n]+))", re.M)


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
    sources = {path: _show(repo, rev, path) for path in py_files}
    mounts = _mounts(sources)
    for path, text in sources.items():
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
            own = _own_prefixes(text)
            for match in _ROUTE.finditer(text):
                line = text[: match.start()].count("\n") + 1
                for mount in mounts.get((path, match.group("obj")), [""]):
                    route_path = mount + own.get(match.group("obj"), "") + match.group("path")
                    if not route_path:  # the router's mount point alone: nothing in the code says where that is
                        continue
                    route = f"{match.group('method').upper()} {route_path}"
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


def _own_prefixes(text: str) -> dict[str, str]:
    """Each router's own prefix (`APIRouter(prefix=...)`): one file may declare several."""
    return {
        m.group("obj"): p.group("prefix") if (p := _PREFIX.search(m.group("args"))) else ""
        for m in _ROUTER.finditer(text)
    }


def _call_args(text: str, start: int) -> str:
    """The text of a call's arguments from just after its opening parenthesis, across lines, to the matching one."""
    depth = 1
    for i in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i]
    return text[start:]


def _module_file(module: str, files: set[str]) -> str | None:
    base = module.replace(".", "/")
    for candidate in (f"{base}.py", f"{base}/__init__.py"):
        found = [f for f in files if f == candidate or f.endswith("/" + candidate)]  # src/ and similar roots
        if len(found) == 1:
            return found[0]
    return None


def _imports(path: str, text: str, files: set[str]) -> dict[str, tuple[str, str | None]]:
    """`alias -> (file, attribute)`: `from a.b import c` is module c's file when c is a module, else b's attribute c."""
    out: dict[str, tuple[str, str | None]] = {}
    for m in _FROM_IMPORT.finditer(text):
        module = m.group("mod")
        if module.startswith("."):
            dots = len(module) - len(module.lstrip("."))
            parent = path.rsplit("/", dots)[0] if path.count("/") >= dots else ""
            module = ".".join(x for x in (parent.replace("/", "."), module.lstrip(".")) if x)
        for name in (m.group("group") or m.group("line") or "").split("#")[0].split(","):
            original, _, alias = name.strip().partition(" as ")
            if not original.isidentifier():
                continue
            alias = alias.strip() or original
            if submodule := _module_file(f"{module}.{original}" if module else original, files):
                out[alias] = (submodule, None)
            elif owner := _module_file(module, files):
                out[alias] = (owner, original)
    return out


def _mounts(sources: dict[str, str]) -> dict[tuple[str, str], list[str]]:
    """Where each router is mounted: `(file, router) -> [literal path prefixes]`, followed through `include_router`.

    FastAPI's full path is the including router's mount and own prefix, then the include's `prefix=`, then the
    router's own prefix and the route. A prefix that is not a literal (`settings.api_prefix`) is left out: the live
    OpenAPI supplies it, and reconciling matches on the path's end; nothing above an unknown prefix is prepended (a
    wrong prefix would stop that match, a missing one does not). A module-level string constant counts as a literal.
    A router mounted twice gets both paths.
    """
    files = set(sources)
    edges: dict[tuple[str, str], list[tuple[tuple[str, str], str | None]]] = {}
    for path, text in sources.items():
        if "include_router(" not in text:
            continue
        aliases = _imports(path, text, files)
        own = _own_prefixes(text)
        for m in _INCLUDE.finditer(text):
            args = _call_args(text, m.start("target"))
            head, _, attr = m.group("target").partition(".")
            if head in aliases:  # `comments.router` (a module's router) or `api_router` (a router imported by name)
                file, imported = aliases[head]
                if imported is None and not attr:
                    continue
                child = (file, imported or attr)
            elif not attr:  # a router of the same file
                child = (path, head)
            else:
                continue
            given = re.search(r"\bprefix\s*=\s*([^,)\s]+)", args)
            if given is None:
                step: str | None = ""
            elif literal := re.fullmatch(r"[\"']([^\"']*)[\"']", given.group(1)):
                step = literal.group(1)
            elif constant := re.search(rf"^{re.escape(given.group(1))}\s*=\s*[\"']([^\"']*)[\"']", text, re.M):
                step = constant.group(1)  # a module-level constant: `user_prefix = "/users"`
            else:
                step = None  # set at runtime: what is above it is unknown here
            parent = (path, m.group("obj"))
            edges.setdefault(child, []).append((parent, None if step is None else own.get(parent[1], "") + step))

    def resolve(router: tuple[str, str], seen: frozenset[tuple[str, str]]) -> list[str]:
        if router not in edges or router in seen:
            return [""]
        return sorted({
            "" if step is None else up + step
            for parent, step in edges[router]
            for up in ([""] if step is None else resolve(parent, seen | {router}))
        })  # fmt: skip

    return {router: resolve(router, frozenset()) for router in edges}
