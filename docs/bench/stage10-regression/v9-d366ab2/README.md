# Regression v9 at product d366ab2: Prefect A-r15, stopped by hand

Frozen worktree `~/unbidden-ai-s10-d366ab2`, `s10-dev`, started 02:40, stopped at about 04:45 (local) during its second
cycle to save the envelope (s10-dev 5.5497 -> 6.0498, US$0.50). No record.json (the harness was stopped); workspace
archived to `~/unbidden-lab/prefect-runs/v9-d366ab2-A-r15-stopped`. Only A was run: B's behaviour at this product
was shown by B-r14, and a full B+A would have spent most of what remains of s10-dev.

What it showed:
- The harness fix holds: cycle 1 reached its 5400 s bound and its process group was stopped; one daemon at a time.
- The API integration was validated and is in use (bb6e552): attempt 1 rejected (before the fix's case), then
  validated; the goal reached a real comparison of the database and the API.
- The goal's comparison was inconclusive, twice: the read-only SQL stopped at its 1000-row limit (flow_run has
  10000 rows) while the API read all 10000 complete, and the join found 0 keys in common. Open: the SQL limit against
  a complete API read, and why no key matched (likely the id's form: uuid in Postgres, string in JSON).
- The CI-scope rule (70ce2e8) declined 26 pyright findings outside `src/`. Three new proposals reached L4, all in
  `src/integrations/`, which pyrightconfig-ci.json lists under `ignore`: not the team's standard either. Fixed in
  1170909 (a config's exclude/ignore are part of the scope).
- Two foreign-key index opportunities (`work_pool.default_queue_id`, `deployment.concurrency_limit_id`) were open
  for experiments when it was stopped.
