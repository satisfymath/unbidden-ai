"""Stage 9's evaluation application: Prefect's server (PrefectHQ/prefect) in the lab, as a person would prepare it.
Everything here is human preparation: counted in docs/bench/stage9-evaluation.md and never attributed to Unbidden.

    uv run python -m bench.ecosystem.prefect_lab up|seed|down [--volumes]

- `up`: clone the person's local copy (~/prefect) at the pinned release to ~/unbidden-lab/prefect, write a compose
  file (the project's own published image of that release running `prefect server start`, PostgreSQL 16, 127.0.0.1
  ports, owned resources; excluded from git), start it; the server migrates its schema at start;
- `seed`: synthetic flows, flow runs, task runs and logs through the server's own REST API (its schema is created and
  kept by the server: written through the API, the data is what the server itself would store), and a read-only
  database role;
- `down`: stop the project's containers, keeping the data volume unless `--volumes`.
No credential: the open-source server has no authentication by default.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from bench.ecosystem import ownership

UPSTREAM = Path.home() / "prefect"  # the person's clone of https://github.com/PrefectHQ/prefect
COMMIT = "1ef3e516d3b3449d19f65b30c45d1e0bff656396"  # 3.9.0, the latest 3.x release when chosen (2026-10-21)
IMAGE = "prefecthq/prefect:3.9.0-python3.12"  # the project's own image of that release
LAB_ID, PROJECT, PORT, DB_PORT = "prefect", "prefect-staging", 18140, 55470
URL = f"http://127.0.0.1:{PORT}"
SECRETS = "prefect-secrets.env"
COMPOSE_FILE = """services:
  server:
    image: {image}
    command: ["prefect", "server", "start", "--host", "0.0.0.0", "--port", "4200"]
    ports:
      - "127.0.0.1:{port}:4200"
    environment:
      PREFECT_SERVER_DATABASE_CONNECTION_URL: "postgresql+asyncpg://postgres:{pg}@db:5432/prefect"
      PREFECT_SERVER_ANALYTICS_ENABLED: "false"
      PREFECT_UI_ENABLED: "false"
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
      POSTGRES_DB: prefect
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 2s
      retries: 30
    volumes:
      - prefect-data:/var/lib/postgresql/data
    labels:
{labels}volumes:
  prefect-data:
    labels:
{labels}"""
COMPOSE = ["docker", "compose", "-f", "docker-compose.lab.yml", "-p", PROJECT]


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / SECRETS
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in ("PREFECT_PG", "PREFECT_READER_PW") if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(lab: Path) -> Path:
    return lab / "prefect"


def up(lab: Path) -> None:
    repo, held = repo_dir(lab), _secrets(lab)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "-q", str(UPSTREAM), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", COMMIT], check=True)
    compose = COMPOSE_FILE.format(image=IMAGE, port=PORT, db_port=DB_PORT, pg=held["PREFECT_PG"],
                                  labels=ownership.compose_labels(LAB_ID))  # fmt: skip
    (repo / "docker-compose.lab.yml").write_text(compose)
    (repo / "docker-compose.lab.yml").chmod(0o600)
    exclude = repo / ".git" / "info" / "exclude"
    wanted = ["docker-compose.lab.yml", ".unbidden/"]
    have = exclude.read_text().splitlines() if exclude.exists() else []
    exclude.write_text("\n".join([*have, *[w for w in wanted if w not in have]]) + "\n")
    subprocess.run([*COMPOSE, "up", "-d"], cwd=repo, check=True)
    for _ in range(150):
        try:
            if httpx.get(f"{URL}/api/health", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(f"{URL} did not come up")


def _psql(lab: Path, sql: str) -> str:
    argv = [*COMPOSE, "exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-At", "-U", "postgres", "-d",
            "prefect"]  # fmt: skip
    return subprocess.run(argv, cwd=repo_dir(lab), input=sql, text=True, capture_output=True, check=True).stdout


def seed(lab: Path, flows: int = 50, runs_per_flow: int = 200, tasks_per_run: int = 3) -> dict[str, int]:
    """Synthetic flows and their runs, written through the server's API (concurrently, bounded)."""
    held = _secrets(lab)
    # The same data before every run: what an earlier seed or run wrote is removed first (the evaluation re-seeds
    # before each run, and the API only adds).
    _psql(lab, "TRUNCATE log, task_run, flow_run, flow RESTART IDENTITY CASCADE;")
    client = httpx.Client(base_url=f"{URL}/api", timeout=30)
    flow_ids = [client.post("/flows/", json={"name": f"synthetic-flow-{i}"}).json()["id"] for i in range(flows)]

    def one(args: tuple[str, int]) -> None:
        flow_id, n = args
        state = ["COMPLETED", "FAILED", "COMPLETED", "CANCELLED"][n % 4]
        run = client.post("/flow_runs/", json={"flow_id": flow_id, "name": f"run-{n}",
                                               "state": {"type": state}}).json()  # fmt: skip
        for t in range(tasks_per_run):
            client.post("/task_runs/", json={"flow_run_id": run["id"], "task_key": f"task-{t}", "dynamic_key": str(n),
                                             "name": f"task-{t}", "state": {"type": state}})  # fmt: skip
        client.post("/logs/", json=[{"name": "synthetic", "level": 20, "message": f"run {n} step {k}",
                                     "timestamp": "2026-10-29T00:00:00Z", "flow_run_id": run["id"]}
                                    for k in range(3)])  # fmt: skip

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, [(f, i * flows + j) for j, f in enumerate(flow_ids) for i in range(runs_per_flow)]))
    _psql(lab, "ANALYZE;\nDO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'prefect_reader') THEN "
               f"CREATE ROLE prefect_reader LOGIN PASSWORD '{held['PREFECT_READER_PW']}'; END IF; END $$;\n"
               "GRANT CONNECT ON DATABASE prefect TO prefect_reader; GRANT USAGE ON SCHEMA public TO prefect_reader;\n"
               "GRANT SELECT ON ALL TABLES IN SCHEMA public TO prefect_reader;")  # fmt: skip
    counts = _psql(lab, "SELECT (SELECT count(*) FROM flow), (SELECT count(*) FROM flow_run), "
                        "(SELECT count(*) FROM task_run), (SELECT count(*) FROM log);").strip().split("|")  # fmt: skip
    return dict(zip(["flows", "flow_runs", "task_runs", "logs"], map(int, counts), strict=True))


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
