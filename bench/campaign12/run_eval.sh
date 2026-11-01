#!/bin/sh
# Campaign 12, phase 4: the frozen evaluation, in the order the protocol fixes, one thing at a time on this host.
#
#   bench/campaign12/run_eval.sh [A|B|all]
#
# Level A on every repository of the corpus (US$0), then Level B run 1 on the 12 chosen repositories, then run 2.
# Nothing here edits code or harness; a failed repository stays in its record and the next one starts. Logs under
# ~/unbidden-lab/c12/eval-*.log; records under docs/bench/campaign12/eval/.
set -u
here=$(cd "$(dirname "$0")/../.." && pwd)
cd "$here" || exit 1
what=${1:-all}
corpus=bench/campaign12/corpus.yaml
out=docs/bench/campaign12/eval
mkdir -p "$out" ~/unbidden-lab/c12
levelb=$(uv run python -c "import yaml; print(' '.join(r['name'] for r in yaml.safe_load(open('$corpus'))['repos'] if r['level_b']))")
# the installed tool must be the frozen wheel: its hash in the corpus, served from the campaign's local directory
want=$(uv run python -c "import yaml; print(yaml.safe_load(open('$corpus'))['wheel_sha256'])")
have=$(shasum -a 256 ~/unbidden-lab/c12/dist/unbidden_ai-0.9.0-py3-none-any.whl | cut -d' ' -f1)
if [ "$want" != "$have" ]; then echo "the served wheel ($have) is not the frozen one ($want); stop"; exit 2; fi
echo "== frozen wheel $have; installed: $(~/unbidden-lab/c12/home/bin/unbidden --version) $(date -u +%FT%TZ)"
if [ "$what" = A ] || [ "$what" = all ]; then
  echo "== Level A on the whole corpus $(date -u +%FT%TZ)"
  uv run python -m bench.campaign12.level_a "$corpus" --phase eval --out "$out" --port 8800 >> ~/unbidden-lab/c12/eval-A.log 2>&1
fi
if [ "$what" = B ] || [ "$what" = all ]; then
  for run in 1 2; do
    for repo in $levelb; do
      if [ -f "$out/$repo/B$run.json" ]; then echo "== $repo B$run exists; skipped"; continue; fi
      echo "== Level B $repo run $run $(date -u +%FT%TZ)"
      uv run python -m bench.campaign12.level_b "$corpus" --repo "$repo" --run "$run" --phase eval --out "$out" --port 8860 \
        >> "$HOME/unbidden-lab/c12/eval-B-$repo-$run.log" 2>&1
      echo "   exit $?"
    done
  done
fi
uv run python -m bench.campaign12.report "$out" --corpus "$corpus" --out "$out/REPORT-eval.md" > /dev/null
echo "== done $(date -u +%FT%TZ)"
