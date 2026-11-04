"""Unbidden brings a repository's application up by itself, from the repository's own compose file (0.18.0).

What a person used to do by hand for each lab (campaign 13's `bench/campaign13/labs.py`), done the same way for any
repository with a compose file, under the mandate's `operations.self_host`:

- the compose file the repository ships, rendered by Docker Compose itself (`docker compose config`), with its
  variables taken from the repository's tracked example env file and, for what is still missing, values generated
  here (secrets are random, never copied from anywhere); missing `env_file`s are created from their example;
- host ports remapped to free ones on 127.0.0.1 (nothing listens outside this machine), fixed container names dropped,
  everything labelled with an isolated project `unbidden-<workspace>`, kept in `.unbidden/host/`;
- the project started (`up -d --build`), its migrations run when the database is still empty (alembic, Django's
  `migrate`, `flask db upgrade`, detected from the repository), then synthetic rows seeded from the database's own
  catalog (`lab/seed.py`, bounded and labelled), when it is PostgreSQL;
- a health URL found on the published ports (an OpenAPI health route, the usual health paths, Django's admin login,
  then `/`);
- the deploy steps written into the mandate as this same command (`unbidden host up --deploy --build`), so a merged
  change is deployed exactly as it was brought up, and the rollback drill run.

Every step is recorded with its outcome; a step that fails ends the bring-up with the reason, never a guess.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from unbidden.observe.compose import COMPOSE_FILES, parse_dotenv

HOST_DIR = Path(".unbidden") / "host"
STATE = HOST_DIR / "state.json"
RENDERED = HOST_DIR / "compose.yml"
ENV_FILE = HOST_DIR / "env"
EXAMPLE_ENVS = (".env.example", ".env.sample", ".env.template", "env.example", ".env.dist", "example.env")
OVERRIDES = ("compose.override.yml", "compose.override.yaml", "docker-compose.override.yml",
             "docker-compose.override.yaml")  # fmt: skip
SECRET_NAME = re.compile(r"PASS|SECRET|KEY|TOKEN|SALT", re.IGNORECASE)
HEALTH_PATHS = ("/health", "/healthz", "/api/health", "/api/v1/health", "/health/", "/api/healthz", "/ping",
                "/admin/login/", "/login", "/")  # fmt: skip
OPENAPI_PATHS = ("/openapi.json", "/api/openapi.json", "/api/v1/openapi.json", "/docs/openapi.json")
UP_TIMEOUT_S = 3600.0
HEALTH_WAIT_S = 600.0
SEED_ROWS = 20_000  # rows of the referencing table per foreign key seeded, spread over SEED_OWNERS parents
SEED_OWNERS = 500
SEED_PLANS = 6
PROBE_EVERY_S = 1.0
DOCUMENTED_GRACE_S = 60.0  # how long a documented health route is waited for
PLACEHOLDERS = ("", "changeme", "change_me", "secret", "password", "your-secret-key", "changethis")
_PLACEHOLDER = re.compile(r"change|your|example|here|xxx|dummy|todo|replace|insert|generate|[<>]|^secret$", re.I)


def placeholder(value: str) -> bool:
    """An example file's stand-in for a secret (`your-secret-key-here`, `<generate>`, a short word): TimeTracker
    refuses to start with its example SECRET_KEY, and nobody should run with one."""
    v = value.strip().strip("'\"")
    return v.lower() in PLACEHOLDERS or bool(_PLACEHOLDER.search(v)) or len(v) < 16


PSQL = (
    'psql -v ON_ERROR_STOP=1 -q -At -F "$(printf "\\t")" '
    '-U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-${POSTGRES_USER:-postgres}}"'
)  # tab-separated rows
Run = Callable[..., subprocess.CompletedProcess[str]]
Get = Callable[[str], "httpx.Response | None"]


@dataclass
class HostResult:
    ok: bool = False
    project: str = ""
    health_url: str | None = None
    ports: dict[str, int] = field(default_factory=dict[str, int])  # "service:container_port" -> host port
    deploy_steps: list[list[str]] = field(default_factory=list[list[str]])
    drill: dict[str, Any] | None = None
    why: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    migrated: str | None = None
    seeded: dict[str, int] = field(default_factory=dict[str, int])
    generated_env: list[str] = field(default_factory=list[str])  # names only, never values

    def step(self, name: str, ok: bool, detail: str = "", seconds: float = 0.0) -> None:
        self.steps.append({"step": name, "ok": ok, "detail": detail[-800:], "seconds": round(seconds, 1)})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_name(repo: Path) -> str:
    return "unbidden-" + (re.sub(r"[^a-z0-9]+", "-", repo.resolve().name.lower()).strip("-") or "app")


def tracked(repo: Path, path: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", path], capture_output=True,
                          check=False).returncode == 0  # fmt: skip


def compose_files(repo: Path) -> list[str]:
    """The repository's own compose file (the first default name it tracks) and its override file, if tracked."""
    main = next((name for name in COMPOSE_FILES if tracked(repo, name)), None)
    if main is None:
        return []
    return [main, *[name for name in OVERRIDES if tracked(repo, name)]]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def load_state(repo: Path) -> dict[str, Any]:
    path = repo / STATE
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(repo: Path, state: dict[str, Any]) -> None:
    (repo / HOST_DIR).mkdir(parents=True, exist_ok=True)
    (repo / STATE).write_text(json.dumps(state, indent=1))


