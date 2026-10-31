# Regression v10 at product dec7ba2: Prefect A-r16, stopped by hand once the pending fixes were seen

Frozen worktree `~/unbidden-ai-s10-dec7ba2`, `s10-dev` 6.40 -> 7.31 (US$0.91), started 08:50, stopped 11:53 (local)
during cycle 2. No record.json (the harness was stopped); workspace archived to
`~/unbidden-lab/prefect-runs/v10-dec7ba2-A-r16-stopped`. Run to verify 1170909 and 458760f on a real run.

- 1170909 (a config's exclude/ignore in the scope): verified. 355 pyright findings declined with "the team's CI
  checks pyright only in src, except client, src/integrations, ...". No pyright proposal this time.
- 458760f (goal join on keys as text): verified. The goal joined 1000 keys (0 before). Two runs inconclusive: the
  read-only SQL stopped at its 1000-row limit while the API read flow_run complete (open, as before).
- New, open: a third goal plan compared `COUNT(*)` of flow_run_state per run (states) with the API's `run_count`
  (executions) and reported "1000 of 1000 keys short; nothing to change": two different quantities. Read-only, no
  action; a false consistency finding if reported as one. The plan was the model's.
- Three mypy proposals reached L4 (`src/prefect/_internal/...`, `src/prefect/utilities/...`): Prefect's CI runs mypy
  through pre-commit, whose `files:` pattern holds four directories, none of them. Not the team's standard. Fixed in
  the next commit (a pre-commit hook's files/exclude are the tool's scope), verified offline on Prefect's own config;
  not run again (s10-dev has US$0.69 left).
