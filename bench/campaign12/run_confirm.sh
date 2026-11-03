#!/bin/sh
# Campaign 12, phase 7: the confirmation re-runs on the phase 6 candidate, under the s12-confirm envelope.
#
#   bench/campaign12/run_confirm.sh [A|A-debian|B|all]
#
# Level A on the whole corpus again with the default mandate (US$0, comparable with phase 4), then the documented
# variant with Debian's archive allowed on the tool cluster, then Level B run 1 on fst, misago, rich and spoolman
# (run 2 only if the envelope allows). Records under docs/bench/campaign12/confirm/; logs ~/unbidden-lab/c12/confirm-*.log.
set -u
here=$(cd "$(dirname "$0")/../.." && pwd)
cd "$here" || exit 1
what=${1:-all}
corpus=bench/campaign12/corpus.yaml
out=docs/bench/campaign12/confirm
mkdir -p "$out" ~/unbidden-lab/c12
want=$(uv run python -c "import yaml; print(yaml.safe_load(open('$corpus'))['confirm_wheel_sha256'])")
have=$(shasum -a 256 ~/unbidden-lab/c12/dist-confirm/unbidden_ai-0.9.0-py3-none-any.whl | cut -d' ' -f1)
if [ "$want" != "$have" ]; then echo "the served wheel ($have) is not the confirm candidate ($want); stop"; exit 2; fi
echo "== confirm wheel $have; installed: $(~/unbidden-lab/c12/home/bin/unbidden --version) $(date -u +%FT%TZ)"
debian="conduit,codex-lb,humanize,harlequin,graphtage,rdflib,archery"
if [ "$what" = A ] || [ "$what" = all ]; then
  echo "== Level A, default mandate $(date -u +%FT%TZ)"
  uv run python -m bench.campaign12.level_a "$corpus" --phase confirm --candidate confirm --out "$out" --port 8800 \
    >> ~/unbidden-lab/c12/confirm-A.log 2>&1
fi
if [ "$what" = A-debian ] || [ "$what" = all ]; then
  echo "== Level A, Debian allowed, tool cluster $(date -u +%FT%TZ)"
  uv run python -m bench.campaign12.level_a "$corpus" --phase confirm-deb --candidate confirm --debian --only "$debian" \
    --out "$out/debian" --port 8801 >> ~/unbidden-lab/c12/confirm-A-debian.log 2>&1
fi
if [ "$what" = B ] || [ "$what" = all ]; then
  for repo in fst misago rich spoolman; do
    if [ -f "$out/$repo/B1.json" ]; then echo "== $repo B1 exists; skipped"; continue; fi
    echo "== Level B $repo run 1 $(date -u +%FT%TZ)"
    uv run python -m bench.campaign12.level_b "$corpus" --repo "$repo" --run 1 --phase confirm --candidate confirm \
      --out "$out" --port 8860 >> "$HOME/unbidden-lab/c12/confirm-B-$repo-1.log" 2>&1
    echo "   exit $?"
  done
fi
uv run python -m bench.campaign12.report "$out" --corpus "$corpus" --out "$out/REPORT-confirm.md" > /dev/null
echo "== done $(date -u +%FT%TZ)"
