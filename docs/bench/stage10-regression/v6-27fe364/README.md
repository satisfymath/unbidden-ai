# Regression v6 at product 27fe364: Prefect B-r12, interrupted

Frozen worktree `~/unbidden-ai-s10-27fe364`, `s10-dev`. Stopped by hand during its first cycle (about 70 min, with
A-r12 not started), recorded as interrupted; workspace archived to
`~/unbidden-lab/prefect-runs/v6-27fe364-B-r12-interrupted`. No record.json: the harness was stopped before writing it.

What it showed:
- The checks now run (eb23cef): 1033 tests collected in the CI's group 1 of 18, 11 failed (among them
  `tests._internal.test_release_workflows`), against `infra_failed` with nothing collected in v4/v5.
- Every experiment of the cycle was a static-analysis opportunity blocked at once ("cannot judge: incomplete reports
  from ruff, pyright", read from the per-commit cache), yet each took about 38 s: the Director's sweep after each one
  re-tokenized the whole CI for every one of 229 opportunities (profiled on a copy of the workspace: 94 s under the
  profiler, `observe/ci.py tool_invocations`). At one experiment per sweep the cycle would have reached its 5400 s
  limit. Fixed in 25152f0 (read once per CI text and tool; the same sweep then takes 4.3 s).
- Spend during the run: small (s10-dev 3.73 -> 3.96, including the start of the cycle).
