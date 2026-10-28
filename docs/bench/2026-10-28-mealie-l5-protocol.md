# mealie L5 on SQLite: protocol, fixed before the run (2026-10-28)

D-036 found the index Unbidden wrote for mealie (D-035) brings nothing on Postgres, whose planner already avoids the
cost, and that its live result was invalid because the baseline's code was inferred. A valid level 5 needs two
deploys Unbidden made itself, on the engine where the effect exists. This is that test, and its outcome is reported
whatever it is.

## What runs

- **Code.** Baseline `e31c5fc` (mealie's upstream `3a9d78e` plus a Postgres compose override that a SQLite deploy does
  not use). Change `a351dc2`, the commit Unbidden wrote in D-035. Their difference is the index alone: one Alembic
  migration and `index=True` on `shopping_list_items.food_id`. No other change.
- **Where.** A separate git worktree of mealie (`~/mealie-sqlite`, branch `unbidden-sqlite`) with its own workspace and
  compose project (`mealie-sqlite`), so D-036's workspace, ledger and volumes are not touched. SQLite, mealie's
  default engine (`DB_ENGINE: sqlite` in `docker/docker-compose.yml`).
- **Deploys.** Both through `unbidden deploy <ref>` (the guarded deploy path), with the steps
  `docker compose -p mealie-sqlite -f docker/docker-compose.yml up -d --build --wait mealie`. Each deploy's commit
  must be `verified` in the ledger (built by Unbidden's own steps from that commit); otherwise the run is invalid.
- **Data.** Synthetic, seeded through mealie's API as the probe user after the baseline deploy and before the
  baseline window, the same shape as D-036: 50 shopping lists x 100 items (5,000) over 580 foods, 80 % checked off.
  The data is not changed between the two windows. The index's effect grows with foods x items; this is a large
  household, not mealie's typical size, and is reported as such.
- **Measured.** `GET /api/foods/empty` and every other probed endpoint, by Unbidden's live watcher.
- **Criteria.** The impact criteria in force (v2: effect floor max(0.2 ms, 3 MADs of the baseline's round medians),
  at least 15 samples per side), unchanged for this run. Outcome classes as in D-022: positive, negative, inconclusive,
  invalid. Level 5 only for a positive outcome between two `verified` deploys.

## What would make it invalid

A deploy not `verified`; a probe window shorter than the criteria require; the data changed between windows; another
heavy workload on the machine during a window (the evaluation program's runs are paused while it runs).

## What it does not show

An effect for real mealie households of typical size, user traffic (the probes are Unbidden's), or anything on
Postgres (D-036).
