# Paired comparison: `dev-all-v2` → `dev-all-v3`

40 repositories in both runs, same commits.

| Outcome | Before | After | Gained | Lost | McNemar p |
|---|---|---|---|---|---|
| stack_supported | 24/40 | 24/40 | 0 | 0 | 1.0 |
| dependencies_installed | 21/40 | 22/40 | 1 | 0 | 1.0 |
| analyzer_complete | 20/40 | 20/40 | 0 | 0 | 1.0 |
| bootstrapped | 20/40 | 20/40 | 0 | 0 | 1.0 |
| ci_understood | 36/40 | 36/40 | 0 | 0 | 1.0 |

## Reach: repositories that got further or less far (regressions first)

- SakuraByteCore__codexmate: deps_tool_version → no_applicable_analyzer

## Decisions: analyzed in both runs, the Director chose differently

- Effect-TS__effect: actionable → findings_declined
- KeepSoftwareSimple__compass-calendar: actionable → findings_declined
- ValueCell-ai__ClawX: actionable → findings_declined
- firekylin__firekylin: actionable → findings_declined
- jdillon__vscode-beads: actionable → findings_declined
- marko-js__marko: actionable → findings_declined
- mistralai__mistral-common: actionable → findings_declined
- nesquena__hermes-webui: actionable → findings_declined
- quantumlib__Cirq: actionable → findings_declined
- southleft__figma-console-mcp: actionable → findings_declined
- vllm-project__tpu-inference: actionable → findings_declined
