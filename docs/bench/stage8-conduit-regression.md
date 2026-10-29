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