def referenced_variables(texts: list[str]) -> list[str]:
    """Variables a compose file needs without a default (`${NAME}`, `${NAME:?err}`, `$NAME`)."""
    found: list[str] = []
    for text in texts:
        for m in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[-?][^}]*)?\}|\$([A-Za-z_][A-Za-z0-9_]*)", text):
            name, op = m.group(1) or m.group(3), m.group(2) or ""
            if op.lstrip(":").startswith("-"):
                continue  # has a default
            if name not in found:
                found.append(name)
    return found


def env_values(repo: Path, texts: list[str], kept: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """The values the compose file is rendered with: the repository's tracked example env file, then generated
    values for what it needs and does not say (random for secrets). `kept` (the previous bring-up's) wins, so a
    redeploy keeps the same database password. Returns the values and the names generated here."""
    values: dict[str, str] = {}
    for name in EXAMPLE_ENVS:
        if tracked(repo, name):
            values.update({k: v for k, v in parse_dotenv((repo / name).read_text(errors="replace")).items() if v})
            break
    generated: list[str] = []
    for name in referenced_variables(texts):
        if name in values or name in kept:
            continue
        values[name] = secrets.token_hex(16) if SECRET_NAME.search(name) else "unbidden"
        generated.append(name)
    for name, value in list(values.items()):
        if SECRET_NAME.search(name) and name not in kept and placeholder(value):
            values[name] = secrets.token_hex(16)  # an example placeholder is never a secret anyone should run with
            generated.append(name)
    return {**values, **kept}, generated


def missing_env_files(repo: Path, raw_texts: list[str]) -> list[str]:
    """`env_file:` entries the compose file names that do not exist in the checkout."""
    missing: list[str] = []
    for text in raw_texts:
        data = yaml.safe_load(text) or {}
        for spec in (data.get("services") or {}).values():
            if not isinstance(spec, dict):
                continue
            entries = spec.get("env_file") or []
            for entry in [entries] if isinstance(entries, str | dict) else entries:
                path = entry.get("path") if isinstance(entry, dict) else entry
                required = entry.get("required", True) if isinstance(entry, dict) else True
                if isinstance(path, str) and required and not (repo / path).exists() and path not in missing:
                    missing.append(path)
    return missing


def create_env_files(repo: Path, paths: list[str]) -> list[str]:
    """Each missing env file from its example beside it (`.env` from `.env.example`), else empty; kept out of git."""
    created: list[str] = []
    for path in paths:
        target = repo / path
        beside = [target.with_name(target.name + s) for s in (".example", ".sample", ".template", ".dist")]
        # codex-lb: `env_file: .env.local`, documented by the repository's `.env.example`.
        general = [repo / name for name in EXAMPLE_ENVS]
        example = next((e for e in [*beside, *general] if e.exists()), None)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = example.read_text(errors="replace") if example is not None else ""
        lines = []
        for line in text.splitlines():
            key, sep, value = line.partition("=")
            if sep and SECRET_NAME.search(key) and not key.strip().startswith("#") and placeholder(value):
                line = f"{key}={secrets.token_hex(16)}"
            lines.append(line)
        target.write_text("\n".join(lines) + ("\n" if lines else ""))
        exclude = repo / ".git" / "info" / "exclude"
        if exclude.parent.exists():
            have = exclude.read_text().splitlines() if exclude.exists() else []
            if path not in have:
                exclude.write_text("\n".join([*have, path]) + "\n")
        created.append(path + (f" (from {example.name})" if example is not None else " (empty)"))
    return created


def rewrite(config: dict[str, Any], project: str, ports: dict[str, int]) -> dict[str, Any]:
    """The rendered project with every published port on 127.0.0.1 and a free host port (the same one as the last
    bring-up), no fixed container names, and the project's label on every service."""
    for name, spec in (config.get("services") or {}).items():
        spec.pop("container_name", None)
        published = []
        for port in spec.get("ports") or []:
            if not isinstance(port, dict):
                continue
            target = int(port.get("target") or 0)
            if not target:
                continue
            key = f"{name}:{target}"
            ports.setdefault(key, free_port())
            published.append({"target": target, "published": str(ports[key]), "host_ip": "127.0.0.1",
                              "protocol": port.get("protocol", "tcp"), "mode": "ingress"})  # fmt: skip
        if published:
            spec["ports"] = published
        labels: dict[str, str] = {}
        raw = spec.get("labels") or {}
        if isinstance(raw, list):
            for item in raw:
                key, _, value = str(item).partition("=")
                labels[key] = value
        elif isinstance(raw, dict):
            labels = {str(k): str(v) for k, v in raw.items()}
        spec["labels"] = {**labels, "dev.unbidden.host": project}
    config["name"] = project
    return config


def compose_argv(repo: Path, project: str) -> list[str]:
    return ["docker", "compose", "-p", project, "--project-directory", str(repo), "-f", str(repo / RENDERED)]


def render(repo: Path, files: list[str], project: str, run: Run) -> dict[str, Any]:
    argv = ["docker", "compose", "-p", project, "--project-directory", str(repo),
            *[x for f in files for x in ("-f", str(repo / f))], "--env-file", str(repo / ENV_FILE),
            "config", "--format", "json"]  # fmt: skip
    done = run(argv, cwd=repo, capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"`docker compose config` failed: {done.stderr.strip()[-600:]}")
    return json.loads(done.stdout)


def app_ports(config: dict[str, Any], ports: dict[str, int]) -> list[tuple[str, int]]:
    """(service, host port) of the services that may be the application: not a database, not a tool beside it (a
    mail catcher, a database console: misago's mailpit answered `/` before misago did); the services built from the
    repository first, then the others in the compose file's order."""
    data = re.compile(r"(postgres|mysql|mariadb|redis|mongo|valkey|rabbitmq|memcached|minio|elasticsearch)", re.I)
    tools = re.compile(
        r"(mailpit|mailhog|maildev|mailcatcher|smtp4dev|adminer|pgadmin|phpmyadmin|redis-?commander"
        r"|redisinsight|mongo-express|jaeger|zipkin|otel|grafana|prometheus|portainer|flower)",
        re.I,
    )
    built, other = [], []
    for name, spec in (config.get("services") or {}).items():
        image = str(spec.get("image") or "")
        if not spec.get("build") and (data.search(image) or tools.search(image) or tools.search(name)):
            continue
        for key, port in ports.items():
            if key.split(":")[0] == name:
                (built if spec.get("build") else other).append((name, port))
    return built + other


def find_health(candidates: list[tuple[str, int]], get: Get, *, documented_only: bool = False) -> str | None:
    """The first health URL that answers below 400 on an application port: an OpenAPI route named health on any
    port first (the API itself, not a frontend that proxies it: codex-lb), then the usual paths, Django's admin
    login, `/`."""
    for _, port in candidates:
        base = f"http://127.0.0.1:{port}"
        for doc in OPENAPI_PATHS:
            response = get(base + doc)
            if response is None or response.status_code != 200:
                continue
            try:
                paths = response.json().get("paths") or {}
            except ValueError:
                continue
            for path, ops in paths.items():
                if "health" in path.lower() and "{" not in path and "get" in ops:
                    hit = get(base + path)
                    if hit is not None and hit.status_code < 400:
                        return base + path
    if documented_only:
        return None
    for path in HEALTH_PATHS:
        for _, port in candidates:
            for scheme in ("http", "https"):  # a proxy that only answers TLS on its published 443 (TimeTracker)
                hit = get(f"{scheme}://127.0.0.1:{port}{path}")
                if hit is not None and hit.status_code < 400:
                    return f"{scheme}://127.0.0.1:{port}{path}"
    return None


def http_get(url: str) -> httpx.Response | None:
    """A GET on this machine's own published port. Certificates are not checked (a local proxy's self-signed one:
    TimeTracker's nginx); a redirect is followed only when it stays on this machine."""
    try:
        response = httpx.get(url, timeout=5, follow_redirects=False, verify=False)
        if response.status_code in (301, 302, 307, 308):
            target = httpx.URL(response.headers.get("location", ""))
            if target.host in ("", "127.0.0.1", "localhost"):
                return httpx.get(response.url.join(target), timeout=5, verify=False, follow_redirects=True)
        return response
    except httpx.HTTPError:
        return None


def migration_command(repo: Path) -> str | None:
    """How the repository migrates its database, when it says (a file the tool needs is tracked)."""
    listed = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=False).stdout
    files = listed.split()
    # Flask-Migrate's layout: alembic.ini and env.py inside migrations/ (TimeTracker); Django has no alembic.ini.
    flask_migrate = any(re.match(r"(.*/)?migrations/alembic\.ini$", f) for f in files)
    if flask_migrate:
        return "flask db upgrade"  # Flask-Migrate keeps alembic.ini inside migrations/ (TimeTracker)
    if any(f.endswith("alembic.ini") for f in files):
        where = next(f for f in files if f.endswith("alembic.ini"))
        directory = str(Path(where).parent)
        return f"cd {directory} && alembic upgrade head" if directory != "." else "alembic upgrade head"
    if any(f.endswith("manage.py") for f in files):
        where = min((f for f in files if f.endswith("manage.py")), key=len)
        directory = str(Path(where).parent)
        prefix = f"cd {directory} && " if directory != "." else ""
        return f"{prefix}python manage.py migrate --noinput"
    if any(re.match(r"(.*/)?migrations/env\.py$", f) for f in files) and "flask" in listed.lower():
        return "flask db upgrade"
    return None


