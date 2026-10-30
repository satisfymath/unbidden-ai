# Regression v4 at product 3b5b99d

Frozen worktree `~/unbidden-ai-s10-3b5b99d`, under `caffeinate -i`, envelope `s10-dev`. Both runs completed (not
interrupted). Cost US$0.8825 (18.9309 -> 19.8134); `s10-dev` at 2.4802 of 8.00 after the run.

## Spoolman B-r4 (966 s, US$0.3637)

- Checks reproduced (278 collected, 0 failed). Data restored: 200 vendors, 5000 filaments, 100000 spools.
- `filament.vendor_id` (opp_6ff3838db6bb4b7b): **verified absence**. 5 requests to the endpoints that use the column
  were sent and answered, and the engine shows none of them looks up `filament` by `vendor_id`. Expected outcome
  under D-061. Defect in the evidence text: the request summaries print empty (`PUT /api/v1/spool/{value}/measure:  |`),
  so the reason does not show what each call returned.
- Consistency of `GET /api/v1/spool/group` (opp_223d85cfc1ad4bb9): extending the integration with the read
  `Find_spool_groups_spool_group_get` failed, then was abandoned; the investigation stays waiting. Not explained yet.
- Robustness probe: 1 failed, 7 passed, 0 crashes, 0 property violations kept (L1).
- No branch, no interventions.

## Conduit R10-B-1 (4073 s, US$0.5188)

- One intervention: `deb.debian.org` granted to `egress.package_registries` (system build tools), as before.
- `favorites.article_id` (opp_8aa2df1342d54cdc): **improved, evidence L4** under perf-v4: 4 sessions per side,
  A/A control (base against base), confirmation in 4 new sessions per side, CI test job on both sides. Branch
  `unbidden/favorites-article-id-is-a-foreign-key-wi-d54cdc` ready; not published (github.com is not in the
  mandate's allowlist), as intended.
- `commentaries.article_id` (opp_c080efaea5fd41b1): no proven fix twice (927 -> 943 ms, p 0.8, interval [-4%, +2%]),
  declined.
- `GET /api/articles/feed` (opp_65ff7491fae54f8b): no proven fix twice (32.3 -> 32.5 ms), declined.
- opp_97b5ebc14ef54b6b: not measurable: no valid workload at the base after 5 attempts; the last failed with
  `asyncpg AmbiguousFunctionError: pg_catalog.date_part(unknown, unknown)` (untyped parameters in the written
  workload). Kept as found.
- Consistency of `GET /api/articles` and `/api/articles/feed`: inconclusive (no confirmed total), waiting.

## Reading

Both criteria from the handoff hold: Spoolman ends in a verified absence, and Conduit still reaches L4 with control
and confirmation. Open, not fixed in this regression: the empty request summaries in the absence reason, the failed
API extension on Spoolman, and workloads that send untyped parameters to Postgres functions.
