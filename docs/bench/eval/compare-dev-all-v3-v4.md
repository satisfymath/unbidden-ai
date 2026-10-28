# Paired comparison: `dev-all-v3` → `dev-all-v4`

40 repositories in both runs, same commits.

| Outcome | Before | After | Gained | Lost | McNemar p |
|---|---|---|---|---|---|
| stack_supported | 24/40 | 27/40 | 3 | 0 | 0.25 |
| dependencies_installed | 22/40 | 25/40 | 3 | 0 | 0.25 |
| analyzer_complete | 20/40 | 25/40 | 5 | 0 | 0.0625 |
| bootstrapped | 20/40 | 25/40 | 5 | 0 | 0.0625 |
| ci_understood | 36/40 | 36/40 | 0 | 0 | 1.0 |

## Reach: repositories that got further or less far (regressions first)

- discobox-ai__discobox: no_applicable_analyzer → findings_declined
- gohugoio__hugoThemesSiteBuilder: no_dependency_manifest → nothing_found
- mirceanton__kubectl-switch: no_dependency_manifest → nothing_found
- moby__moby: no_dependency_manifest → nothing_found
- dsx-ai-factory__infra-controller: unsupported_language → nothing_found

## Decisions: analyzed in both runs, the Director chose differently

- firekylin__firekylin: findings_declined → actionable
