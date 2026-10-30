# Stage 9: the frozen evaluation on applications never used in development

Registered before any run on these applications. Development (Conduit, LNbits) stopped at the product commit named
at the end; nothing of the product, the harness, the scenarios or the criteria changes during the evaluation. If a
failure needs a correction, this version is closed and reported as it is; any later repetition is a regression, not
out-of-sample evidence.

## Choice

**Rule** (written before looking at any candidate's code): a public repository under an OSI license; active in the
last six months; the Python project at the repository's root, its server built on FastAPI; PostgreSQL among its
databases; an OpenAPI document at a standard path, and either no authentication or an API key in a header (the
scope v1.0 declares); its own tests run by its CI; runnable locally with its database only (no other external
service), on synthetic data; at most 300 MB on GitHub; never used in development or in an earlier evaluation, and not
built from the RealWorld/Conduit specification. Every candidate that passes is evaluated: no candidate is dropped
after a run, and none is added.

Candidates were listed from general knowledge of public Python web applications and two web searches (which
returned templates, not applications); metadata was read from GitHub's public API only.

| Candidate | Passes? | Why |
|---|---|---|
| Donkie/Spoolman | **yes** | MIT; FastAPI at the root; PostgreSQL, SQLite, MariaDB, CockroachDB; OpenAPI at `/api/v1/openapi.json`; no authentication; integration tests in CI (compose, one per database) |
| PrefectHQ/prefect (server) | **yes** | Apache-2.0; FastAPI server at the root (`src/`); PostgreSQL or SQLite; OpenAPI at `/api/openapi.json`; no authentication by default; pytest in CI against PostgreSQL 14 (18 groups); 252 MB |
| evroon/bracket | no | its Python is in `backend/` (a subproject: the lab has no per-subproject environment, a known limit), and its API is OAuth2 (out of scope) |
| keephq/keep | no | license not OSI-identified on GitHub |
| TracecatHQ/tracecat | no | needs Temporal and MinIO beside its database |
| fief-dev/fief | no | license not OSI-identified; inactive for eleven months |
| polarsource/polar, open-webui/open-webui, Agenta-AI/agenta, MODSetter/SurfSense, zenml-io/zenml, argilla-io/argilla, Skyvern-AI/skyvern | no | larger than 300 MB, and some with licenses not OSI-identified |
| ethyca/fides, Netflix/dispatch | no | archived |
| lnbits/lnbits, mealie, Conduit, full-stack-fastapi-template | no | used in development |

**Pinned:** Spoolman **v0.27.0** (`bed3f14ee77a3a571d31b14215d54b0b88a7519c`, 2026-09-25, latest release); Prefect
**3.9.0** (`1ef3e516d3b3449d19f65b30c45d1e0bff656396`, 2026-10-21, latest 3.x release).

**Disclosed:** while writing Spoolman's synthetic data, the harness's author read its table models (to name columns)
and saw two foreign keys declared without an index. The selection had already been made by the rule; nothing in the
product, the goal or the harness refers to it. Prefect's schema was not read: its data is written through its API. During development (2026-10-30), the CI reader
(`ci_test_plan`) was also run once on both applications' repositories while checking it on LNbits: Spoolman gave no
plan, Prefect a job of `api-compatibility-tests.yaml`. Nothing was changed because of either result, and neither
repository was used again before the freeze; they are recorded here so the reader knows they were seen.

## Labs (human preparation, counted)

`bench/ecosystem/spoolman_lab.py`, `bench/ecosystem/prefect_lab.py`: a clone of the release in
`~/unbidden-lab/<app>`; the project's own published image of that release (`ghcr.io/donkie/spoolman:0.27.0`,
`prefecthq/prefect:3.9.0-python3.12`); a compose file written by the person (PostgreSQL 16, ports on 127.0.0.1 only,
owned resources with their lab identity, a named volume); no privileged container, no Docker socket. Synthetic data:
Spoolman 200 vendors, 5,000 filaments, 100,000 spools (SQL); Prefect 50 flows, 10,000 flow runs, 30,000 task runs,
30,000 logs (through its REST API). A read-only role for Unbidden. No source file of either application is changed.

## Protocol

`bench/ecosystem/app_eval.py --envelope eval`, per application, from the same restored state each time (repository
at the release, data re-seeded, a new `.unbidden`): **B-1** (proactive, no goal), then **A-1** (one general goal,
the same text for both applications: "Readers must see correct and timely data: every number the API reports about
stored records must agree with what is stored, and the main listings must stay fast as the data grows", read-only,
no action), each four cycles; the one declared answer a person gives (adding a package registry Unbidden names, once)
after cycle 2. Mandate: as the regressions (Meta's API only; Spark; experiments allowed; no pull request, merge or
deploy; read-only connections to the database and the API; monthly cap US$2.00 per workspace).

**Limits:** each cycle at most 90 minutes (a cycle past it is recorded as not finished); the `eval` envelope (US$12)
for everything; the project's own checks at the base bounded at one hour. One run per mode and application.

**What each mode allows us to claim.** B: what Unbidden finds and does with no ticket. A: whether it can turn a
general goal into a conclusion with evidence. Neither is a claim about other applications.

## Independent measurement (by the harness's author, after the runs; never by Unbidden)

1. **Reproduction:** the project's own tests, run as its CI runs them, outside Unbidden, at the release.
2. **Every performance claim:** its perf-v3 record read in full; the changed query's plan with and without the
   change on the lab's data (`EXPLAIN ANALYZE`, rolled back); the project's checks with the patch, outside Unbidden.
3. **Every consistency finding:** the reported number and the stored one recomputed directly (API and SQL).
4. **Every abstention:** whether an opportunity existed that Unbidden's checks should have found (foreign keys and
   their indexes, the main listings' timings on the seeded data), so an abstention is labelled as justified or as an
   inability to observe.

Each outcome is classified as one of: **useful improvement verified** (measured by perf-v3 and confirmed by 2),
**absence of opportunity verified** (by 4), **technical block** (said by Unbidden, cause confirmed), **inconclusive**,
or **false promotion** (an L4 or a finding that 2 or 3 does not confirm). The labeller is the person who built the
harness (Claude): a limit, stated.

**Frozen product commit:** 466739e (the evaluation runs from a worktree at it).
