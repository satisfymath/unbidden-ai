"""Stage 10's evaluation application 1: codex-lb (Soju06/codex-lb) in the lab, as a person would prepare it.
Everything here is human preparation: counted in docs/bench/stage10-evaluation.md and never attributed to Unbidden.

    uv run python -m bench.ecosystem.codex_lb_lab up|seed|down [--volumes]

- `up`: clone the person's copy (~/codex-lb) at the pinned release to ~/unbidden-lab/codex-lb, write a compose file
  (the project's own published image of that release, PostgreSQL 18, 127.0.0.1 ports, owned resources; excluded from
  git), start it; the application migrates its schema at start;
- `seed`: synthetic data through SQL written from the project's models (its API cannot create accounts: they come
  from ChatGPT's OAuth), generated, nothing real; and a read-only role;
- `down`: stop the project's containers, keeping the data volume unless `--volumes`.
Dashboard authentication is set to the project's own `disabled` mode; no credential is needed to read its API. The
schedulers that call ChatGPT for the accounts (usage, reset credits, quota planner, automations, auth guardian) are
off through the project's own settings: the accounts are synthetic, nothing may leave the lab, and nothing rewrites
the data while it is measured.
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

UPSTREAM = Path.home() / "codex-lb"  # the person's clone of https://github.com/Soju06/codex-lb
COMMIT = "84fde5a1ed5e0d5a58ccb3ec4b82938b059bf8c5"  # v1.24.0, the latest release when chosen (2026-10-31)
IMAGE = "ghcr.io/soju06/codex-lb:1.24.0"  # the project's own image of that release
LAB_ID, PROJECT, PORT, DB_PORT = "codex-lb", "codex-lb-staging", 18150, 55480
URL = f"http://127.0.0.1:{PORT}"
SECRETS = "codex-lb-secrets.env"
SPEC = {"database": "codex_lb", "docs": "/openapi.json", "secret": "CODEX_LB_READER_PW"}  # read by app_eval
COMPOSE_FILE = """services:
  app:
    image: {image}
    ports:
      - "127.0.0.1:{port}:2455"
    environment:
      CODEX_LB_DATABASE_URL: "postgresql+asyncpg://codex_lb:{pg}@db:5432/codex_lb"
      CODEX_LB_DASHBOARD_AUTH_MODE: disabled
      CODEX_LB_USAGE_REFRESH_ENABLED: "false"
      CODEX_LB_RATE_LIMIT_RESET_CREDITS_REFRESH_ENABLED: "false"
      CODEX_LB_QUOTA_PLANNER_SCHEDULER_ENABLED: "false"
      CODEX_LB_AUTOMATIONS_SCHEDULER_ENABLED: "false"
      CODEX_LB_AUTH_GUARDIAN_ENABLED: "false"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - codex-lb-home:/var/lib/codex-lb
    labels:
{labels}  db:
    image: postgres:18-alpine
    ports:
      - "127.0.0.1:{db_port}:5432"
    environment:
      POSTGRES_USER: codex_lb
      POSTGRES_PASSWORD: "{pg}"
      POSTGRES_DB: codex_lb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U codex_lb -d codex_lb"]
      interval: 2s
      retries: 30
    volumes:
      - codex-lb-data:/var/lib/postgresql
    labels:
{labels}volumes:
  codex-lb-data:
    labels:
{vlabels}  codex-lb-home:
    labels:
{vlabels}"""
COMPOSE = ["docker", "compose", "-f", "docker-compose.lab.yml", "-p", PROJECT]


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / SECRETS
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in ("CODEX_LB_PG", "CODEX_LB_READER_PW") if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(lab: Path) -> Path:
    return lab / "codex-lb"


def up(lab: Path) -> None:
    repo, held = repo_dir(lab), _secrets(lab)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "-q", str(UPSTREAM), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", COMMIT], check=True)
    compose = COMPOSE_FILE.format(image=IMAGE, port=PORT, db_port=DB_PORT, pg=held["CODEX_LB_PG"],
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
    argv = [*COMPOSE, "exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-At", "-U", "codex_lb", "-d",
            "codex_lb"]  # fmt: skip
    return subprocess.run(argv, cwd=repo_dir(lab), input=sql, text=True, capture_output=True, check=True).stdout


def seed(lab: Path, accounts: int = 2000, keys: int = 50, logs: int = 300_000, usage: int = 200_000) -> dict[str, int]:
    """Synthetic accounts, API keys, request logs and usage history at a size where reads that scan a table can be
    told from reads that use an index. Generated and deterministic; the token columns hold placeholder bytes (the
    project encrypts real ones), the emails are on example.com, nothing is real."""
    held = _secrets(lab)
    statuses = "ARRAY['active','active','active','paused','rate_limited','quota_exceeded']::account_status[]"
    sql = [
        "BEGIN;",
        "TRUNCATE request_logs, usage_history, api_keys, accounts RESTART IDENTITY CASCADE;",
        "INSERT INTO accounts (id, chatgpt_account_id, email, plan_type, access_token_encrypted, "
        "refresh_token_encrypted, id_token_encrypted, last_refresh, created_at, status, codex_installation_id) "
        "SELECT 'acct_' || lpad(g::text, 5, '0'), 'chatgpt-' || g, 'user' || g || '@example.com', "
        "(ARRAY['plus','pro','team'])[1 + g % 3], '\\x00'::bytea, '\\x00'::bytea, '\\x00'::bytea, "
        "timestamp '2026-10-01' + (g || ' minutes')::interval, timestamp '2026-09-01' + (g || ' minutes')::interval, "
        f"({statuses})[1 + g % 6], 'install-' || g FROM generate_series(1, {accounts}) g;",
        "INSERT INTO api_keys (id, name, key_hash, key_prefix, is_active, created_at) "
        "SELECT 'key_' || lpad(g::text, 3, '0'), 'Key ' || g, md5('key' || g), 'sk-' || lpad(g::text, 4, '0'), "
        f"g % 7 <> 0, timestamp '2026-09-01' + (g || ' hours')::interval FROM generate_series(1, {keys}) g;",
        "INSERT INTO request_logs (account_id, api_key_id, request_id, requested_at, model, transport, input_tokens, "
        "output_tokens, cached_input_tokens, reasoning_tokens, latency_ms, status, cost_usd, request_kind) "
        f"SELECT 'acct_' || lpad((1 + (g::bigint * 7919) % {accounts})::text, 5, '0'), "
        f"'key_' || lpad((1 + g % {keys})::text, 3, '0'), 'req_' || g, "
        "timestamp '2026-10-01' + (g * 7 || ' seconds')::interval, "
        "(ARRAY['gpt-5.5','gpt-5.5-mini','gpt-5.4-codex'])[1 + g % 3], 'http', 200 + g % 4000, 50 + g % 900, "
        "g % 300, g % 120, 300 + g % 5000, (ARRAY['success','success','success','error'])[1 + g % 4], "
        f"round(((g % 1000) / 10000.0)::numeric, 4), 'normal' FROM generate_series(1, {logs}) g;",
        'INSERT INTO usage_history (account_id, recorded_at, "window", used_percent, input_tokens, output_tokens, '
        f"window_minutes) SELECT 'acct_' || lpad((1 + (g::bigint * 104729) % {accounts})::text, 5, '0'), "
        "timestamp '2026-10-01' + (g * 11 || ' seconds')::interval, (ARRAY['primary','secondary'])[1 + g % 2], "
        f"(g % 100)::double precision, 1000 + g % 9000, 100 + g % 900, (ARRAY[300, 10080])[1 + g % 2] "
        f"FROM generate_series(1, {usage}) g;",
        "COMMIT;",
        "ANALYZE;",
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'codex_lb_reader') THEN "
        f"CREATE ROLE codex_lb_reader LOGIN PASSWORD '{held['CODEX_LB_READER_PW']}'; END IF; END $$;",
        "GRANT CONNECT ON DATABASE codex_lb TO codex_lb_reader; GRANT USAGE ON SCHEMA public TO codex_lb_reader;",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO codex_lb_reader;",
    ]
    _psql(lab, "\n".join(sql))
    tables = ["accounts", "api_keys", "request_logs", "usage_history"]
    counted = _psql(lab, "SELECT " + ", ".join(f"(SELECT count(*) FROM {t})" for t in tables) + ";")
    counts = counted.strip().split("|")
    return dict(zip(tables, map(int, counts), strict=True))


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
