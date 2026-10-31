"""Stage 10's evaluation application 3: rag-api (LibreChat-AI/rag-api) in the lab, as a person would prepare it.
Everything here is human preparation: counted in docs/bench/stage10-evaluation.md and never attributed to Unbidden.

    uv run python -m bench.ecosystem.rag_api_lab up|seed|down [--volumes]

- `up`: clone the person's copy (~/rag-api) at the pinned release to ~/unbidden-lab/rag-api, write a compose file
  (the project's own published image of that release, the lite variant, and pgvector PostgreSQL as its compose uses,
  127.0.0.1 ports, owned resources; excluded from git), start it; the application creates its tables at start;
- `seed`: documents through SQL written from its models (the API embeds a document with a model to store it),
  generated, with deterministic placeholder vectors, nothing real; a read-only role;
- `down`: stop the project's containers, keeping the data volume unless `--volumes`.
No `JWT_SECRET`: its middleware lets every request through (no authentication). The embeddings key is a
placeholder: nothing calls a model, nothing leaves the lab.
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

UPSTREAM = Path.home() / "rag-api"  # the person's clone of https://github.com/LibreChat-AI/rag-api
COMMIT = "4985b37b8b5d4519d68eceedfef1e63624012f9d"  # v0.9.0, the latest release when chosen (2026-10-31)
IMAGE = "ghcr.io/danny-avila/librechat-rag-api-dev-lite:v0.9.0"  # the project's own image of that release
LAB_ID, PROJECT, PORT, DB_PORT = "rag-api", "rag-api-staging", 18170, 55500
URL = f"http://127.0.0.1:{PORT}"
SECRETS = "rag-api-secrets.env"
SPEC = {"database": "rag_api", "docs": "/openapi.json", "secret": "RAG_API_READER_PW"}  # read by app_eval
COMPOSE_FILE = """services:
  app:
    image: {image}
    ports:
      - "127.0.0.1:{port}:8000"
    environment:
      DB_HOST: db
      DB_PORT: "5432"
      POSTGRES_DB: rag_api
      POSTGRES_USER: rag_api
      POSTGRES_PASSWORD: "{pg}"
      EMBEDDINGS_PROVIDER: openai
      RAG_OPENAI_API_KEY: sk-placeholder-not-a-key
      RAG_HOST: 0.0.0.0
      RAG_PORT: "8000"
    depends_on:
      db:
        condition: service_healthy
    labels:
{labels}  db:
    image: pgvector/pgvector:pg16
    ports:
      - "127.0.0.1:{db_port}:5432"
    environment:
      POSTGRES_USER: rag_api
      POSTGRES_PASSWORD: "{pg}"
      POSTGRES_DB: rag_api
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rag_api -d rag_api"]
      interval: 2s
      retries: 30
    volumes:
      - rag-api-data:/var/lib/postgresql/data
    labels:
{labels}volumes:
  rag-api-data:
    labels:
{vlabels}"""
COMPOSE = ["docker", "compose", "-f", "docker-compose.lab.yml", "-p", PROJECT]


def _secrets(lab: Path) -> dict[str, str]:
    path = lab / SECRETS
    held = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    missing = {k: secrets.token_urlsafe(18) for k in ("RAG_API_PG", "RAG_API_READER_PW") if k not in held}
    if missing or not path.exists():
        held |= missing
        path.write_text("".join(f"{k}={v}\n" for k, v in held.items()))
        path.chmod(0o600)
    return held


def repo_dir(lab: Path) -> Path:
    return lab / "rag-api"


def up(lab: Path) -> None:
    repo, held = repo_dir(lab), _secrets(lab)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", "-q", str(UPSTREAM), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", COMMIT], check=True)
    compose = COMPOSE_FILE.format(image=IMAGE, port=PORT, db_port=DB_PORT, pg=held["RAG_API_PG"],
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
        "rag_api",
        "-d",
        "rag_api",
    ]
    return subprocess.run(argv, cwd=repo_dir(lab), input=sql, text=True, capture_output=True, check=True).stdout


def seed(lab: Path, files: int = 3000, chunks: int = 30_000, users: int = 300) -> dict[str, int]:
    """Document chunks of synthetic files, tagged as the project tags what it ingests (`file_id`, its chunk index
    and ingestion attempt, with `user_id`, `digest`, `source`, `page`), in the collection it creates at start. The
    vector is the same placeholder of the default model's 1536 dimensions for every chunk (no model is called).
    Generated and deterministic; nothing is real."""
    held = _secrets(lab)
    sql = [
        "BEGIN;",
        "DELETE FROM langchain_pg_embedding;",
        "INSERT INTO langchain_pg_embedding (uuid, collection_id, embedding, document, cmetadata, custom_id) "
        "SELECT md5('chunk' || g)::uuid, (SELECT uuid FROM langchain_pg_collection WHERE name = 'testcollection'), "
        "array_fill(0.01::real, ARRAY[1536])::vector, 'Synthetic chunk ' || g || ' of file ' || (g % "
        f"{files}), "
        f"jsonb_build_object('file_id', 'file-' || lpad((g % {files})::text, 5, '0'), "
        f"'user_id', 'user-' || lpad((g % {users})::text, 4, '0'), 'digest', md5('file' || (g % {files})), "
        f"'source', '/uploads/file-' || (g % {files}) || '.txt', 'page', g / {files}, "
        f"'_rag_chunk_index', g / {files}, '_rag_ingestion_attempt_id', md5('attempt' || (g % {files})), "
        f"'_rag_ingestion_attempt_started_at_ns', 1793400000000000000::bigint + (g % {files})::bigint * 1000000), "
        # custom_id is the file's id, as the project stores it (`/ids` lists them, `/documents?ids=` reads by them)
        f"'file-' || lpad((g % {files})::text, 5, '0') "
        f"FROM generate_series(1, {chunks}) g;",
        "COMMIT;",
        "ANALYZE;",
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_api_reader') THEN "
        f"CREATE ROLE rag_api_reader LOGIN PASSWORD '{held['RAG_API_READER_PW']}'; END IF; END $$;",
        "GRANT CONNECT ON DATABASE rag_api TO rag_api_reader; GRANT USAGE ON SCHEMA public TO rag_api_reader;",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO rag_api_reader;",
    ]
    _psql(lab, "\n".join(sql))
    counted = _psql(lab, "SELECT count(*), count(DISTINCT cmetadata->>'file_id') FROM langchain_pg_embedding;")
    return dict(zip(["chunks", "files"], map(int, counted.strip().split("|")), strict=True))


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
