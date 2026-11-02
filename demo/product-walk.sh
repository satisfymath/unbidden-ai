#!/bin/sh
# The product walk, reproducible from the installed artifact: install -> setup -> start --ui -> dashboard with real
# events -> chat -> a widget -> stop (dashboard withdrawn) -> reopen the same dashboard -> stop/resume without
# duplicate executors. About six minutes; one or two paid calls (the robustness probe, one chat analysis).
#
#   demo/product-walk.sh <repo-dir> [--base URL] [--home DIR] [--port N]
#
# <repo-dir> is a git checkout to work on (the demo of 2026-11-01 used the fork satisfymath/rich at 9d8f9a372cc5).
# --base is where the wheel and SHA256SUMS are served: a local `python3 -m http.server` over `dist/` today (there is
# no public release yet); the GitHub release URL once one exists. --home is the HOME the installed tool uses (empty
# by default: nothing of the person's machine except what is listed below). Evidence goes to <home>/walk/.
#
# What the walk reuses from the host, said plainly:
#   - the machine's spend ledger (UNBIDDEN_HOME) so every paid call counts in the real budget; set UNBIDDEN_ENVELOPE
#     when the ledger is split into envelopes;
#   - MODEL_API_KEY read from MODEL_KEY_FILE (default ~/.unbidden/.env of the real HOME) and passed to setup on
#     stdin: never printed, never in argv;
#   - the Docker daemon and its CLI plugins (DOCKER_CONFIG of the real HOME: buildx builds the sandbox images).
# Needs: git, Docker with buildx and compose, network to api.meta.ai. Ollama is not needed (option api).
set -eu

repo=${1:?usage: demo/product-walk.sh <repo-dir> [--base URL] [--home DIR] [--port N]}; shift
base=http://127.0.0.1:8780; home=""; port=8840
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base=$2; shift 2 ;;
    --home) home=$2; shift 2 ;;
    --port) port=$2; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
