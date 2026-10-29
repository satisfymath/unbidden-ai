"""Stage 8's independent application: LNbits (lnbits/lnbits) in the lab, as a person would prepare it. Everything
here is human preparation: counted in docs/bench/stage8-independent.md and never attributed to Unbidden.

    uv run python -m bench.ecosystem.lnbits_lab up|seed|token|down

- `up`: clone the person's local copy (~/lnbits) at the pinned release to ~/unbidden-lab/lnbits, write `.env` and a
  compose file (127.0.0.1 ports, a named volume, the lab's label; both excluded from git), build the project's own
  Dockerfile and start it with a PostgreSQL. Funding source: FakeWallet (no Lightning node, no funds, offline);
- `seed`: synthetic accounts, wallets and payments through SQL (generated, no real person or payment), and a
  read-only role for Unbidden;
- `token`: a synthetic wallet created through the app's own API; its invoice (read) key is what a person would hand
  over as a credential, kept in the lab's secrets, never printed;
- `down`: stop and remove the project's containers and volume.
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

UPSTREAM = Path.home() / "lnbits"  # the person's clone of https://github.com/lnbits/lnbits
COMMIT = "9349da153c223b008f7d80453b53a54e09c8ed3d"  # v1.6.2, the latest release when chosen (2026-09-18)
PROJECT, PORT, DB_PORT = "lnbits-staging", 18120, 55450
URL = f"http://127.0.0.1:{PORT}"
COMPOSE_FILE = """services:
  app:
    build: .
    ports:
      - "127.0.0.1:{port}:5000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    labels:
      unbidden.lab: ecosystem
  db:
    image: postgres:16
    ports:
      - "127.0.0.1:{db_port}:5432"
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: "{pg}"
      POSTGRES_DB: lnbits
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 2s
      retries: 30
    volumes:
      - lnbits-data:/var/lib/postgresql/data
    labels:
      unbidden.lab: ecosystem
volumes:
  lnbits-data:
