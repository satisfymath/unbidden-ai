# Stage 8: Conduit as a regression (a new version; not out-of-sample evidence)

Conduit became development when stage 8's fixes were made from its frozen run (9ef6a60, kept as it is). This run
checks the new version on it, from clean states, B before A, as in stage 7: runs `B-2` (proactive, no goal) then
`A-3` (the same general goal), with `bench/ecosystem/conduit_eval.py --runs B-2,A-3` from a worktree at the commit
named below. Same preparation as stage 7 (`stage7-transfer-prep.md`); same mandate: PyPI only as registries.

One declared human answer: if Unbidden asks to add a package registry it names, a person adds exactly that one, once,
and the run continues for two more cycles. That is counted as an intervention. Nothing else is granted or told.
The `articlesCount` defect stays Claude's observation; the agent is not told about it.

Measured: whether the project is reproduced (its checks run at the base); what is read and with which deviations;
what is found and how it is explained; whether an experiment runs and what it shows (an improvement measured with the
checks green on both sides, or a discard with evidence); what is asked of a person; the second cycle's repeats;
calls, models, latency, spend.
regression version: adb803d

## Second regression version

The first version's runs (adb803d, `B-2`, `A-3`) showed five defects, each fixed generally, none with
Conduit-specific code: one request per need and the held work released on the grant; deviations counted once per
operation, field and value; reads bounded by records (50 requests had stopped the listing at 5,000 of 20,000); and
handlers of routes mounted with `include_router` prefixes located (two endpoints had no handler, so their joins went
unexplained). Same protocol, same preparation, same single declared answer: runs `B-3` then `A-4`
(`--runs B-3,A-4`) from a worktree at the commit named below.
regression version 2: 37e2324

## Third regression version

The second version (37e2324) confirmed four of the fixes on Conduit: one request for the registry, answered once;
the five held jobs ran right after the grant (the robustness probe ran: 0 crashes); the listing read all 20,000
articles (its completeness stays unknown: no total is declared under a name the reader knows, and the read ended on
a short batch, so the integration is rejected and the goal blocks, as case C requires); deviations counted. It then
stopped every index experiment at "no the model of table ...": Conduit keeps its schema in Alembic migrations and
reads with SQL. Fixed generally (bea8adf): the schema comes from the migration that creates the table when no model
maps it, and a PostgreSQL test service counts as enforcing foreign keys. Runs `B-4` then `A-5` (`--runs B-4,A-5`),
same protocol, from a worktree at the commit named below, which is also the independent run's frozen commit.
regression version 3: 6bbf3a1

## Fourth regression version

The third version (6bbf3a1): B-4 wrote all four index candidates by rule (the migration-only path), then every
workload request was refused by Guardian's prompt scan (Conduit's tests log in with `password="password"`), and the
lab swallowed the refusal; A-5 as A-4. Fixed generally (16682f4): credential-looking values masked before asking,
refusals recorded, a masked value never flagged again. With the post-evaluation fixes from LNbits (da7a595), runs
`B-5` then `A-6` (`--runs B-5,A-6`) from a worktree at the commit named below.
regression version 4: fbf8d32

## Fifth regression version

The fourth version (fbf8d32): B-5 measured the base for the first time (a workload written on the third attempt ran
at the base, `commentaries.article_id`), then the candidate broke at import: the rule-written migration's
`str | None` annotation is a TypeError on Conduit's Python 3.9. The other three candidates had no workload that ran
(asyncpg task lifecycles, unique keys reused across attempts). A-6 as A-5, and its proactive part as B-5. US$0.34
for both. Fixed generally (853309d): the migration template carries no annotations. Runs `B-6` then `A-7` from a
worktree at the commit named below.
regression version 5: 995afd8

## Sixth regression version

The fifth version (995afd8): B-6 wrote the four candidates; no workload ran at the base for any (every failure on
event loops: Conduit's suite is asynchronous and the driver was a synchronous test that could not use its async
fixtures). A-7 as A-6. US$0.31 for both. Fixed generally (821ea27): an async driver, generated from the workload's
signature, when the suite's fixtures are coroutines. Runs `B-7` then `A-8` from a worktree at the commit named
below. This is the last regression version the stage's development budget allows.
regression version 6: f56b130

## What the sixth version showed (B-7, A-8)

**B-7** (50 min, US$0.14, one intervention: Debian's archive): the project's suite ran on both sides of every
experiment (90 tests, 3 rounds, none failed); four candidates written by rule, four workloads ran at the base.

| Candidate | Endpoint (Unbidden's workload) | Unbidden's verdict | Independent check (lab data, `conduit_indep.py`, query time, median of 15) |
|---|---|---|---|
| `commentaries.article_id` | `GET /api/articles/{slug}/comments` 26.0 -> 18.6 ms | improved, L4 | **confirmed**: the listing's query 8.43 -> 0.06 ms |
| `favorites.article_id` | `DELETE /api/articles/{slug}` 10.0 -> 1.7 ms | improved, L4 | **confirmed, conditionally**: 0.60 -> 0.20 ms once comments are indexed; alone 7.81 -> 7.26 ms, the cascade into the unindexed comments dominating on this data |
| `commentaries.author_id` | `DELETE .../comments/{id}` 2.5 -> 2.0 ms | improved, L4 | **not confirmed**: the delete finds the row by primary key (0.04 -> 0.03 ms); the 0.5 ms difference at the endpoint cannot come from this index. A false L4: base and candidate run in separate sandbox sessions, each seeding its own data, and a small absolute difference passed the criteria |
| `articles.author_id` | (two experiments) 32.4 -> 32.4 ms, 34.0 -> 35.7 ms | no effect, declined | consistent (not checked further) |

Proposals: three local branches (`unbidden/...`), each a single Alembic migration after the current head; none
pushed (pull requests denied by the mandate, `github.com` not an allowed destination). Applied together they would
leave three Alembic heads: each is a proposal on its own.

**A-8** (81 min, US$0.24): the goal blocked as before (the API's listing complete only as "unknown"); its proactive
part reproduced `commentaries.article_id` at L4 (24.8 -> 18.7 ms) on the second attempt.

The cycle is complete on Conduit: reproduced before any change, measured on both sides with the project's checks,
improvements proposed and a negative declined with evidence; one of the three improvements is a false positive.

## Addendum (stage 9): the sixth version's L4s re-judged

Under the corrected criteria (perf-v3, `stage9-revalidation.md`): `favorites.article_id` upheld (L4);
`commentaries.author_id` revoked (an artifact: no effect, the index never used); `commentaries.article_id` revoked
(18% at the endpoint, below the 20% threshold; inconclusive). The table above is kept as it was recorded.