def built_service(config: dict[str, Any]) -> str | None:
    """The service built from the repository itself (the application, not its proxy): where migrations run."""
    services = config.get("services") or {}
    built = [name for name, spec in services.items() if spec.get("build")]
    proxies = re.compile(r"nginx|proxy|caddy|traefik|certgen|cert", re.I)
    app = [name for name in built if not proxies.search(name)]
    return (app or built or [None])[0]


def database_service(config: dict[str, Any]) -> str | None:
    for name, spec in (config.get("services") or {}).items():
        if re.search(r"(^|/)postgres(:|$)|postgis", str(spec.get("image") or "")):
            return name
    return None


def psql_in(repo: Path, project: str, service: str, run: Run) -> Callable[[str], str]:
    """SQL in the project's own Postgres, as its container's superuser (`POSTGRES_USER`, `POSTGRES_DB`)."""

    def psql(sql: str) -> str:
        done = run([*compose_argv(repo, project), "exec", "-T", service, "sh", "-c", PSQL], input=sql,
                   capture_output=True, text=True, timeout=900)  # fmt: skip
        if done.returncode != 0:
            raise RuntimeError(done.stderr.strip()[-400:])
        return done.stdout

    return psql


def tables_in(psql: Callable[[str], str]) -> int:
    out = psql("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';").strip()
    return int(out or 0)