"""
COMPOSE = ["docker", "compose", "-f", "docker-compose.lab.yml", "-p", PROJECT]
SECRETS = "lnbits-secrets.env"


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / SECRETS
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in ("LNBITS_PG", "LNBITS_READER_PW", "LNBITS_FAKE") if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(lab: Path) -> Path:
    return lab / "lnbits"


def up(lab: Path) -> None:
    repo, held = repo_dir(lab), _secrets(lab)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "-q", str(UPSTREAM), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", COMMIT], check=True)
    (repo / ".env").write_text(
        f"LNBITS_DATABASE_URL=postgres://postgres:{held['LNBITS_PG']}@db:5432/lnbits\n"
        "LNBITS_BACKEND_WALLET_CLASS=FakeWallet\nLNBITS_ALLOWED_FUNDING_SOURCES=FakeWallet\n"
        f"FAKE_WALLET_SECRET={held['LNBITS_FAKE']}\nLNBITS_ADMIN_UI=false\nLNBITS_ALLOW_NEW_ACCOUNTS=true\n"
        "LNBITS_EXTENSIONS_DEFAULT_INSTALL=\nLNBITS_DATA_FOLDER=./data\n"
    )
    (repo / ".env").chmod(0o600)
    (repo / "docker-compose.lab.yml").write_text(COMPOSE_FILE.format(port=PORT, db_port=DB_PORT, pg=held["LNBITS_PG"]))
    (repo / "docker-compose.lab.yml").chmod(0o600)
    exclude = repo / ".git" / "info" / "exclude"
    wanted = [".env", "docker-compose.lab.yml", ".unbidden/", "data/"]
    have = exclude.read_text().splitlines() if exclude.exists() else []
    exclude.write_text("\n".join([*have, *[w for w in wanted if w not in have]]) + "\n")
    subprocess.run([*COMPOSE, "up", "-d", "--build"], cwd=repo, check=True)
    for _ in range(150):
        try:
            if httpx.get(f"{URL}/openapi.json", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(f"{URL} did not come up")


def _psql(lab: Path, sql: str) -> str:
    argv = [
        *COMPOSE,
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
        "lnbits",
    ]
    return subprocess.run(argv, cwd=repo_dir(lab), input=sql, text=True, capture_output=True, check=True).stdout


def seed(lab: Path, accounts: int = 2000, wallets_per: int = 2, payments: int = 400_000) -> dict[str, int]:
    """Synthetic accounts, wallets and settled payments, at a size where reads that scan a table can be told from
    reads that use an index. Generated deterministically in SQL; hashes and bolt11 strings are placeholders."""
    held = _secrets(lab)
    wallets = accounts * wallets_per
    sql = [
        "BEGIN;",
        "DELETE FROM apipayments WHERE checking_id LIKE 'synthetic-%';",  # the readers' histories too
        "DELETE FROM wallets WHERE id LIKE 'synw%'; DELETE FROM accounts WHERE id LIKE 'syna%';",
        f"INSERT INTO accounts (id, username, email) SELECT 'syna' || g, 'user' || g, 'user' || g || '@example.test' "
        f"FROM generate_series(1, {accounts}) g;",
        f"INSERT INTO wallets (id, name, \"user\", adminkey, inkey) SELECT 'synw' || g, 'Wallet ' || g, "
        f"'syna' || (1 + (g - 1) / {wallets_per}), md5('a' || g), md5('i' || g) FROM generate_series(1, {wallets}) g;",
        "INSERT INTO apipayments (checking_id, payment_hash, wallet_id, amount, fee, bolt11, memo, status, time, "
        "created_at, updated_at) SELECT 'synthetic-' || g, md5('h' || g), 'synw' || (1 + (g::bigint * 7919) % "
        f"{wallets}), (CASE WHEN g % 3 = 0 THEN -1 ELSE 1 END) * (1000 + (g * 37) % 100000), 0, 'lnbcsynthetic' || g, "
        "'synthetic payment', 'success', now() - (g || ' seconds')::interval, now() - (g || ' seconds')::interval, "
        f"now() - (g || ' seconds')::interval FROM generate_series(1, {payments}) g;",
        "COMMIT;",
        "ANALYZE;",
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lnbits_reader') THEN "
        f"CREATE ROLE lnbits_reader LOGIN PASSWORD '{held['LNBITS_READER_PW']}'; END IF; END $$;",
        "GRANT CONNECT ON DATABASE lnbits TO lnbits_reader; GRANT USAGE ON SCHEMA public TO lnbits_reader;",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO lnbits_reader;",
    ]
    _psql(lab, "\n".join(sql))
    totals = (
        "SELECT (SELECT count(*) FROM accounts), (SELECT count(*) FROM wallets), (SELECT count(*) FROM apipayments);"
    )
    counts = _psql(lab, totals).strip().split("|")
    return dict(zip(["accounts", "wallets", "payments"], map(int, counts), strict=True))


def token(lab: Path) -> str:
    """Create a synthetic wallet through the app and keep its invoice (read) key in the lab's secrets."""
    r = httpx.post(f"{URL}/api/v1/account", json={"name": "unbidden-reader"}, timeout=10)
    if r.status_code != 200:
        raise SystemExit(f"creating the synthetic wallet answered {r.status_code}")
    key, wallet = r.json()["inkey"], r.json()["id"]
    # The wallet a person hands over has a history: 5,000 synthetic settled payments.
    _psql(lab, "INSERT INTO apipayments (checking_id, payment_hash, wallet_id, amount, fee, bolt11, memo, status, "
          "time, "
          f"created_at, updated_at) SELECT 'synthetic-r-{wallet}-' || g, md5('r{wallet}' || g), '{wallet}', "
          "(CASE WHEN g % 3 = 0 THEN -1 ELSE 1 END) * (1000 + g * 37), 0, 'lnbcsynthetic', 'synthetic payment', "
          "'success', now() - (g || ' minutes')::interval, now() - (g || ' minutes')::interval, "
          "now() - (g || ' minutes')::interval FROM generate_series(1, 5000) g;")  # fmt: skip
    path = lab / SECRETS
    lines = [ln for ln in path.read_text().splitlines() if not ln.startswith("LNBITS_TOKEN=")]
    path.write_text("\n".join([*lines, f"LNBITS_TOKEN={key}"]) + "\n")
    path.chmod(0o600)
    return f"held in {SECRETS}"


def down(lab: Path) -> None:
    repo = repo_dir(lab)
    if repo.exists():
        subprocess.run([*COMPOSE, "down", "-v"], cwd=repo, capture_output=True, check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["up", "seed", "token", "down"])
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    args = parser.parse_args()
    lab = Path(args.dir)
    out = {"up": up, "seed": seed, "token": token, "down": down}[args.action](lab)
    if out is not None:
        print(json.dumps(out) if not isinstance(out, str) else out)


if __name__ == "__main__":
    main()
