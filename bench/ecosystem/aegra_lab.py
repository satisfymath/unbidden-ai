"""Stage 10's evaluation application 2: Aegra (aegra/aegra) in the lab, as a person would prepare it. Everything here
is human preparation: counted in docs/bench/stage10-evaluation.md and never attributed to Unbidden.

    uv run python -m bench.ecosystem.aegra_lab up|seed|down [--volumes]

- `up`: clone the person's copy (~/aegra) at the pinned release to ~/unbidden-lab/aegra, build the project's own
  image from its Dockerfile at that commit (no image is published), write a compose file (that image, PostgreSQL with
  pgvector as the project's compose uses, 127.0.0.1 ports, owned resources; excluded from git), start it; the
  application migrates its schema at start;
- `seed`: assistants and threads through the project's API (it creates them without any model); runs through SQL
  written from its models (the API would execute a graph, which calls a model); generated, nothing real; a read-only
  role;
- `down`: stop the project's containers, keeping the data volume unless `--volumes`.
Authentication is the project's default (`AUTH_TYPE=noop`). Redis stays off, as by default (`REDIS_BROKER_ENABLED`);
the cron scheduler is off (it would run graphs, which call a model); the model key is a placeholder: the graphs load,
nothing calls a model, nothing leaves the lab.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
import uuid
from pathlib import Path

import httpx

from bench.ecosystem import ownership

UPSTREAM = Path.home() / "aegra"  # the person's clone of https://github.com/aegra/aegra
COMMIT = "46055c0b9adffe51fb168974f79dfadaa6edd612"  # v0.11.0, the latest release when chosen (2026-10-31)
IMAGE = "unbidden-lab/aegra:0.11.0"  # built from the project's deployments/docker/Dockerfile at COMMIT
LAB_ID, PROJECT, PORT, DB_PORT = "aegra", "aegra-staging", 18160, 55490
URL = f"http://127.0.0.1:{PORT}"
SECRETS = "aegra-secrets.env"
SPEC = {"database": "aegra", "docs": "/openapi.json", "secret": "AEGRA_READER_PW"}  # read by app_eval
COMPOSE_FILE = """services:
  app:
    image: {image}
    ports:
      - "127.0.0.1:{port}:2026"
    environment:
      POSTGRES_HOST: db
      POSTGRES_PORT: "5432"
      POSTGRES_DB: aegra
      POSTGRES_USER: aegra
      POSTGRES_PASSWORD: "{pg}"
      AUTH_TYPE: noop
      REDIS_BROKER_ENABLED: "false"
      CRON_ENABLED: "false"
      OPENAI_API_KEY: sk-placeholder-not-a-key
      ENV_MODE: LOCAL
      HOST: 0.0.0.0
      PORT: "2026"
    # The project's compose runs the API this way (the image's own `aegra serve` is not in it); without --reload.
    command: ["uvicorn", "aegra_api.main:app", "--host", "0.0.0.0", "--port", "2026"]
    depends_on:
      db:
        condition: service_healthy
    labels:
{labels}  db:
    image: pgvector/pgvector:pg18
    ports:
      - "127.0.0.1:{db_port}:5432"
    environment:
      POSTGRES_USER: aegra
      POSTGRES_PASSWORD: "{pg}"
      POSTGRES_DB: aegra
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U aegra -d aegra"]
      interval: 2s
      retries: 30
    volumes:
      - aegra-data:/var/lib/postgresql
    labels:
{labels}volumes:
  aegra-data:
    labels:
{vlabels}"""
COMPOSE = ["docker", "compose", "-f", "docker-compose.lab.yml", "-p", PROJECT]


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / SECRETS
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in ("AEGRA_PG", "AEGRA_READER_PW") if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(lab: Path) -> Path:
    return lab / "aegra"


def up(lab: Path) -> None:
    repo, held = repo_dir(lab), _secrets(lab)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "-q", str(UPSTREAM), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", COMMIT], check=True)
    built = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode == 0
    if not built:
        subprocess.run(["docker", "build", "-q", "-f", "deployments/docker/Dockerfile", "-t", IMAGE,
                        "--label", f"unbidden.lab={LAB_ID}", "."], cwd=repo, check=True)  # fmt: skip
    compose = COMPOSE_FILE.format(image=IMAGE, port=PORT, db_port=DB_PORT, pg=held["AEGRA_PG"],
                                  labels=ownership.compose_labels(LAB_ID),
                                  vlabels=ownership.compose_labels(LAB_ID))  # fmt: skip
    (repo / "docker-compose.lab.yml").write_text(compose)
    (repo / "docker-compose.lab.yml").chmod(0o600)
    exclude = repo / ".git" / "info" / "exclude"
    wanted = ["docker-compose.lab.yml", ".unbidden/"]
    have = exclude.read_text().splitlines() if exclude.exists() else []
    exclude.write_text("\n".join([*have, *[w for w in wanted if w not in have]]) + "\n")
    subprocess.run([*COMPOSE, "up", "-d"], cwd=repo, check=True)
    for _ in range(150):
        try:
            if httpx.get(f"{URL}{SPEC['docs']}", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(f"{URL} did not come up")


def _psql(lab: Path, sql: str) -> str:
    argv = [*COMPOSE, "exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-At", "-U", "aegra", "-d", "aegra"]
    return subprocess.run(argv, cwd=repo_dir(lab), input=sql, text=True, capture_output=True, check=True).stdout


GRAPHS = ["agent", "agent_hitl", "subgraph_agent", "factory"]  # graphs of the project's aegra.json


def seed(lab: Path, assistants: int = 200, threads: int = 20_000, runs: int = 200_000) -> dict[str, int]:
    """Assistants and threads through the API, runs through SQL, at a size where reads that scan a table can be told
    from reads that use an index. Generated and deterministic; nothing is real."""
    held = _secrets(lab)
    _psql(lab, "TRUNCATE runs, thread, assistant_versions, assistant CASCADE;")
    with httpx.Client(base_url=URL, timeout=30) as api:
        for i in range(assistants):
            # Its own configuration: the API keeps one assistant per graph and configuration (an id is not enough).
            body = {
                "assistant_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"unbidden-lab/aegra/assistant/{i}")),
                "graph_id": GRAPHS[i % len(GRAPHS)],
                "name": f"Assistant {i:03d}",
                "config": {"configurable": {"variant": i}},
                "metadata": {"team": f"team-{i % 20}", "seed": i},
                "if_exists": "do_nothing",
            }
            api.post("/assistants", json=body).raise_for_status()
        for i in range(threads):
            body = {"metadata": {"customer": f"customer-{i % 500}", "seed": i, "channel": ["web", "api"][i % 2]}}
            api.post("/threads", json=body).raise_for_status()
    sql = [
        "BEGIN;",
        "CREATE TEMP TABLE t AS SELECT thread_id, user_id, row_number() OVER (ORDER BY created_at, thread_id) n "
        "FROM thread;",
        "CREATE TEMP TABLE a AS SELECT assistant_id, row_number() OVER (ORDER BY name) n FROM assistant;",
        "INSERT INTO runs (run_id, thread_id, assistant_id, status, input, config, output, user_id, created_at, "
        "updated_at, context, execution_params) "
        "SELECT md5('run' || g)::uuid::text, t.thread_id, a.assistant_id, "
        "(ARRAY['success','success','success','error','interrupted'])[1 + g % 5], "
        "jsonb_build_object('messages', "
        "jsonb_build_array(jsonb_build_object('role', 'user', 'content', 'message ' || g))), "
        "'{}'::jsonb, jsonb_build_object('result', 'output ' || g), t.user_id, "
        "timestamptz '2026-10-01 00:00:00+00' + (g * 9 || ' seconds')::interval, "
        "timestamptz '2026-10-01 00:00:00+00' + (g * 9 + 4 || ' seconds')::interval, '{}'::jsonb, '{}'::jsonb "
        f"FROM generate_series(1, {runs}) g "
        f"JOIN t ON t.n = 1 + (g::bigint * 7919) % {threads} "
        f"JOIN a ON a.n = 1 + g % {assistants};",
        "COMMIT;",
        "ANALYZE;",
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aegra_reader') THEN "
        f"CREATE ROLE aegra_reader LOGIN PASSWORD '{held['AEGRA_READER_PW']}'; END IF; END $$;",
        "GRANT CONNECT ON DATABASE aegra TO aegra_reader; GRANT USAGE ON SCHEMA public TO aegra_reader;",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO aegra_reader;",
    ]
    _psql(lab, "\n".join(sql))
    tables = ["assistant", "thread", "runs"]
    counted = _psql(lab, "SELECT " + ", ".join(f"(SELECT count(*) FROM {t})" for t in tables) + ";")
    return dict(zip(tables, map(int, counted.strip().split("|")), strict=True))


def down(lab: Path, volumes: bool = False) -> None:
    repo = repo_dir(lab)
    if repo.exists():
        ownership.compose_down(PROJECT, str(repo), volumes=volumes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["up", "seed", "down"])
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    parser.add_argument("--volumes", action="store_true", help="down: also remove the data volume")
    args = parser.parse_args()
    lab = Path(args.dir)
    actions = {"up": up, "seed": seed, "down": lambda lab: down(lab, args.volumes)}
    out = actions[args.action](lab)
    if out is not None:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
