"""The stage 4 development lab: Depot (a bin store) and its pick history. Development only; not Dispatch.

    uv run python -m bench.ecosystem.depot_lab up|down|oracle|revoke-key|restore-key|faults [fault ...]

- database `depot` in the lab's PostgreSQL (127.0.0.1:55432): table `picks` (bin, units, picked_at), read by role
  `depot_reader`;
- Depot (`bench/ecosystem/depot.py`) on 127.0.0.1:18085, its faults set by `faults`;
- the application's repository `depotapp`, its compose project `depotapp-staging` naming both.
Truth: bins whose picks of the last 7 days exceed what they can supply (quantity - reserved + incoming).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import subprocess
import time
from pathlib import Path

from bench.ecosystem import lab as base
from bench.ecosystem import ownership
from bench.ecosystem.depot import Depot

NAME, PORT, SEED = "unbidden-lab-depot", 18085, 31_2026
SCRIPT = Path(__file__).with_name("depot.py")


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / "depot-secrets.env"
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in ("DEPOT_READER_PW", "DEPOT_KEY") if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def _database(lab: Path) -> None:
    exists = base._docker(
        "exec",
        base.PG,
        "psql",
        "-U",
        "postgres",
        "-At",
        "-c",  # pyright: ignore[reportPrivateUsage]
        "SELECT 1 FROM pg_database WHERE datname = 'depot'",
    ).stdout.strip()
    if exists == "1":
        base.align_password("depot_reader", _secrets(lab)["DEPOT_READER_PW"])
        return
    base._docker("exec", base.PG, "psql", "-U", "postgres", "-c", "CREATE DATABASE depot")  # pyright: ignore[reportPrivateUsage]
    rng = random.Random(SEED)
    rows = ",\n".join(
        f"('B{b:02d}', {rng.randint(1, 6)}, now() - interval '{d} days' - interval '2 hours')"
        for b in range(1, 12)
        for d in range(10)
        for _ in range(rng.randint(0, 2))
    )
    sql = f"""
CREATE TABLE picks (id serial PRIMARY KEY, bin text NOT NULL, units int NOT NULL, picked_at timestamptz NOT NULL);
INSERT INTO picks (bin, units, picked_at) VALUES {rows};
ANALYZE;
CREATE ROLE depot_reader LOGIN PASSWORD '{_secrets(lab)["DEPOT_READER_PW"]}';
GRANT CONNECT ON DATABASE depot TO depot_reader;
GRANT USAGE ON SCHEMA public TO depot_reader;
GRANT SELECT ON picks TO depot_reader;
"""
    subprocess.run(
        ["docker", "exec", "-i", base.PG, "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "postgres", "-d", "depot"],
        input=sql,
        text=True,
        capture_output=True,
        check=True,
    )


def set_faults(lab: Path, faults: list[str]) -> None:
    """Faults take effect at the service's next request (it reads them each time); its state is kept."""
    data = lab / "depot"
    data.mkdir(parents=True, exist_ok=True)
    (data / "faults").write_text("\n".join(faults) + "\n")


def _service(lab: Path) -> None:
    data = lab / "depot"
    data.mkdir(parents=True, exist_ok=True)
    if not (data / "keys").exists():
        (data / "keys").write_text(_secrets(lab)["DEPOT_KEY"] + "\n")
    if not (data / "faults").exists():
        (data / "faults").write_text("")
    if base._docker("ps", "-aq", "--filter", f"name=^{NAME}$").stdout.strip():  # pyright: ignore[reportPrivateUsage]
        base._docker("start", NAME)  # pyright: ignore[reportPrivateUsage]
        return
    base._docker(
        "run",
        "-d",
        "--name",
        NAME,
        *ownership.labels("depot"),
        "--user",
        f"{os.getuid()}:{os.getgid()}",  # pyright: ignore[reportPrivateUsage]
        "-v",
        f"{SCRIPT}:/app/depot.py:ro",
        "-v",
        f"{data}:/data",
        "-p",
        f"127.0.0.1:{PORT}:8080",
        "python:3.12-slim",
        "python",
        "-u",
        "/app/depot.py",
        "8080",
        "/data",
    )
    time.sleep(1.5)


APP_COMPOSE = """services:
  picker:
    image: python:3.12-slim
    command: ["python", "-m", "http.server", "8000"]
    ports:
      - "127.0.0.1:18095:8000"
    environment:
      PICKS_DB: postgresql://depot_reader@host.docker.internal:55432/depot
      DEPOT_API: http://host.docker.internal:18085
"""


def _app(lab: Path) -> Path:
    repo = lab / "depotapp"
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "docker-compose.yml").write_text(APP_COMPOSE)
        (repo / "README.md").write_text(
            "# Depot app\n\nPicks orders from bins. Staging: `docker compose -p depotapp-staging up -d`.\n"
        )
        git = ["git", "-C", str(repo), "-c", "user.name=dev", "-c", "user.email=dev@example.com"]
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "depot app"], check=True)
    subprocess.run(
        ["docker", "compose", "-p", "depotapp-staging", "up", "-d"], cwd=repo, check=True, capture_output=True
    )
    return repo


def oracle(lab: Path) -> dict[str, object]:
    rows = base._docker(
        "exec",
        base.PG,
        "psql",
        "-U",
        "postgres",
        "-d",
        "depot",
        "-At",
        "-c",  # pyright: ignore[reportPrivateUsage]
        "SELECT bin, sum(units) FROM picks WHERE picked_at > now() - interval '7 days' GROUP BY bin",
    ).stdout.splitlines()
    picks = {b: int(u) for b, u in (line.split("|") for line in rows)}
    bins = Depot(set()).bins  # the service's initial stock, by the same definition
    short = {
        b: picks.get(b, 0) - (v["quantity"] - v["reserved"] + v["incoming"])
        for b, v in bins.items()
        if picks.get(b, 0) > v["quantity"] - v["reserved"] + v["incoming"]
    }
    truth = {"picks_7d": picks, "short": {"depot": short}}
    (lab / "depot-oracle.json").write_text(json.dumps(truth, indent=1))
    return truth


def up(lab: Path) -> None:
    base.up(lab)
    _database(lab)
    _service(lab)
    _app(lab)
    oracle(lab)
    (lab / "depot-oracle-initial.json").write_text((lab / "depot-oracle.json").read_text())


def down(lab: Path) -> None:
    repo = lab / "depotapp"
    if repo.exists():
        ownership.compose_down("depotapp-staging", str(repo))
    ownership.down("depot")
    base.down(lab)
    (lab / "depot" / "faults").unlink(missing_ok=True)
    (lab / "depot" / "keys").unlink(missing_ok=True)


def set_key(lab: Path, valid: bool) -> None:
    key = _secrets(lab)["DEPOT_KEY"] if valid else secrets.token_urlsafe(18)
    (lab / "depot" / "keys").write_text(key + "\n")  # read by the service at its next request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["up", "down", "oracle", "revoke-key", "restore-key", "faults"])
    parser.add_argument("faults", nargs="*")
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    args = parser.parse_args()
    lab = Path(args.dir)
    {
        "up": up,
        "down": down,
        "oracle": oracle,
        "revoke-key": lambda p: set_key(p, False),
        "restore-key": lambda p: set_key(p, True),
        "faults": lambda p: set_faults(p, args.faults),
    }[args.action](lab)


if __name__ == "__main__":
    main()
