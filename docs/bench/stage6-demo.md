# The demo: the screen contradicts the data; Unbidden finds why, fixes the code, and shows it holds

Recorded 2026-10-29 from the frozen code (94765da), `bench/ecosystem/board_demo.py`; records in `stage6-demo/`.

```sh
uv run python -m bench.ecosystem.depot_lab up       # once: the lab's PostgreSQL (127.0.0.1)
uv run python -m bench.ecosystem.board_demo "$PWD" --case style --perception dom --policy spark
```

**What the harness prepared, and says so.** The scenario is staged: the board's repository (a lab app) gets one
seeded defect in a commit titled "board: tidy layout and wording"; the data are seeded (24 bins, 12 short). Before
Unbidden runs, the model-free checker sees 12 short bins and 0 correctly flagged. Unbidden is given a workspace as a
person would give it: the goal (no hint of the defect), read-only grants to the picks database and the Depot API,
the app's declared check and deploy steps, the lab's staging only. The case's name appears nowhere Unbidden reads.

**What Unbidden did on its own** (two cycles, 89 s):
1. *Goal and discovery:* mapped the project (the compose service, its published page, the two granted sources).
2. *Missing capability:* the Depot API had no integration; Forge built one from its OpenAPI document and its oracle
   validated it on the live service (complete reads, the refused key).
3. *Observation:* read both sources whole, computed what each bin should show, scanned the page in a confined
   browser: 12 rows shown wrongly; cause, in its words: "The SHORT badge uses the same green success styling as OK
   instead of white text on a red alert background."
4. *Action:* found the commit that recoloured the badge in the repository's history, changed one CSS rule in a
   worktree (`patch.diff`), ran the app's tests offline, committed, deployed with the declared steps.
5. *Verification:* scanned again (no discrepancy), and the next cycle found nothing to do and changed nothing.

**What the independent checker says** (not the agent's code, not a model): verified; 12 of 12 short bins flagged on
their rows; no false flags; inventory, pick history and the page's other information unchanged.
Before / after: `before-step-00.png`, `after-step-00.png`.

**What Meta contributed:** `muse-spark-1.3`, 8 calls, US$0.07: planning the goal (3), choosing the integration's
operations (1), comparing the page with the data (3), writing the fix (1). Everything else is Unbidden's own code:
the reads, the arithmetic, the scan, the checks, the deploy, and the refusal of anything outside the grants.

**Human help during the run:** none. Before it: a person wrote the goal, the grants and the deploy steps (the
workspace), and the harness staged the defect.

**What it does not show:** a real application or production system; defects of other kinds; that this works on any
stack. The evidence covers PostgreSQL, OpenAPI 3.0/3.1 REST services within the declared contracts, and local pages
(RESULTS.md, stages 3-6).
