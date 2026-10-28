# Paired comparison: `val-v0` → `val-v3`

32 repositories in both runs, same commits.

| Outcome | Before | After | Gained | Lost | McNemar p |
|---|---|---|---|---|---|
| stack_supported | 18/32 | 18/32 | 0 | 0 | 1.0 |
| dependencies_installed | 15/32 | 16/32 | 1 | 0 | 1.0 |
| analyzer_complete | 13/32 | 18/32 | 5 | 0 | 0.0625 |
| bootstrapped | 13/32 | 18/32 | 5 | 0 | 0.0625 |
| ci_understood | 31/32 | 31/32 | 0 | 0 | 1.0 |

## Reach: repositories that got further or less far (regressions first)

- BUKOWSKIREAL__magpie-gemini-web: no_applicable_analyzer → nothing_found
- browseros-ai__BrowserOS: no_dependency_manifest → findings_declined
- RisorseArtificiali__anti-vocale: unsupported_language → nothing_found
- litenova__LiteBus: unsupported_language → nothing_found
- cloudflare__agents: deps_tool_version → actionable

## Decisions: analyzed in both runs, the Director chose differently

- none
