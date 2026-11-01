# Paired comparison: `val-v3` → `val-v4`

32 repositories in both runs, same commits.

| Outcome | Before | After | Gained | Lost | McNemar p |
|---|---|---|---|---|---|
| stack_supported | 18/32 | 21/32 | 3 | 0 | 0.25 |
| dependencies_installed | 16/32 | 19/32 | 3 | 0 | 0.25 |
| analyzer_complete | 18/32 | 21/32 | 3 | 0 | 0.25 |
| bootstrapped | 18/32 | 21/32 | 3 | 0 | 0.25 |
| ci_understood | 31/32 | 31/32 | 0 | 0 | 1.0 |

## Reach: repositories that got further or less far (regressions first)

- allisonhere__tidemail: no_dependency_manifest → nothing_found
- perkeep__perkeep: no_dependency_manifest → nothing_found
- sammy-ette__Hilbish: no_dependency_manifest → nothing_found

## Decisions: analyzed in both runs, the Director chose differently

- none
