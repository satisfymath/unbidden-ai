#!/usr/bin/env bash
# The autonomous CLI demo, about three minutes, on a repository Unbidden has never seen.
#
#   demo/autonomous.sh [workdir]
#
# A fresh shallow clone of marshmallow at the commit pinned in bench/repos/scale.yaml, the benchmark's mandate
# (autonomous for local work; pull requests only to the satisfymath fork, never upstream; no merges; local fallback
# denied), then one full autonomous cycle. Nothing is chosen for it. What to watch for:
#   - it probes the package for crashes on its own (Muse Spark writes property tests, run offline);
#   - it finds type and lint findings, then reads the team's own CI through tox and the upstream's checks, and declines
#     them as differences of its own environment, before spending anything on them;
#   - every decision, payload and cent is on the record.
# Needs Docker, MODEL_API_KEY in ~/.unbidden/.env and network access to GitHub and api.meta.ai.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
work="${1:-$(mktemp -d)}/marshmallow"
commit=b762ea2d59ca52fe5df76b90de14bed7e5ec5607
unbidden() { uv run --project "$here" unbidden "$@"; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "a repository Unbidden has never seen: marshmallow at ${commit:0:12}"
mkdir -p "$work" && cd "$work"
git init -q && git remote add origin https://github.com/marshmallow-code/marshmallow
git fetch -q --depth 1 origin "$commit" && git checkout -q FETCH_HEAD

say "unbidden init, and the mandate: autonomous locally, pull requests only to the fork"
unbidden init
uv run --project "$here" python - <<'EOF'
import yaml
from pathlib import Path
from bench.scale import bench_mandate
path = Path(".unbidden/mandate.yaml")
raw = bench_mandate(yaml.safe_load(path.read_text()), profile="frontier", repo_budget_usd=0.10,
                    fork="satisfymath/marshmallow", local_fallback="deny")
path.write_text(yaml.safe_dump(raw, sort_keys=False))
EOF
unbidden route

say "one full autonomous cycle: observe, decide, probe, experiment, propose"
export UNBIDDEN_RUN="demo:marshmallow"
unbidden watch --once

say "what it found, and what it decided"
unbidden inbox --all
unbidden decide

say "everything that left the machine, byte counts and destinations"
unbidden egress --last 5

say "what it cost"
unbidden spend --run "$UNBIDDEN_RUN"
