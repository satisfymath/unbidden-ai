"""Campaign 12 labs: the application's own services beside a clean checkout at the pin, under ~/unbidden-lab/c12,
with campaign names (`c12-<app>` compose projects, `unbidden.lab.id=c12-<app>` labels) so nothing collides with the
labs of other sessions. Everything here is human preparation, counted as such; the harness never tells Unbidden
anything about the application.

Applications: `fst` (full-stack-fastapi-template: db + backend built from the repository, migrations by its own
prestart script, health GET /api/v1/utils/health-check/) and `spoolman` (built from the repository's Dockerfile,
health GET /api/v1/health). Libraries have no lab: `restore` gives them a clean checkout only.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from bench.ecosystem import ownership

LAB_IDS = {"fst": "c12-fst", "spoolman": "c12-spoolman"}
PORTS = {"fst": (18200, 55500), "spoolman": (18230, 55530)}
REGISTRIES = ["pypi.org", "files.pythonhosted.org", "deb.debian.org", "registry.npmjs.org"]

FST_COMPOSE = """services:
  db:
    image: postgres:18
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d app"]
      interval: 5s
      retries: 20
    environment:
      POSTGRES_PASSWORD: "{pg}"
      POSTGRES_USER: postgres
      POSTGRES_DB: app
    ports:
      - "127.0.0.1:{db_port}:5432"
    volumes:
      - c12-fst-data:/var/lib/postgresql/data
    labels:
{labels}  prestart:
    build:
      context: .
      dockerfile: backend/Dockerfile
    command: bash scripts/prestart.sh
    depends_on:
      db:
        condition: service_healthy
    environment: &env
      PROJECT_NAME: c12-fst
      SECRET_KEY: "{secret}"
      FIRST_SUPERUSER: admin@example.com
      FIRST_SUPERUSER_PASSWORD: "{admin}"
      POSTGRES_SERVER: db
      POSTGRES_PORT: "5432"
      POSTGRES_DB: app
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: "{pg}"
      DATABASE_URL: "postgresql://postgres:{pg}@db:5432/app"
      SMTP_HOST: ""
      EMAILS_FROM_EMAIL: noreply@example.com
      FRONTEND_HOST: http://127.0.0.1:{port}
      ENVIRONMENT: local
    labels:
{labels}  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    depends_on:
      prestart:
        condition: service_completed_successfully
    environment: *env
    ports:
      - "127.0.0.1:{port}:8000"
    labels:
{labels}volumes:
  c12-fst-data:
    labels:
{vlabels}"""

SPOOLMAN_COMPOSE = """services:
  app:
    build: .
    ports:
      - "127.0.0.1:{port}:8000"
    environment:
      SPOOLMAN_DB_TYPE: postgres
      SPOOLMAN_DB_HOST: db
      SPOOLMAN_DB_PORT: "5432"
      SPOOLMAN_DB_NAME: spoolman
      SPOOLMAN_DB_USERNAME: postgres
      SPOOLMAN_DB_PASSWORD: "{pg}"
    depends_on:
      db:
        condition: service_healthy
    labels:
{labels}  db:
    image: postgres:16
    ports:
      - "127.0.0.1:{db_port}:5432"
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: "{pg}"
      POSTGRES_DB: spoolman
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 2s
      retries: 30
    volumes:
      - c12-spoolman-data:/var/lib/postgresql/data
    labels:
{labels}volumes:
  c12-spoolman-data:
    labels:
{vlabels}"""

COMPOSE_FILE = "docker-compose.c12.yml"


def _secrets(lab: Path, app: str, names: list[str]) -> dict[str, str]:
    path = lab / f"{app}-secrets.env"
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in names if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(repo: dict[str, Any], lab: Path) -> Path:
    return lab / (repo.get("lab") or repo["name"])


def restore(repo: dict[str, Any], lab: Path) -> Path:
    """A clean checkout at the pin: the lab's excluded files (compose, .env) stay, branches and `.unbidden` go."""
    target = repo_dir(repo, lab)
    if not (target / ".git").exists():
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "remote", "add", "origin", repo["url"]], check=True)
        subprocess.run(["git", "-C", str(target), "fetch", "-q", "origin", repo["commit"]], check=True, timeout=3600)
    subprocess.run(["git", "-C", str(target), "fetch", "-q", "origin", repo["commit"]], check=False, timeout=3600)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "--detach", "--force", repo["commit"]], check=True)
    subprocess.run(["git", "-C", str(target), "clean", "-q", "-fd"], check=True)  # excluded files stay
    heads = subprocess.run(
        ["git", "-C", str(target), "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for branch in heads:
        subprocess.run(["git", "-C", str(target), "branch", "-q", "-D", branch], check=False)
    shutil.rmtree(target / ".unbidden", ignore_errors=True)
    exclude = target / ".git" / "info" / "exclude"
    have = exclude.read_text().splitlines() if exclude.exists() else []
    wanted = [".unbidden/", COMPOSE_FILE, ".env"]
    exclude.write_text("\n".join([*have, *[w for w in wanted if w not in have]]) + "\n")
    return target


def _compose(app: str, repo: Path) -> list[str]:
    return ["docker", "compose", "-f", COMPOSE_FILE, "-p", LAB_IDS[app]]


def _psql(app: str, repo: Path, database: str, sql: str) -> str:
    out = subprocess.run(
        [
            *_compose(app, repo),
            "exec",
            "-T",
            "db",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-At",
            "-U",
            "postgres",
            "-d",
            database,
        ],
        input=sql,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr[-400:]}")
    return out.stdout


def _wait(url: str, attempts: int = 120) -> bool:
    for _ in range(attempts):
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def up(app: str, lab: Path) -> dict[str, Any]:
    """Compose up (built from the repository), synthetic data, a read-only role; returns what the mandate needs
    (deploy steps, check steps, health, connections, credentials) and what was prepared."""
    repo = lab / app
    port, db_port = PORTS[app]
    lab_id = LAB_IDS[app]
    labels = ownership.compose_labels(lab_id)
    vlabels = ownership.compose_labels(lab_id, indent="      ")
    if app == "fst":
        held = _secrets(lab, app, ["FST_PG", "FST_SECRET", "FST_ADMIN", "FST_READER_PW"])
        (repo / COMPOSE_FILE).write_text(
            FST_COMPOSE.format(
                pg=held["FST_PG"],
                secret=held["FST_SECRET"],
                admin=held["FST_ADMIN"],
                port=port,
                db_port=db_port,
                labels=labels,
                vlabels=vlabels,
            )
        )
        health = f"http://127.0.0.1:{port}/api/v1/utils/health-check/"
        database, reader, pw = "app", "fst_reader", held["FST_READER_PW"]
        docs = f"http://127.0.0.1:{port}/api/v1/openapi.json"
        seed_sql = (
            Path(__file__).resolve().parents[2] / "demo" / "fastapi-template" / "seed_production.sql"
        ).read_text()
        credential = "FST_READER_PW"
    else:
        held = _secrets(lab, app, ["SPOOLMAN_PG", "SPOOLMAN_READER_PW"])
        (repo / COMPOSE_FILE).write_text(
            SPOOLMAN_COMPOSE.format(pg=held["SPOOLMAN_PG"], port=port, db_port=db_port, labels=labels, vlabels=vlabels)
        )
        health = f"http://127.0.0.1:{port}/api/v1/health"
        database, reader, pw = "spoolman", "spoolman_reader", held["SPOOLMAN_READER_PW"]
        docs = f"http://127.0.0.1:{port}/api/v1/openapi.json"
        seed_sql = None  # the ecosystem lab's SQL, below
        credential = "SPOOLMAN_READER_PW"
    (repo / COMPOSE_FILE).chmod(0o600)
    prep: list[dict[str, Any]] = []
    if app == "spoolman":
        # Human preparation, counted: Spoolman's Dockerfile copies frontends its CI builds with Node before the
        # image (`client/dist`, `client_v2/build`); a person runs the same two builds (ci.yml: node 24, npm ci, npm
        # run build). The repository is not changed; the outputs are ignored by git.
        for sub in ("client", "client_v2"):
            out_dir = repo / sub / ("dist" if sub == "client" else "build")
            if out_dir.exists():
                continue
            t0 = time.monotonic()
            for argv in (["npm", "ci", "--no-audit", "--no-fund"], ["npm", "run", "build"]):
                done = subprocess.run(argv, cwd=repo / sub, capture_output=True, text=True, timeout=1800)
                if done.returncode != 0:
                    raise RuntimeError(f"{sub}: {' '.join(argv)} failed: {done.stderr[-400:]}")
            prep.append(
                {
                    "step": f"build the {sub} frontend (npm ci, npm run build) as the project's CI does",
                    "minutes": round((time.monotonic() - t0) / 60, 1),
                    "why": "the Dockerfile copies it",
                }
            )
    started = time.monotonic()
    build = subprocess.run(
        [*_compose(app, repo), "up", "-d", "--build"], cwd=repo, capture_output=True, text=True, timeout=3600
    )
    if build.returncode != 0:
        raise RuntimeError(f"compose up failed: {build.stderr[-600:]}")
    if not _wait(health):
        raise RuntimeError(f"{health} did not answer")
    up_s = round(time.monotonic() - started, 1)
    data: dict[str, Any] = {}
    if app == "fst":
        _psql(app, repo, database, seed_sql or "")
        counts = _psql(app, repo, database, 'SELECT (SELECT count(*) FROM "user"), (SELECT count(*) FROM item);')
        data = dict(zip(["users", "items"], map(int, counts.strip().split("|")), strict=True))
    else:
        from bench.ecosystem import spoolman_lab

        sql = _spoolman_seed_sql(200, 5000, 100_000, pw)
        _psql(app, repo, database, sql)
        counts = _psql(
            app,
            repo,
            database,
            "SELECT (SELECT count(*) FROM vendor), (SELECT count(*) FROM filament), (SELECT count(*) FROM spool);",
        )
        data = dict(zip(["vendors", "filaments", "spools"], map(int, counts.strip().split("|")), strict=True))
        del spoolman_lab
    _psql(
        app,
        repo,
        database,
        f"""
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{reader}') THEN
CREATE ROLE {reader} LOGIN PASSWORD '{pw}'; END IF; END $$;
GRANT CONNECT ON DATABASE {database} TO {reader}; GRANT USAGE ON SCHEMA public TO {reader};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {reader};""",
    )
    return {
        "app": app,
        "project": lab_id,
        "port": port,
        "db_port": db_port,
        "health": health,
        "up_s": up_s,
        "data": data,
        "deploy_steps": [["docker", "compose", "-f", COMPOSE_FILE, "-p", lab_id, "up", "-d", "--build"]],
        "check_steps": [
            ["python", "-c", "import compileall,sys; sys.exit(0 if compileall.compile_dir('.', quiet=1) else 1)"]
        ],
        "check_image": "python:3.12-slim",
        "connections": [
            {
                "id": f"{app}-db",
                "kind": "postgres",
                "location": f"127.0.0.1:{db_port}/{database}",
                "environment": "staging",
                "username": reader,
                "credential_ref": credential,
                "permissions": ["read"],
                "content_may_leave": True,
            },
            {
                "id": f"{app}-api",
                "kind": "http_api",
                "location": f"http://127.0.0.1:{port}",
                "docs": docs,
                "environment": "staging",
                "permissions": ["read"],
                "content_may_leave": True,
            },
        ],
        "credentials": {credential: pw},
        "writes": False,
        "prep": prep,
    }


def _spoolman_seed_sql(vendors: int, filaments: int, spools: int, reader_pw: str) -> str:
    """The ecosystem lab's synthetic data (bench/ecosystem/spoolman_lab.py), the same sizes."""
    return "\n".join(
        [
            "BEGIN;",
            "TRUNCATE spool, filament, vendor RESTART IDENTITY CASCADE;",
            f"INSERT INTO vendor (registered, name) SELECT now(), 'Vendor ' || g FROM generate_series(1, {vendors}) g;",
            "INSERT INTO filament (registered, name, vendor_id, material, price, density, diameter, weight, color_hex) "
            f"SELECT now(), 'Filament ' || g, 1 + (g * 7) % {vendors}, (ARRAY['PLA','PETG','ABS','TPU'])[1 + g % 4], "
            f"10 + g % 40, 1.24, 1.75, 1000, lpad(to_hex(g * 4099 % 16777216), 6, '0') "
            f"FROM generate_series(1, {filaments}) g;",
            "INSERT INTO spool (registered, filament_id, used_weight, archived) "
            "SELECT now() - (g || ' minutes')::interval, "
            f"1 + (g::bigint * 7919) % {filaments}, (g * 37) % 900, g % 10 = 0 FROM generate_series(1, {spools}) g;",
            "COMMIT;",
            "ANALYZE;",
        ]
    )


def observe(app: str, lab: Path) -> dict[str, Any]:
    """What the lab shows, independently of Unbidden's records: health, the running image's build time, the
    commit the backend container was built from (its label if any), the containers."""
    repo = lab / app
    port, _ = PORTS[app]
    health = (
        f"http://127.0.0.1:{port}/api/v1/utils/health-check/"
        if app == "fst"
        else f"http://127.0.0.1:{port}/api/v1/health"
    )
    try:
        status = httpx.get(health, timeout=5).status_code
    except httpx.HTTPError as exc:
        status = f"error: {type(exc).__name__}"
    ps = subprocess.run(
        [*_compose(app, repo), "ps", "--format", "{{.Service}} {{.Status}} {{.Image}}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return {"health_status": status, "containers": ps.stdout.strip().splitlines(), "checkout_head": head}


def down(app: str, lab: Path, *, volumes: bool = True) -> None:
    repo = lab / app
    if (repo / COMPOSE_FILE).exists():
        ownership.compose_down(LAB_IDS[app], str(repo), volumes=volumes)
