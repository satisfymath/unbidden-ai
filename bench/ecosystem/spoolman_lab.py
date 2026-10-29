"""Stage 9's evaluation application: Spoolman (Donkie/Spoolman) in the lab, as a person would prepare it. Everything
here is human preparation: counted in docs/bench/stage9-evaluation.md and never attributed to Unbidden.

    uv run python -m bench.ecosystem.spoolman_lab up|seed|down [--volumes]

- `up`: clone the person's local copy (~/Spoolman) at the pinned release to ~/unbidden-lab/spoolman, write a compose
  file (the project's own published image of that release, PostgreSQL 16, 127.0.0.1 ports, owned resources; excluded
  from git), start it; the application creates its schema at start;
- `seed`: synthetic vendors, filaments and spools through SQL (generated, nothing real), and a read-only role;
- `down`: stop the project's containers, keeping the data volume unless `--volumes`.
No credential: Spoolman's API has no authentication.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

import httpx

from bench.ecosystem import ownership

UPSTREAM = Path.home() / "Spoolman"  # the person's clone of https://github.com/Donkie/Spoolman
COMMIT = "bed3f14ee77a3a571d31b14215d54b0b88a7519c"  # v0.27.0, the latest release when chosen (2026-09-25)
IMAGE = "ghcr.io/donkie/spoolman:0.27.0"  # the project's own image of that release
LAB_ID, PROJECT, PORT, DB_PORT = "spoolman", "spoolman-staging", 18130, 55460
URL = f"http://127.0.0.1:{PORT}"
SECRETS = "spoolman-secrets.env"
COMPOSE_FILE = """services:
  app:
    image: {image}
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
      - spoolman-data:/var/lib/postgresql/data
    labels:
{labels}volumes:
  spoolman-data:
    labels:
{vlabels}"""
COMPOSE = ["docker", "compose", "-f", "docker-compose.lab.yml", "-p", PROJECT]


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / SECRETS
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in ("SPOOLMAN_PG", "SPOOLMAN_READER_PW") if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(lab: Path) -> Path:
    return lab / "spoolman"


def up(lab: Path) -> None:
    repo, held = repo_dir(lab), _secrets(lab)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "-q", str(UPSTREAM), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", COMMIT], check=True)
    compose = COMPOSE_FILE.format(image=IMAGE, port=PORT, db_port=DB_PORT, pg=held["SPOOLMAN_PG"],
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
            if httpx.get(f"{URL}/api/v1/openapi.json", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(f"{URL} did not come up")


def _psql(lab: Path, sql: str) -> str:
    argv = [*COMPOSE, "exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-At", "-U", "postgres", "-d",
            "spoolman"]  # fmt: skip
    return subprocess.run(argv, cwd=repo_dir(lab), input=sql, text=True, capture_output=True, check=True).stdout


def seed(lab: Path, vendors: int = 200, filaments: int = 5000, spools: int = 100_000) -> dict[str, int]:
    """Synthetic data at a size where reads that scan a table can be told from reads that use an index."""
    held = _secrets(lab)
    sql = [
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
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'spoolman_reader') THEN "
        f"CREATE ROLE spoolman_reader LOGIN PASSWORD '{held['SPOOLMAN_READER_PW']}'; END IF; END $$;",
        "GRANT CONNECT ON DATABASE spoolman TO spoolman_reader; GRANT USAGE ON SCHEMA public TO spoolman_reader;",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO spoolman_reader;",
    ]
    _psql(lab, "\n".join(sql))
    counts = _psql(lab, "SELECT (SELECT count(*) FROM vendor), (SELECT count(*) FROM filament), "
                        "(SELECT count(*) FROM spool);").strip().split("|")  # fmt: skip
    return dict(zip(["vendors", "filaments", "spools"], map(int, counts), strict=True))


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
