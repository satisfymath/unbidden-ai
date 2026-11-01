# Paired comparison: `dev-b1-v0` → `dev-b1-v1`

15 repositories in both runs, same commits.

| Outcome | Before | After | Gained | Lost | McNemar p |
|---|---|---|---|---|---|
| stack_supported | 13/15 | 13/15 | 0 | 0 | 1.0 |
| dependencies_installed | 8/15 | 11/15 | 3 | 0 | 0.25 |
| analyzer_complete | 8/15 | 11/15 | 3 | 0 | 0.25 |
| bootstrapped | 8/15 | 11/15 | 3 | 0 | 0.25 |
| ci_understood | 15/15 | 15/15 | 0 | 0 | 1.0 |

## Repositories whose root cause changed (regressions first)

- NVIDIA__IsaacCapture: deps_missing_file → deps_resolution
- UKGovernmentBEIS__inspect_evals: deps_python_version → deps_vcs_source
- mistralai__mistral-common: deps_tool_version → findings_declined
- nesquena__hermes-webui: deps_stale_lockfile → findings_declined
- KeepSoftwareSimple__compass-calendar: deps_resolution → actionable
