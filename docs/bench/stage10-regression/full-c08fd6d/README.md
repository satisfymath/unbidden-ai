# Stage 10 regressions, part 4: codex-lb B-1 at product c08fd6d (the rule-written index), development

Worktree `~/unbidden-ai-s10-c08fd6d`, `s10-dev` 8.60 -> 9.22 (US$0.62), 947 s. Workspace archived to
`codex_lb-runs/codex_lb-reg-B-1-20261031T164751` (the harness now suffixes a colliding name).

- Checks reproduced (6422 collected). Consistency: 18 questions investigated, blocked or failed as before (reads at
  their bounds; now a declared comparison is required, next product).
- **The candidate is written by the rule** (60da8ac held): `candidate: index on proxy_pool_members.endpoint_id,
  written from the finding`, no lint finding added, no model call for it.
- **Not measured: no valid workload in five attempts.** Every attempt's log reads `6422 deselected`: the driver test
  was never collected. The CI's pytest names its targets (`tests/unit tests/test_request_logs_options_api.py`); the
  driver was written to `tests/test_unbidden_workload.py`, outside them, and `-k test_unbidden_workload` matched
  nothing. A product defect in the lab's placement of its driver, not the model's; fixed next (the driver goes where
  the plan's pytest collects, and the plan names it).
- No false conclusion; no action.
