# Stage 10 regressions, part 5: codex-lb B-1 at product 3cf779d (the driver where the plan collects), development

Worktree `~/unbidden-ai-s10-3cf779d`, `s10-dev` 9.36 -> 9.70 (US$0.34; cumulative 27.3527 -> 27.6945 of 37.2945),
3767 s. Workspace archived to `codex_lb-runs/codex_lb-reg-B-1-20261031T175549`. Four cycles, no intervention. The
first full cycle on codex-lb that reaches a measured experiment: checks, candidate, workload, deferral, sessions, the
CI job on both sides, a verdict.

- **Checks reproduced**: 6422 collected, 34 failed on both sides in every round (git and release-script tests, no
  `.git` in the snapshot: the same 34 as at 6f48b39; the author's run as its CI runs it had 2 failed, 71 skipped).
- **The candidate is written by the rule** (no model call): a migration `10c0468bb3ae` after the project's head
  and `index=True` on the multi-line `mapped_column` of `proxy_pool_members.endpoint_id`.
- **The driver is collected now.** Experiment 1: workload attempt 1 validated. Experiment 2: attempt 1 returned HTTP
  400 at warm-up, attempt 2 was cut off at the token limit, attempt 3 broke a unique constraint
  (`pool_id, endpoint_id`), attempt 4 validated. Both workloads build 2,000 pools, 2,000 endpoints and 200,000
  members at the base and measure `POST /api/settings/upstream-proxy/pools/{pool_id}/members`.
- **Host-load deferral worked as written**: 42 deferrals logged (load 1.5 - 5.6, the Prefect lab service and the
  earlier mealie run); each session records `host_load` and `host_waited_s` (0 - 390 s per session; measurement
  began at loads 1.18 - 1.47, under 1.5); no other service was stopped.
- **Verdict: no proven fix, twice.** Session medians 4.06 -> 4.13 ms (-2%, p 0.8, 95% interval -19% .. +3%) and
  4.08 -> 4.12 ms (-1%, p 0.757, -8% .. +7%). Declined after two experiments. Correct: the handler's uniqueness check
  (`_validate_proxy_pool_member_is_unique`, `api.py:399`) filters by `pool_id` and `endpoint_id` together, which
  the existing unique constraint already indexes; an index on `endpoint_id` alone adds nothing. The mechanism could
  not be observed either (`index_scans` None: the project's test job runs on SQLite, no PostgreSQL statistics).
- **The project's tests reject the candidate**: 37 failed against 34, the three new in `tests/unit/test_db_migrate`
  (revision remapping and the schema-migration contract). Recorded in the experiment; with no improvement the verdict
  did not need it, and with one it would have been a regression (`classify_tests`). A model- or rule-written
  migration must satisfy the project's migration tests: the next change to the rule, before any promotion on this
  project.
- Consistency: as before, blocked at the API bounds and bearer-only endpoints (the anonymous probe said so).
- No false conclusion; no action; nothing promoted.
