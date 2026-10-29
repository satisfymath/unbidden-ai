#!/bin/sh
# Independent reproduction (stage8-independent.md, measurement 1): the CI's test-unit job, SQLite variant (db-url ""),
# Python 3.13 (in its matrix), at the release, in a plain container; not Unbidden's sandbox.
set -e
SRC=$(mktemp -d)
git clone -q ~/lnbits "$SRC/lnbits" && git -C "$SRC/lnbits" checkout -q 9349da153c223b008f7d80453b53a54e09c8ed3d
docker run --rm --label unbidden.lab=ecosystem -v "$SRC/lnbits:/app" -w /app \
  -e LNBITS_BACKEND_WALLET_CLASS=FakeWallet -e LNBITS_DATABASE_URL= -e PYTHONUNBUFFERED=1 -e DEBUG=true \
  python:3.13-slim sh -c 'pip -q install uv && uv sync -q --locked --all-extras --dev && uv run pytest tests/unit -q -p no:cacheprovider 2>&1 | tail -15'
