# Stage 5: the frozen evaluation, protocol and budget (written before it runs)

Two questions, reported apart. Nothing here is development evidence; development used Shopfront, Depot and the
board's development set (`docs/bench/ecosystem/RESULTS.md`, stage 5). Dispatch and Depot are not used.

## What is frozen

- **Code and harness:** one commit (filled in at the freeze, below), run from the frozen worktree
  `~/unbidden-ai-eco` checked out detached at it. The harness and the product come from the same tree. No change to
  either during the runs; a fix found from these results makes a new version, reported apart, not this trial.
- **Models:** `muse-spark-1.3` on the `code` route (think budget 2048), Meta API; the local model as configured
  (Ollama, `auto`) for the local policy and as recorded fallback. Prices: dev.meta.ai list prices (D-042).
- **Oracles:** question A: `larder_lab.oracle` (the harness's SQL over `distributions`, Larder's items read by the
  harness) and `larder_lab.effects` (`inbound` read from the service itself); question B: `board_check` (model-free;
  amendment 1 of the objective).
- **Scenarios:** A: `a1`-`a4` (`bench/ecosystem/evaluate.py`, project `larder`); B perception: set `eval` (10
  states); B cycle: set `eval-cycle` (5 states) (`bench/ecosystem/board_eval.py`). Written in commit 8437b48 before
  any run on them.
- **Metrics:** A: connections as expected, reads complete, goals completed, actions on truly short items, verified,
  false verifications (claimed against the service's own state), duplicates, acts after revocation, interventions,
  calls, fallbacks, latency, spend. B perception: detection, rows named (precision, recall against the checker),
  cause localization (rubric fixed per state), false alarms on healthy states, unreadable answers, latency, cost.
  B cycle: completed (checker verified), false verification, regressions, information or rows lost, unnecessary
  changes, interventions, calls, latency, spend.
- **Repetitions:** A: Spark x2 per scenario, local x1 per scenario. B perception: x2 per state and method. B cycle:
  x1 per state and method. One run per cell is descriptive evidence, not a basis for claims of superiority.

## Budget

| Part | Calls (est.) | Estimate |
|---|---|---|
| A, Spark x2 (8 runs) | ~40 | US$0.45 |
| A, local x1 (4 runs) | 0 remote | US$0 |
| B perception (10 states x 3 methods x 2) | 60 + 60 SAM images | US$0.95 |
| B cycle (5 states x 3 methods x 1) | ~75 | US$1.20 |
| **Total** | | **~US$2.60** |

Cap: the reserve held for evaluation and demo, US$3.00 (D-042). The spend ledger refuses any call that would not
fit; a refused call is recorded as a failure of that cell, not retried around. What is left after the evaluation
(about US$0.40) is for the demo.

## The one human intervention needed

The reserve is released only by a person: `unbidden spend --release-reserve` (it moves the US$3.00 held back into
what may be spent; nothing else changes: no recharge, no card, no other permission). Development spend is within
its own US$5.00 cap. Nothing in the evaluation runs before this release.

## Rules while it runs

No code or harness change; failures and invalid runs kept with their cause; a lab problem (a container that did not
start) invalidates that cell, which is rerun once and both are reported.
