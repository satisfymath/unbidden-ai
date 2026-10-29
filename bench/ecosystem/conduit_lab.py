"""Stage 7: Conduit (nsidnev/fastapi-realworld-example-app) in the lab, as a person would prepare it. Everything here is
human preparation: it is counted in docs/bench/stage7-transfer-prep.md and never attributed to Unbidden.

    uv run python -m bench.ecosystem.conduit_lab up|seed|token|down

- `up`: clone at the pinned commit to ~/unbidden-lab/conduit, write `.env` and a compose override (127.0.0.1 ports,
  a named volume, the lab's label; both excluded from git), build and start the app and its PostgreSQL;
- `seed`: synthetic data through SQL (users, articles, tags, comments, favorites; generated, no real person), and a
  read-only role for Unbidden;
- `token`: a JWT for a synthetic user, obtained by registering through the app's own API (what a person would hand
  over as a credential);
- `down`: stop and remove the project's containers and volume.
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

import httpx

UPSTREAM = "https://github.com/nsidnev/fastapi-realworld-example-app.git"
COMMIT = "029eb7781c60d5f563ee8990a0cbfb79b244538c"
PROJECT, PORT, DB_PORT = "conduit-staging", 18110, 55440
URL = f"http://127.0.0.1:{PORT}"
# Human preparation, counted: the 2022 Dockerfile's `pip install poetry==1.1` now pulls poetry-core 1.9, which no
# longer has `poetry.core.toml`; the build fails. The same Dockerfile with the era's matching pair, given inline in
# the (untracked) override, so the application's repository stays as published. Then `pkg_resources` was missing at
# start: 2022's virtualenvs carried setuptools implicitly, today's do not; setuptools of that era is added to the venv.
DOCKERFILE = """FROM python:3.9.10-slim
ENV PYTHONUNBUFFERED 1
EXPOSE 8000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends netcat && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
COPY poetry.lock pyproject.toml ./
RUN pip install poetry==1.1.15 poetry-core==1.0.8 && poetry config virtualenvs.in-project true \\
    && poetry install --no-dev && .venv/bin/pip install setuptools==65.5.0
COPY . ./
CMD poetry run alembic upgrade head && poetry run uvicorn --host=0.0.0.0 app.main:app
"""
# Human preparation, counted: asyncpg 0.26.0 (the lock's) has no linux/arm64 wheel and the slim image has no compiler;
# the app image is built for linux/amd64 (emulated on this Apple Silicon machine), the lock untouched.
OVERRIDE = """services:
  app:
    platform: linux/amd64
    build:
      context: .
      dockerfile_inline: |
{dockerfile}
    ports: !override
      - "127.0.0.1:{port}:8000"
    environment:
      DATABASE_URL: "postgresql://postgres:{pg}@db/postgres"
    labels:
      unbidden.lab: ecosystem
      unbidden.lab.id: conduit
  db:
    ports: !override
      - "127.0.0.1:{db_port}:5432"
    environment:
      POSTGRES_PASSWORD: "{pg}"
    volumes: !override
      - conduit-data:/var/lib/postgresql/data
    labels:
      unbidden.lab: ecosystem
      unbidden.lab.id: conduit
volumes:
  conduit-data:
    labels:
      unbidden.lab: ecosystem
      unbidden.lab.id: conduit
