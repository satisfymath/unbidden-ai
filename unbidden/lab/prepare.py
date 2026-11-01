"""What a project itself uses to test and run its API, read from its repository, each with where it was found.

Stage 10: Spoolman tests its API only over HTTP, against the server its compose file starts with a database; the
lab could only measure by writing one more in-process test of `tests/`, which the project never writes, and sixteen
workload attempts failed on fixtures, imports and settings that exist only in the project's integration setup
(docs/bench/stage10-diagnosis.md). The lab now measures the way the project tests its API:

- `in_process`: the project's tests call the API inside the application's process (a `TestClient`, an ASGI
  transport); the workload is one more test of the CI's test command, with the fixtures visible where it runs.
- `served`: the project's API tests call a running server; the lab starts the application as the project starts it
  (its compose service's environment and database, its Dockerfile's or entrypoint's server command), seeds the
  database itself, and a fixed driver sends the request.

Nothing here names an application: every rule reads a kind of file every project may have.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.observe.compose import Service, load_compose

IN_PROCESS = re.compile(r"\bTestClient\(|\bASGITransport\(|AsyncClient\([^)]*\bapp\s*=|\bLifespanManager\(")
OVER_HTTP = re.compile(r"""(?:httpx|requests)\.(?:get|post|put|patch|delete|request)\(\s*(?:f?["']https?://|URL\b|\w*url\b)"""
                       r"""|^\s*\w*URL\s*=\s*f?["']https?://""", re.M | re.I)  # fmt: skip
_APP_IMPORT = re.compile(
    r"^\s*from\s+(?!tests?\b|fastapi\b|starlette\b|httpx\b)[\w.]+\s+import\s+[^\n]*\b(app|application|"
    r"create_app|get_app|get_application|create_application|\w+_app)\b",
    re.M,
)
_OWN_APP = re.compile(r"=\s*(?:FastAPI|Starlette)\(")
SERVERS = re.compile(r"\b(uvicorn|gunicorn|hypercorn|granian|daphne)\b|\bpython3?\s+-m\s+\w+|\bfastapi\s+run\b")
_RUNNER_PREFIX = re.compile(r"^(?:uv\s+(?:--\S+\s+)*run\s+(?:--\S+\s+)*|poetry\s+run\s+|pipenv\s+run\s+|pdm\s+run\s+)")


@dataclass(frozen=True)
class Evidence:
    kind: str  # what it tells: "api_tests", "server_command", "server_env", "database", "artifact", ...
    source: str  # file (and line) or job it was read from
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "source": self.source, "detail": self.detail}


@dataclass(frozen=True)
class ServerRecipe:
    """How the project starts its application: the command, its environment, its database, the port it listens on,
    and the build artifacts its image copies in that the repository does not hold (created empty: the API does not
    read them; said in the evidence)."""

    command: str
    port: int
    env: dict[str, str]
    database: Service
    placeholders: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass
class Inventory:
    api_tests: str  # "in_process", "over_http" or "none", for the tests the CI's test command runs
    server: ServerRecipe | None
    evidence: list[Evidence] = field(default_factory=list[Evidence])
    why_not_served: str = ""

    @property
    def mode(self) -> str | None:
        """How the lab measures: as the project's own API tests run; None when neither way is supported."""
        if self.api_tests == "in_process":
            return "in_process"
        if self.server is not None:
            return "served"
        return None


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def api_test_style(repo: Path, rev: str, test_dirs: list[str]) -> tuple[str, list[Evidence]]:
    """Whether the tests in `test_dirs` (those the CI's test command runs) call the API in-process; else whether any
    of the repository's tests call it over HTTP."""
    files = [f for f in _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines() if f.endswith(".py")]
    tests = [f for f in files if re.search(r"(^|/)(tests?|testing|tests_\w+)/", f)]
    inside = [f for f in tests if any(f == d or f.startswith(d.rstrip("/") + "/") for d in test_dirs)] or tests
    for path in inside:
        text = _git(repo, "show", f"{rev}:{path}")
        m = IN_PROCESS.search(text)
        # The project's own application, imported from its package; a test that builds its own `FastAPI()` to try a
        # middleware (Spoolman's host guard) says nothing about how the API is tested.
        imported = _APP_IMPORT.search(text)
        if m and imported and not _OWN_APP.search(text):
            line = text[: m.start()].count("\n") + 1
            return "in_process", [
                Evidence(
                    "api_tests", f"{path}:{line}", f"in-process client of the application ({imported.group(0)[:80]})"
                )
            ]
    for path in tests:
        text = _git(repo, "show", f"{rev}:{path}")
        if m := OVER_HTTP.search(text):
            line = text[: m.start()].count("\n") + 1
            return "over_http", [Evidence("api_tests", f"{path}:{line}", f"tests call a server: {m.group(0)[:80]}")]
    return "none", []


def _compose_files(repo: Path, rev: str) -> list[str]:
    return [f for f in _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()
            if re.search(r"(^|/)(docker-)?compose[\w.-]*\.ya?ml$", f)]  # fmt: skip


def _dockerfile_server(repo: Path, rev: str, dockerfile: str) -> tuple[str, int | None, list[Evidence]] | None:
    """The server command a Dockerfile runs: its CMD or ENTRYPOINT, or the entrypoint script's server line, with the
    script's defaults for the variables it uses (`PORT=${PORT:-8000}`)."""
    text = _git(repo, "show", f"{rev}:{dockerfile}")
    if not text:
        return None
    exposed = [int(p) for p in re.findall(r"^\s*EXPOSE\s+(\d+)", text, re.M)]
    env = {m.group(1): m.group(2).strip("\"'") for m in re.finditer(r"^\s*ENV\s+(\w+)[=\s]+(\S+)", text, re.M)}
    for keyword in ("CMD", "ENTRYPOINT"):
        for m in reversed(list(re.finditer(rf"^\s*{keyword}\s+(.+)$", text, re.M))):
            raw = m.group(1).strip()
            parts = _exec_form(raw)
            command = " ".join(parts)
            line = text[: m.start()].count("\n") + 1
            if SERVERS.search(command):
                prefix = "".join(f"{k}={shlex.quote(v)}; " for k, v in env.items())
                return prefix + _RUNNER_PREFIX.sub("", command), (exposed or [None])[0], [
                    Evidence("server_command", f"{dockerfile}:{line}", command[:200])]  # fmt: skip
            script = next((p for p in parts if p.endswith(".sh")), None)
            if script:
                found = _script_server(repo, rev, script)
                if found:
                    command, source = found
                    return command, (exposed or [None])[0], [Evidence("server_command", source, command[:200])]
    return None


def _exec_form(raw: str) -> list[str]:
    if raw.startswith("["):
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', raw)
        if parts[:2] in (["sh", "-c"], ["bash", "-c"]) and len(parts) > 2:
            return shlex.split(parts[2])
        return parts
    return shlex.split(raw)


def _script_server(repo: Path, rev: str, script: str) -> tuple[str, str] | None:
    """The server line of an entrypoint script in the repository, with its `X=${X:-default}` defaults before it."""
    candidates = [script.lstrip("/")]
    files = set(_git(repo, "ls-tree", "-r", "--name-only", rev).splitlines())
    name = script.rsplit("/", 1)[-1]
    candidates += [f for f in files if f.rsplit("/", 1)[-1] == name]
    path = next((c for c in candidates if c in files), None)
    if path is None:
        return None
    text = _git(repo, "show", f"{rev}:{path}")
    defaults = [ln.strip() for ln in text.splitlines() if re.match(r"^\s*\w+=\$\{\w+:-[^}]*\}\s*$", ln)]
    for i, line in reversed(list(enumerate(text.splitlines(), 1))):
        stripped = line.strip().removeprefix("exec ").strip()
        if SERVERS.search(stripped) and not stripped.startswith("#"):
            command = _RUNNER_PREFIX.sub("", stripped).replace('"$@"', "").strip()
            return "; ".join([*defaults, command]), f"{path}:{i}"
    return None


def _artifacts(repo: Path, rev: str, dockerfile: str, files: set[str]) -> list[Evidence]:
    """Paths the image copies in that the repository does not hold: a build output of another stage or of the
    build's context (a compiled web client). The lab creates them empty; the API under test does not read them."""
    text = _git(repo, "show", f"{rev}:{dockerfile}")
    workdir = ""
    out: list[Evidence] = []
    for i, line in enumerate(text.splitlines(), 1):
        if m := re.match(r"^\s*WORKDIR\s+(\S+)", line):
            workdir = m.group(1).rstrip("/")
        m = re.match(r"^\s*COPY\s+(?P<flags>(?:--\S+\s+)*)(?P<args>.+)$", line)
        if not m:
            continue
        args = m.group("args").split()
        if len(args) < 2:
            continue
        *sources, dest = args
        staged = "--from=" in m.group("flags")
        for source in sources:
            rel = source.lstrip("./")
            if staged:
                # Copied from another stage into the application's tree: the destination, relative to the tree.
                target = dest
                if workdir and dest.startswith(workdir + "/"):
                    target = dest[len(workdir) + 1 :]
                target = target.lstrip("./")
                if dest.startswith("/") and target == dest.lstrip("/"):
                    continue  # outside the application's tree (a binary into /bin)
            else:
                target = rel
            if not target or "*" in target or "$" in target:
                continue
            if target in files or any(f.startswith(target.rstrip("/") + "/") for f in files):
                continue
            if staged or not any(f.startswith(rel.split("/")[0] + "/") for f in files) or rel not in files:
                out.append(Evidence("artifact", f"{dockerfile}:{i}", target))
    return list({e.detail: e for e in out}.values())


def server_recipe(repo: Path, rev: str) -> tuple[ServerRecipe | None, list[Evidence], str]:
    """How the project runs its application with a database: from a compose file whose application service talks to
    a database service in the same file, and the server command its compose service, Dockerfile or entrypoint
    gives. None with the reason when the repository does not say."""
    files = set(_git(repo, "ls-tree", "-r", "--name-only", rev).splitlines())
    why = "no compose file in the repository runs the application with a database"
    for path in sorted(_compose_files(repo, rev), key=lambda p: ("postgres" not in p, p.count("/"), p)):
        compose = load_compose(repo, rev, [path])
        if compose is None:
            continue
        app = compose.app_service_for(".")
        databases = [s for s in compose.data_services() if s.data_kind == "postgres"]
        if app is None or not databases or app.data_kind is not None:
            continue
        database = next((d for d in databases if d.name in app.depends_on), databases[0])
        evidence = [
            Evidence("database", path, f"service {database.name}: {database.image}"),
            Evidence("server_env", path, f"service {app.name}: {', '.join(sorted(app.environment))}"),
        ]
        dockerfile = app.dockerfile or next((f for f in ("Dockerfile", "docker/Dockerfile") if f in files), None)
        server = _dockerfile_server(repo, rev, dockerfile) if dockerfile else None
        if server is None:
            why = f"{path}: the application's server command is not in its compose file, Dockerfile or entrypoint"
            continue
        command, exposed, found = server
        port = exposed
        for spec in app.ports:
            if spec.split(":")[-1].split("/")[0].isdigit():
                port = int(spec.split(":")[-1].split("/")[0])
        named = re.search(r"--port[= ](\d+)", command)
        port = int(named.group(1)) if named else port
        if port is None:
            port = int(
                re.sub(r"\D", "", next((v for k, v in app.environment.items() if k.endswith("PORT")), "")) or 8000
            )
        artifacts = _artifacts(repo, rev, dockerfile, files) if dockerfile else []
        recipe = ServerRecipe(command=command, port=port, env=dict(app.environment), database=database,
                              placeholders=tuple(e.detail for e in artifacts),
                              evidence=(*evidence, *found, *artifacts))  # fmt: skip
        return recipe, list(recipe.evidence), ""
    return None, [], why


def inventory(repo: Path, rev: str, test_dirs: list[str]) -> Inventory:
    style, evidence = api_test_style(repo, rev, test_dirs)
    if style == "in_process":
        return Inventory(style, None, evidence)
    server, found, why = server_recipe(repo, rev)
    return Inventory(style, server, [*evidence, *found], why)