real_home=$HOME
here=$(cd "$(dirname "$0")/.." && pwd)
home=${home:-$(mktemp -d)}
mkdir -p "$home/walk"
log="$home/walk/walk.log"
export UNBIDDEN_HOME="${UNBIDDEN_HOME:-$real_home/.unbidden}"
export DOCKER_CONFIG="${DOCKER_CONFIG:-$real_home/.docker}"
export MODEL_KEY_FILE="${MODEL_KEY_FILE:-$real_home/.unbidden/.env}"
export UNBIDDEN_RUN="${UNBIDDEN_RUN:-product-walk}"
export HOME="$home" UV_TOOL_DIR="$home/tools" UV_TOOL_BIN_DIR="$home/bin" UNBIDDEN_INSTALL_BASE="$base"
U="$home/bin/unbidden"
say() { printf '\n== %s  (%s)\n' "$*" "$(date -u +%H:%M:%SZ)" | tee -a "$log"; }
run() { echo "\$ $*" | tee -a "$log"; "$@" 2>&1 | tee -a "$log"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

say "1. install the wheel from $base into an empty HOME ($home)"
run sh "$here/install.sh" --yes --version "${UNBIDDEN_VERSION:-0.9.0}"
run "$U" --version

say "2. setup: option api (no Ollama), supervised, US\$1.5 a month; the key over stdin from $MODEL_KEY_FILE"
cd "$repo"
grep '^MODEL_API_KEY=' "$MODEL_KEY_FILE" | cut -d= -f2- | "$U" setup --non-interactive --models api --mode supervised \
  --budget 1.5 --dashboard later --model-key-stdin --yes --json > "$home/walk/setup.json" 2>"$home/walk/setup.txt"
json "'setup:', {k: d[k] for k in ('applied','models','mode','budget_usd','credentials_saved')}" < "$home/walk/setup.json" | tee -a "$log"
run "$U" doctor
run "$U"

say "3. the agent, in the background, serving its own dashboard"
run "$U" start --ui --port "$port" --interval 60
echo "waiting for the first cycle (project checks in the sandbox, the robustness probe)..." | tee -a "$log"
for i in $(seq 1 60); do
  sleep 10
  n=$("$U" status --json | json "d['agent']['jobs_queued'] + d['agent']['jobs_running']")
  ev=$(python3 -c "import sqlite3; print(sqlite3.connect('.unbidden/state.db').execute('select count(*) from events').fetchone()[0])")
  printf '  t+%ss queue=%s events=%s\n' "$((i*10))" "$n" "$ev" | tee -a "$log"
  [ "$i" -ge 9 ] && [ "$n" = 0 ] && break
done
run "$U" status
tail -n 12 .unbidden/logs/agent.log | tee -a "$log"

say "4. the dashboard: real events of this cycle"
TOKEN=$(python3 -c "import json;print(json.load(open('.unbidden/ui.json'))['token'])")
PORT=$(python3 -c "import json;print(json.load(open('.unbidden/ui.json'))['port'])")
sid="live:$(basename "$repo")"
api="http://127.0.0.1:$PORT/api/ws/$sid"
curl -fsS -H "Authorization: Bearer $TOKEN" "$api/summary" > "$home/walk/summary.json"
json "'summary:', d['workspace']['mode'], d['freshness'], 'counts', d['counts'], 'agent', d['connection']['agent']['detail']" < "$home/walk/summary.json" | tee -a "$log"
curl -fsS -H "Authorization: Bearer $TOKEN" "$api/events?limit=200" > "$home/walk/events.json"
json "'events:', len(d['items']), 'by type', __import__('collections').Counter(e['type'] for e in d['items'])" < "$home/walk/events.json" | tee -a "$log"
if [ -n "${WALK_SCREENSHOT:-}" ]; then
  "$WALK_SCREENSHOT" "http://127.0.0.1:$PORT/?s=$TOKEN" "$home/walk/dashboard-live.png" | tee -a "$log" || true
fi

say "5. chat: a status question (rules, no model) and one analysis (one routed call)"
run "$U" chat "¿Qué ha hecho el agente hasta ahora y cuántas oportunidades hay?"
run "$U" chat "¿Por qué no hay todavía una oportunidad probada y qué revisarías primero?"

say "6. a widget from existing data, by rules, with its provenance"
curl -sS -N -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -X POST "$api/chat" \
  -d '{"content":"Añade una tabla con las oportunidades","selected":[],"planner":"rule"}' > "$home/walk/widget.sse"
curl -fsS -H "Authorization: Bearer $TOKEN" "$api/presentation" > "$home/walk/presentation-1.json"
json "[(w['type'], w['title'], w['provenance']['source'], w['provenance']['completeness']) for w in d['widgets']]" < "$home/walk/presentation-1.json" | tee -a "$log"

say "7. stop the agent (its dashboard goes with it); reopen the dashboard apart: the same space"
run "$U" stop
test -e .unbidden/ui.json && echo "ui.json still there" | tee -a "$log" || echo "ui.json withdrawn" | tee -a "$log"
run "$U" ui --port "$port"
TOKEN=$(python3 -c "import json;print(json.load(open('.unbidden/ui.json'))['token'])")
PORT=$(python3 -c "import json;print(json.load(open('.unbidden/ui.json'))['port'])")
curl -fsS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/ws/$sid/presentation" > "$home/walk/presentation-2.json"
python3 - "$home/walk" <<'PY' | tee -a "$log"
import json, sys
a = json.load(open(f"{sys.argv[1]}/presentation-1.json")); b = json.load(open(f"{sys.argv[1]}/presentation-2.json"))
print("same widgets after reopen:", [w["id"] for w in a["widgets"]] == [w["id"] for w in b["widgets"]], len(b["widgets"]))
PY
if [ -n "${WALK_SCREENSHOT:-}" ]; then
  "$WALK_SCREENSHOT" "http://127.0.0.1:$PORT/?s=$TOKEN" "$home/walk/dashboard-reopened.png" | tee -a "$log" || true
fi
run "$U" ui --stop

say "8. stop and resume: one executor, no duplicate effects"
run "$U" start --interval 3600
run "$U" start --interval 3600
echo "watch processes: $(pgrep -f 'unbidden.cli watch' | wc -l | tr -d ' ')" | tee -a "$log"
run "$U" stop
run "$U" status

say "spend of this walk"
"$U" spend --json | json "'run', d['by_run'].get('$UNBIDDEN_RUN'), '| envelopes', d.get('envelopes'), '| available', d['available_usd']" | tee -a "$log"
echo; echo "evidence in $home/walk; the tool stays installed in $home (sh install.sh --uninstall --yes to remove it)" | tee -a "$log"