def seed_live(psql: Callable[[str], str]) -> dict[str, int]:
    """Synthetic rows from the database's own catalog for the first foreign keys (`lab/seed.py`), each plan in one
    transaction: a plan the schema refuses (unique values, a cycle) is skipped, not forced."""
    from unbidden.lab.seed import catalog, plan_seed

    seeded: dict[str, int] = {}
    tables = catalog(psql)
    pairs = [(name, col) for name, t in sorted(tables.items()) for col in sorted(t.foreign)]
    for name, col in pairs[:SEED_PLANS]:
        try:
            plan = plan_seed(psql, name, col, SEED_ROWS, SEED_OWNERS)
            psql("BEGIN;\n" + "\n".join(plan.statements) + "\nCOMMIT;")
        except (ValueError, RuntimeError):
            continue
        for table, count in plan.counts.items():
            seeded[table] = seeded.get(table, 0) + count
    return seeded


def deploy_steps() -> list[list[str]]:
    """This command, as the mandate's deploy step: a merged change is rebuilt and started the way it was brought up."""
    return [[sys.executable, "-m", "unbidden.cli", "host", "up", "--deploy", "--build", "--json"]]


def up(repo: Path, *, deploy: bool = False, build: bool = True, run: Run = subprocess.run, get: Get = http_get,
       wait_s: float = HEALTH_WAIT_S) -> HostResult:  # fmt: skip
    """Bring the application up (or, with `deploy`, rebuild and restart it with the same ports and values)."""
    result = HostResult(project=project_name(repo))
    if shutil.which("docker") is None and run is subprocess.run:
        result.why = "Docker is not installed"
        return result
    files = compose_files(repo)
    if not files:
        result.why = "the repository tracks no compose file (compose.yml, docker-compose.yml)"
        return result
    state = load_state(repo)
    texts = [(repo / f).read_text(errors="replace") for f in files]
    started = time.monotonic()
    if not deploy:
        created = create_env_files(repo, missing_env_files(repo, texts))
        if created:
            result.step("env files created from their examples", True, ", ".join(created))
    values, generated = env_values(repo, texts, state.get("env") or {})
    result.generated_env = generated
    (repo / HOST_DIR).mkdir(parents=True, exist_ok=True)
    (repo / ENV_FILE).write_text("".join(f"{k}={json.dumps(v)}\n" for k, v in sorted(values.items())))
    (repo / ENV_FILE).chmod(0o600)
    try:
        config = render(repo, files, result.project, run)
    except (RuntimeError, ValueError) as exc:
        result.why = str(exc)
        result.step("render the compose file", False, str(exc))
        return result
    ports: dict[str, int] = dict(state.get("ports") or {})
    config = rewrite(config, result.project, ports)
    (repo / RENDERED).write_text(yaml.safe_dump(config, sort_keys=False))
    (repo / RENDERED).chmod(0o600)
    result.ports = ports
    save_state(repo, {**state, "env": values, "ports": ports, "files": files})
    result.step("render the compose file", True, f"{', '.join(files)}; {len(config.get('services') or {})} services",
                time.monotonic() - started)  # fmt: skip
    t0 = time.monotonic()
    done = run([*compose_argv(repo, result.project), "up", "-d", *(["--build"] if build else []), "--remove-orphans"],
               cwd=repo, capture_output=True, text=True, timeout=UP_TIMEOUT_S)  # fmt: skip
    result.step("docker compose up", done.returncode == 0, (done.stderr or done.stdout).strip(), time.monotonic() - t0)
    if done.returncode != 0:
        result.why = f"`docker compose up` failed: {(done.stderr or done.stdout).strip()[-600:]}"
        return result
    database = database_service(config)
    psql = psql_in(repo, result.project, database, run) if database else None
    command = migration_command(repo)
    candidates = app_ports(config, ports)
    t0 = time.monotonic()
    deadline = time.monotonic() + wait_s
    health: str | None = state.get("health_url") if deploy else None
    migrated_once = False
    attempts = 0  # migration tries: the app may still be starting
    while time.monotonic() < deadline:
        if psql is not None and command and not migrated_once and candidates and attempts < 3:
            try:
                empty = tables_in(psql) == 0
            except RuntimeError:
                empty = False  # the database is not accepting connections yet
            if empty or deploy:
                attempts += 1
                service = built_service(config) or candidates[0][0]
                mig = run([*compose_argv(repo, result.project), "exec", "-T", service, "sh", "-c", command],
                          cwd=repo, capture_output=True, text=True, timeout=1800)  # fmt: skip
                migrated_once = mig.returncode == 0
                result.migrated = command if migrated_once else None
                result.step(f"migrate ({command}) in {service}", migrated_once, (mig.stderr or mig.stdout).strip())
        if health is not None:
            hit = get(health)
            if hit is not None and hit.status_code < 400:
                break
        else:
            # An API's documented health route first: a frontend answering `/ping` before the API it proxies is up
            # is not the application's health (codex-lb, 0.18.0 rehearsal); a plain path only after a minute.
            health = find_health(
                candidates, get, documented_only=time.monotonic() - t0 < min(DOCUMENTED_GRACE_S, wait_s / 2)
            )
            if health is not None:
                break
        time.sleep(3)
    result.health_url = health if health and (h := get(health)) is not None and h.status_code < 400 else None
    result.step("health", result.health_url is not None, result.health_url or "no URL answered on the app's ports",
                time.monotonic() - t0)  # fmt: skip
    if result.health_url is None:
        app = built_service(config)
        logs = run([*compose_argv(repo, result.project), "logs", "--tail", "30", *([app] if app else [])], cwd=repo,
                   capture_output=True, text=True, timeout=120)  # fmt: skip
        result.why = (f"the application did not answer on {candidates or 'any published port'}; "
                      f"the last lines of {app or 'the project'}: {logs.stdout[-900:]}")  # fmt: skip
        return result
    if psql is not None and not deploy and not state.get("seeded"):
        t0 = time.monotonic()
        try:
            result.seeded = seed_live(psql)
        except (RuntimeError, ValueError) as exc:  # the catalog could not be read: the app runs, unseeded
            result.step("seed synthetic rows", False, str(exc))
        else:
            result.step("seed synthetic rows", True, json.dumps(result.seeded), time.monotonic() - t0)
    result.deploy_steps = deploy_steps()
    result.ok = True
    seeded = result.seeded or state.get("seeded")
    save_state(repo, {**load_state(repo), "health_url": result.health_url, "seeded": seeded, "project": result.project})
    return result


