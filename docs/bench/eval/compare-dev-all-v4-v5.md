# Paired comparison: `dev-all-v4` → `dev-all-v5`

40 repositories in both runs, same commits.

| Outcome | Before | After | Gained | Lost | McNemar p |
|---|---|---|---|---|---|
| stack_supported | 27/40 | 27/40 | 0 | 0 | 1.0 |
| dependencies_installed | 25/40 | 25/40 | 0 | 0 | 1.0 |
| analyzer_complete | 25/40 | 25/40 | 0 | 0 | 1.0 |
| bootstrapped | 25/40 | 25/40 | 0 | 0 | 1.0 |
| ci_understood | 36/40 | 36/40 | 0 | 0 | 1.0 |

## Reach: repositories that got further or less far (regressions first)

- none

## Decisions: analyzed in both runs, the Director chose differently

- KeepSoftwareSimple__compass-calendar: findings_declined → actionable
- jdillon__vscode-beads: findings_declined → actionable
- quantumlib__Cirq: findings_declined → actionable
- vllm-project__tpu-inference: findings_declined → actionable
