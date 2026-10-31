# Regression v8 at product bb6e552: Prefect B-r14 (cycles overlapped) and A-r14 (did not start)

Frozen worktree `~/unbidden-ai-s10-bb6e552`, `s10-dev`. B-r14: 21601 s, US$1.1381 (21.4010 -> 22.5391).

**Not valid as a clean run.** Each of the four cycles reached the harness's 5400 s bound. `subprocess.run(timeout=)`
killed only `uv run`; the daemon under it kept working, so each next cycle ran beside the one before on the same store,
and the output of every cycle was lost (cycles.log holds only the four "did not finish" lines). After the workspace
was archived a surviving daemon wrote `exp_80d82ee160d84a01.patch` into a new `.unbidden` (kept in
`~/unbidden-lab/prefect-runs/prefect-B-r14/after-archive/`), and A-r14 refused to start ("exists: archive it first").
Fixed in the harness (bench/ecosystem/cycle.py: own process group, SIGINT then SIGKILL to the group, output kept).

What it showed, kept as found:
- The type-check lab now runs on Prefect (b603744): 28+ experiments; three proposals at L4, branches ready, not
  published: `unbidden/1-pyright-error-in-benches-bench-flows-p-58475f`, `unbidden/3-pyright-errors-in-benches-bench-block-2e4a86`,
  `unbidden/4-pyright-errors-in-benches-bench-count-534ea5`.
- All three fix pyright errors in `benches/`, which the team's pyright does not check: the CI runs
  `pyright -p pyrightconfig-ci.json`, whose `include` is `src/` only. Unbidden ran pyright with its own scope (the whole
  tree). Their L4 is real for the code changed but not a fix to the team's standard; counted as such, not as wins.
  Fixed generically: the Director declines analyzer findings outside the scope the CI checks with that tool (its named
  paths, or its config's `include`/`files`).
- Spend rate about US$0.19 per hour of Prefect type-check experiments; s10-dev 5.5497 of 8.00 after this run.