def down(repo: Path, *, run: Run = subprocess.run) -> dict[str, Any]:
    project = project_name(repo)
    if not (repo / RENDERED).exists():
        return {"ok": True, "project": project, "why": "nothing brought up here"}
    done = run([*compose_argv(repo, project), "down", "-v", "--remove-orphans"], cwd=repo, capture_output=True,
               text=True, timeout=600)  # fmt: skip
    if done.returncode == 0:
        state = load_state(repo)
        save_state(repo, {k: v for k, v in state.items() if k not in ("seeded", "health_url")})
    return {"ok": done.returncode == 0, "project": project, "why": None if done.returncode == 0 else done.stderr[-400:]}


_SCHEMA = re.compile(r"(^|/)(migrations?|alembic|versions)/|alembic\.ini$|schema\.(sql|prisma)$", re.IGNORECASE)


def same_schema_previous(repo: Path, depth: int = 30) -> str | None:
    """The latest earlier commit with the same database migrations as HEAD: rolling code back across a migration
    leaves the database ahead of the code (TimeTracker: the older app does not start on the newer schema), so the
    rollback drill proves the rollback that is safe, and says which one it was."""
    revs = subprocess.run(["git", "-C", str(repo), "rev-list", f"--max-count={depth}", "HEAD~1"], capture_output=True,
                          text=True, check=False).stdout.split()  # fmt: skip
    for rev in revs:
        changed = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", rev, "HEAD"], capture_output=True,
                                 text=True, check=False).stdout.split()  # fmt: skip
        if not any(_SCHEMA.search(path) for path in changed):
            return rev
    return None