"""
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.lab.yml", "-p", PROJECT]


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / "conduit-secrets.env"
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {
        k: secrets.token_urlsafe(18) for k in ("CONDUIT_PG", "CONDUIT_SECRET", "CONDUIT_READER_PW") if k not in held
    }
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(lab: Path) -> Path:
    return lab / "conduit"


def up(lab: Path) -> None:
    repo, held = repo_dir(lab), _secrets(lab)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "-q", UPSTREAM, str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", COMMIT], check=True)
    (repo / ".env").write_text(f"SECRET_KEY={held['CONDUIT_SECRET']}\nDEBUG=False\n"
                               f"DATABASE_URL=postgresql://postgres:{held['CONDUIT_PG']}@db/postgres\n")  # fmt: skip
    (repo / ".env").chmod(0o600)
    inline = "\n".join("        " + line for line in DOCKERFILE.splitlines())
    (repo / "docker-compose.lab.yml").write_text(
        OVERRIDE.format(port=PORT, db_port=DB_PORT, pg=held["CONDUIT_PG"], dockerfile=inline)
    )
    (repo / "docker-compose.lab.yml").chmod(0o600)
    exclude = repo / ".git" / "info" / "exclude"
    wanted = [".env", "docker-compose.lab.yml", ".unbidden/", "postgres-data/"]
    have = exclude.read_text().splitlines() if exclude.exists() else []
    exclude.write_text("\n".join([*have, *[w for w in wanted if w not in have]]) + "\n")
    subprocess.run([*COMPOSE, "up", "-d", "--build"], cwd=repo, check=True)
    for _ in range(120):
        try:
            if httpx.get(f"{URL}/api/tags", timeout=3).status_code == 200:
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
        "postgres",
    ]
    out = subprocess.run(argv, cwd=repo_dir(lab), input=sql, text=True, capture_output=True, check=True)
    return out.stdout


def seed(lab: Path, seed: int = 7_2026, users: int = 2000, articles: int = 20_000, comments: int = 300_000,
         favorites: int = 200_000) -> dict[str, int]:  # fmt: skip
    """Synthetic data at a size where reads that scan a table can be told from reads that use an index."""
    rng = random.Random(seed)
    tags = [f"topic{i}" for i in range(60)]
    held = _secrets(lab)
    sql = [
        "BEGIN;",
        "TRUNCATE commentaries, favorites, articles_to_tags, articles, tags, followers_to_followings, users "
        "RESTART IDENTITY CASCADE;",
        f"INSERT INTO users (username, email, salt, hashed_password, bio, image) SELECT 'user' || g, 'user' || g || "
        f"'@example.test', 'salt', 'not-a-real-hash', '', NULL FROM generate_series(1, {users}) g;",
        "INSERT INTO tags (tag) VALUES " + ", ".join(f"('{t}')" for t in tags) + ";",
        f"INSERT INTO articles (slug, title, description, body, author_id) SELECT 'article-' || g, 'Article ' || g, "
        f"'A synthetic article', repeat('Lorem ipsum ', 40), 1 + (g::bigint * 7919) % {users} "
        f"FROM generate_series(1, {articles}) g;",
        "INSERT INTO articles_to_tags (article_id, tag) SELECT g, 'topic' || (g % 60) "
        f"FROM generate_series(1, {articles}) g;",
        f"INSERT INTO commentaries (body, author_id, article_id) SELECT 'A synthetic comment', "
        f"1 + (g::bigint * 31) % {users}, 1 + (g::bigint * 104729) % {articles} FROM generate_series(1, {comments}) g;",
        f"INSERT INTO favorites (user_id, article_id) SELECT DISTINCT 1 + (g::bigint * 13) % {users}, "
        f"1 + (g::bigint * 7907) % {articles} FROM generate_series(1, {favorites}) g ON CONFLICT DO NOTHING;",
        "COMMIT;",
        "ANALYZE;",
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'conduit_reader') THEN "
        f"CREATE ROLE conduit_reader LOGIN PASSWORD '{held['CONDUIT_READER_PW']}'; END IF; END $$;",
        "GRANT CONNECT ON DATABASE postgres TO conduit_reader; GRANT USAGE ON SCHEMA public TO conduit_reader;",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO conduit_reader;",
    ]
    _ = rng  # deterministic SQL generation; the seed is recorded for the record
    _psql(lab, "\n".join(sql))
    totals = "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM articles), "
    totals += "(SELECT count(*) FROM commentaries), (SELECT count(*) FROM favorites);"
    counts = _psql(lab, totals).strip().split("|")
    return dict(zip(["users", "articles", "comments", "favorites"], map(int, counts), strict=True))


def token(lab: Path) -> str:
    """Register a synthetic user through the app and keep its token in the lab's secrets (never printed)."""
    name = "unbidden-reader"
    body = {"user": {"username": name, "email": f"{name}@example.test", "password": secrets.token_urlsafe(16)}}
    r = httpx.post(f"{URL}/api/users", json=body, timeout=10)
    if r.status_code != 201:
        raise SystemExit(f"registering the synthetic user answered {r.status_code}")
    jwt = r.json()["user"]["token"]
    path = lab / "conduit-secrets.env"
    lines = [ln for ln in path.read_text().splitlines() if not ln.startswith("CONDUIT_TOKEN=")]
    path.write_text("\n".join([*lines, f"CONDUIT_TOKEN=Token {jwt}"]) + "\n")
    path.chmod(0o600)
    return "held in conduit-secrets.env"


def down(lab: Path, volumes: bool = False) -> None:
    """Stop and remove the project's containers; its database volume only with `--volumes`."""
    repo = repo_dir(lab)
    if repo.exists():
        subprocess.run([*COMPOSE, "down", *(["-v"] if volumes else [])], cwd=repo, capture_output=True,
                       check=False)  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["up", "seed", "token", "down"])
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    parser.add_argument("--volumes", action="store_true", help="down: also remove the data volume")
    args = parser.parse_args()
    lab = Path(args.dir)
    actions = {"up": up, "seed": seed, "token": token, "down": lambda lab: down(lab, args.volumes)}
    result = actions[args.action](lab)
    if result is not None:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
