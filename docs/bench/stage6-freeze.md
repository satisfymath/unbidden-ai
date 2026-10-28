# Stage 6: the frozen evaluation, protocol and budget (written before it runs)

Two questions, reported apart, plus the demo. Development evidence (Shopfront, Depot, the board's development set,
and Larder, which became development once fixed against) is not used here. The 2793504 trial is closed
(`docs/bench/stage5-freeze.md`, amendment 1) and its records stay as they are.

## What is frozen

- **Code and harness:** commit f334213 (frozen 2026-10-28); run from the worktree `~/unbidden-ai-eval6`
  checked out detached at it. The harness and the product come from the same tree; nothing changes during the runs.
  A fix found from these results is a new version, reported apart.
- **Models:** `muse-spark-1.3` (the `code` route, think budget 2048) for every arm except the declared Wonder arm
  (`muse-wonder-1.0`, same route); the local model (Ollama `auto`) for the local policy of A and as recorded
  fallback. SAM 3.1 only in the `vision_sam` method. Prices: dev.meta.ai list prices (D-042).
- **Oracles:** A: `linen_lab.oracle` (the harness's SQL over `requests`, Linen's stations read by the harness) and
  `linen_lab.effects` (`en_route` from the service itself). B: `board_check` (model-free; objective amendment 1).
- **Scenarios** (all written before any agent run on them):
  - A: Linen `k1`-`k4` (`bench/ecosystem/evaluate.py`, project `linen`): every page read, an extension of the
    integration (k2), a verified action, a repeat without duplication, approval pending (k3), revocation (k4).
  - B perception: set `eval` (10 states, stage 5, never run with the agent and never adapted to an answer).
  - B cycle with history: set `eval-cycle` (5 states, stage 5). B cycle without a healthy version in history: set
    `eval6-nohistory` (3 states). The two are reported apart.
- **Metrics:** A: connections as expected, reads complete, goal completed, actions on truly short stations,
  verified, false verifications (against the service's own state), duplicates, acts after revocation or without
  approval, interventions, calls, fallbacks, latency, spend. B perception (`score_found`): alerted, at least one
  wrong row named, all of them, rows named not wrong, precision, recall, cause named (rubric fixed per state),
  false alarms on healthy states, inconclusive answers, latency, cost. B cycle: the agent's own conclusion and the
  checker's verdict kept apart; completed (checker verified), false verification (agent says fixed or fine, checker
  does not verify), inconclusive, regressions, rows or information lost, unnecessary changes, interventions, calls,
  latency, spend.

## Repetitions and budget (from the ledger's stage 6 starting point, 2026-10-28T22:44:23Z)

| Part | Runs | Estimate |
|---|---|---|
| A, Spark x2 (k1-k4) | 8 | US$0.50 |
| A, local x1 (k1-k4) | 4 | US$0 |
| B perception, x2 (10 states x 3 methods) | 60 page checks, 60 SAM images | US$1.00 |
| B cycle with history, x1 (5 states x 3 methods) | 15 | US$1.10 |
| B cycle without history, x2 under dom (3 states), x1 under vision and vision_sam | 12 | US$0.90 |
| Wonder arm: B cycle without history, dom, x1 (3 states); hypothesis below | 3 | US$0.60 |
| **Total** | | **~US$4.10** of the US$5.00 evaluation share |

The cases without history get the extra repetitions because they are the critical, new ones. **Wonder hypothesis,
declared before running:** a repair with no healthy version to recover needs more reasoning from the code alone,
and Wonder completes more of those cases than Spark under the same perception. Compared on the same three states.
Every run counts as it comes: no run is repeated because it failed, and none is dropped because it did well. A cell
refused by the spend ledger is reported as such. Only after the evaluation does the reserve's US$2.00 for the demo
and contingencies get used.
