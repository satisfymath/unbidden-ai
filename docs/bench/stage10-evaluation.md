# Stage 10: a new frozen evaluation on applications never used before

Written before any candidate was looked at (2026-10-30). Development applications (Conduit, LNbits, Spoolman,
Prefect, and fst and mealie for revalidation) are not candidates. Nothing below changes once the first candidate is
inspected; the set, the product, the harness, the models, the modes, the acceptance conditions, the oracles, the
repetitions, the budget, the time limits and the invalidation rules are frozen together before any run.

## Selection rule (fixed now)

**Source, deterministic:** GitHub's public search API, unauthenticated, query
`language:Python topic:fastapi stars:>150 pushed:>2026-05-01 archived:false`, sorted by stars, descending,
read page by page. Candidates are examined in that order; the **first three** that pass every criterion form the set.
A candidate is never skipped for any reason not listed here, and never replaced after a run.

**Criteria** (the scope v1.0 declares):
1. An OSI-approved license identified by GitHub.
2. A Python project at the repository's root (`pyproject.toml`, `requirements.txt` or `setup.py` there) whose
   server is FastAPI.
3. PostgreSQL supported as its database (in its settings, compose files or documentation).
4. Its own tests in the repository, run by a GitHub Actions workflow.
5. Runnable locally with its database only: no other external service required to start and serve its API.
6. Its API documented by OpenAPI at a standard path, with no authentication, an API key in a header, or a login
   the project's own tests perform; OAuth with an external provider excludes it.
7. At most 300 MB on GitHub.
8. Not a template, a library, a tutorial or an example collection; not built from the RealWorld/Conduit
   specification; not used by Unbidden before.

Every inspection (which files were read, for which criterion) is recorded in this document before the next
candidate is examined.

## What the harness may prepare (human preparation, counted) and what Unbidden must do

Harness: clone the release (or the default branch's head when there is no release) and pin its commit; a compose
file written by the person with the project's published image or its Dockerfile, PostgreSQL, ports on 127.0.0.1
only, no privileged container, no Docker socket, owned resources; synthetic data through the project's own API or,
where the API cannot create a kind of record, SQL written from the project's models; a read-only database role.
Unbidden: everything else (reproducing the environment, the project's checks, finding, preparing and validating
workloads, measuring, concluding, abstaining). The harness never tells Unbidden anything about the application.

## Protocol (fixed now)

As stage 9 (`bench/ecosystem/app_eval.py`), per application: **B-1** (proactive, no goal), then **A-1** (the same
general goal for every application: "Readers must see correct and timely data: every number the API reports about
stored records must agree with what is stored, and the main listings must stay fast as the data grows", read-only),
each four cycles; one declared answer a person may give after cycle 2 (adding a package registry Unbidden names).
Meta's API only (Spark), `s10-eval` envelope, US$2.00 monthly cap per workspace, each cycle at most 90 minutes.

## Outcome classes and denominators

Reported per application and in total, with explicit denominators: environment reproduced; project checks run
(scope stated); opportunities investigated; workloads valid; experiments completed; improvements verified; justified
abstentions; technical blocks; false promotions. Each outcome is one of: useful improvement verified, absence
verified, technical block, inconclusive, false promotion.

**Independent measurement** (by the harness's author, after the runs, never by Unbidden): the project's own tests as
its CI runs them; every L4 re-measured from its spec outside Unbidden (the endpoint's own SQL with `EXPLAIN ANALYZE`
on the lab data, rolled back) and its patch run against the project's tests; every consistency finding recomputed
from the API and SQL; every abstention checked against the foreign keys, indexes and listing timings on the data.

**Evaluator controls** (development, before the freeze): the A/A and irrelevant-index controls and the seven v4
cases run on the frozen product, so a run that ends blocked is never read as proof that false positives cannot occur.

**Invalidation:** a run whose harness failed, or whose product tree changed during it, is invalid and reported as
such; it is not repeated inside the evaluation. A failure that needs a correction closes this version: the fix and
any repeat are regressions.

## Freeze (2026-10-31, before the first candidate is inspected)

- **Product:** commit 0102ccb, the tree the evaluator controls passed on (7 of 7 on a quiet host,
  `stage10-controls/0102ccb-run4`; the third run's inconclusive A/A on a noisy host is kept beside it). Frozen as
  hashes: `unbidden/` tree 577c03c03025a89678495e8f5640f52d53f3aff7, `pyproject.toml` 6f1c60dd626db4358fa9a310ca9396268ae87ec9,
  `uv.lock` 9c80aa6458810a803d0695888bc95ffa269d50f9. Every evaluation run is made from a worktree whose files have
  exactly these hashes; a run on any other product is invalid.
- **Harness:** commit 0fe4ecd: `bench/ecosystem/app_eval.py` f6b87cf79e5db8e911c1f9be980ae40f0e3a89e7,
  `bench/ecosystem/cycle.py` 299991beb6bdce328b478b9a4581915d60a66b4f, `bench/ecosystem/conduit_eval.py`
  0fef07d5c0ffa5a15c7ffaa9bb55673c1e1e4608. Each selected application adds its own preparation as new files only
  (`bench/ecosystem/<app>_lab.py`, its compose file and data), recorded and counted as human preparation; no frozen
  file changes.
- **Protocol:** this document's sections above, as committed in 2f3da12 (blob 81620c54fa2ede92ef0540ac576c3d347f500fa0),
  unchanged. Models: Meta's API only (Spark, `muse-spark-1.3`, the runner's config). Budget: envelope `s10-eval`,
  US$8.50, untouched at the freeze (cumulative cap US$37.2945, spent US$24.2976).
- **Host:** the runs are measured on the same machine as the controls; the controls showed that a busy host makes the
  A/A control inconclusive, so each run records the host's load and the lab services running.

## Choice

(to be filled, in order, before any run)
