#!/bin/zsh
# The stage 6 frozen evaluation (docs/bench/stage6-freeze.md), from ~/unbidden-ai-eval6 at 94765da, in order.
W=~/unbidden-ai-eval6; O=~/unbidden-lab/eval6; cd $W
git -C $W log --oneline -1 > $O/commit.txt
step() { echo "== $1 $(date -u +%FT%TZ)" >> $O/steps.log; shift; "$@" >> $O/steps.log 2>&1; echo "-- exit $? $(date -u +%FT%TZ)" >> $O/steps.log; }
step A-local     uv run python -m bench.ecosystem.evaluate $W --project linen --policy local --out $O/A-local --label local
step A-spark-r1  uv run python -m bench.ecosystem.evaluate $W --project linen --policy spark --out $O/A-spark-r1 --label spark
step A-spark-r2  uv run python -m bench.ecosystem.evaluate $W --project linen --policy spark --out $O/A-spark-r2 --label spark
step B-perception uv run python -m bench.ecosystem.board_eval perception $W --set eval --reps 2 --policy spark --out $O/B-perception
step B-cycle-history uv run python -m bench.ecosystem.board_eval cycle $W --set eval-cycle --policy spark --out $O/B-cycle-history
step B-nohistory-dom uv run python -m bench.ecosystem.board_eval cycle $W --set eval6-nohistory --methods dom --reps 2 --policy spark --out $O/B-nohistory-dom
step B-nohistory-vision uv run python -m bench.ecosystem.board_eval cycle $W --set eval6-nohistory --methods vision,vision_sam --policy spark --out $O/B-nohistory-vision
step B-nohistory-wonder uv run python -m bench.ecosystem.board_eval cycle $W --set eval6-nohistory --methods dom --policy wonder --out $O/B-nohistory-wonder
echo "== done $(date -u +%FT%TZ)" >> $O/steps.log
