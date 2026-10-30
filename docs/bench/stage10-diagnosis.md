# Stage 10: why Spoolman's workloads and Prefect's runs failed, reconstructed from their records

Sources (all kept): the archived workspaces `~/unbidden-lab/spoolman-runs/{eval9-*,post9-*,post9b-*}` and
`~/unbidden-lab/prefect-runs/{eval9-*,post9-prefect-B-post1-interrupted}` (each `state.db` with its events, jobs and
model runs, and `artifacts/` with every workload attempt and its output), the records in `docs/bench/stage9-evaluation`
and `docs/bench/stage9-post-evaluation`, and the two applications' repositories at their pinned releases. Each cause is
put in one class: **environment not prepared**, **missing fixture**, **missing dependency or service**, **test data
blocked by Guardian**, **wrong checks command**, **invalid workload**, **unsupported operation**, **a defect of the
candidate (Unbidden)**.

## Spoolman: sixteen workload attempts in four runs, none ran at the base

| Run (product) | Attempt | What its output says | Class |
|---|---|---|---|
| B-post1 (c5ea5ee) | 1 | `sqlite3.OperationalError: unable to open database file`: the application opened its default SQLite path; its database settings (`SPOOLMAN_DB_*`) were not set | missing dependency or service |
| B-post1 | 2, 4 | `fixture 'random_filament' not found` | missing fixture |
| B-post1 | 5 | `warm-up returned HTTP 404`: `/spool` called at the root; the API is under `/api/v1` (the map knew only the root's document) | invalid workload (fed a wrong path: a candidate defect, fixed in 977835c) |
| A-post1 (c5ea5ee) | 1, 3 | `fixture 'random_filament' not found` | missing fixture |
| A-post1 | 2 | `Could not find FastAPI app ... The web client has not been built: 'client_v2/build' does not exist` | environment not prepared |
| A-post1 | 4 | `module 'unbidden_workload' has no attribute 'build'` | invalid workload |
| A-post1 | 5 | `'NoneType' object has no attribute 'execute'` (its own engine search found nothing) | invalid workload |
| B-post2 (977835c) | 1 | `fixture 'random_filament' not found` | missing fixture |
| B-post2 | 2, 4 | `could not locate FastAPI app` / `cannot find FastAPI app` (the import fails on the unbuilt client) | environment not prepared |
| B-post2 | 3 | `fixture 'api_client' not found` | missing fixture |
| B-post2 | 5 | `fixture 'a' not found`: `def build(*a, **k)`, whose parameters pytest takes for fixtures | invalid workload |
| A-post2 (977835c) | 1 | `fixture 'random_filament' not found` | missing fixture |
| A-post2 | 2 | `The web client has not been built` | environment not prepared |
| A-post2 | 3 | `fixture 'kwargs' not found` | invalid workload |
| A-post2 | 4, 5 | no workload file: one request was refused by Guardian (`url_credentials`, one `egress.blocked` event), and the run's last note is that refusal | test data blocked by Guardian |

**The common cause, read from the repository.** Spoolman tests its API only over HTTP: `tests_integration/` runs the
project's own image with `SPOOLMAN_DB_TYPE=postgres` and a PostgreSQL service (`docker-compose-postgres.yml`), and its
fixtures (`random_filament`, `random_vendor`) live in `tests_integration/tests/conftest.py` and call the server by URL.
`tests/` (the 278 tests the base checks ran) are unit tests that never import the application. The lab's only way to
measure was to run the workload as one more test of `tests/`, inside the application's process: there the
integration fixtures do not exist, the application cannot be imported until its web client is built (the Dockerfile
builds it), and the database is SQLite unless the integration environment's variables are set. The model was asked to
write a test the project itself never writes, and every repair could only trade one of these failures for another.

**The Guardian refusal** (A-post2, attempts 4-5). The prompt held a URL with credentials from the project's test
configuration (`postgresql://...:abc@db`). It was masked before sending, but the mask of a URL password, `***`, is
itself three characters, which the URL pattern matches again: masking was not idempotent for URLs, and the scan of the
masked prompt refused the whole request. `${VAR}` in a URL (`mysql://root:${PASSWORD}@db`) was also taken for a secret.
A defect of the candidate, not of the data.

## Prefect

| Run (product) | What the records show | Class |
|---|---|---|
| B-1 (466739e) | the dependency image did not build: `--all-groups` included `cli-bench`, a package from GitHub | environment not prepared (fixed in c5ea5ee) |
| A-1 (466739e) | goal blocked: Prefect reads with `POST .../filter`, every POST taken as a write | unsupported operation |
| B-1, A-1, B-post1 | the same `world.endpoint_tables` request refused by Guardian (`credential_assignment`, one hit): the handler code sent was not masked, and the scan took code for a secret: `reservation_token=reservation.reservation_token` (a dotted attribute) or `ORMCsrfToken = CsrfToken` (an alias); 15 such lines in `src/prefect/server` | test data blocked by Guardian (a scanner false positive, and an unmasked path) |
| B-post1 (c5ea5ee) | base checks `infra_failed`: the command came from `run-canonical-tests`, a job split into 18 groups by pytest-split, read with its matrix expressions empty (`--group ""`, a PostgreSQL image of `${{ ... }}`), its duration file a downloaded artifact (`test-durations.json`, not in the repository), `jq` and `$GITHUB_OUTPUT` assumed, a bookkeeping step (`jq -e` on durations) taken as a test step, and `$GITHUB_ENV` (the database URL) ignored | wrong checks command |
| B-post1 | 511 opportunities from mypy and ruff (230 open); the Director ran FixLab on 229 of them, each about 35 s, no model call, each ending without a verdict (the exact note is not in the records: the harness died before writing the cycle's output) | a defect of the candidate: a commit whose base checks did not run let experiments start, and each experiment re-ran the same linters at the same commit |
| B-post1 | every finished experiment queued a Director sweep (`after:<job>`); each sweep decided 511 opportunities (787 decisions recorded, about 50 s each); the queue never emptied and the cycle passed its 90-minute bound, then the harness died on the timeout | a defect of the candidate (and of the harness, fixed in 977835c) |

## What is fixed in stage 10, generally (no branch on an application's name)

1. **Measurement from the project's own evidence** (the main cause above): an inventory of what the project uses to
   test and run itself (CI jobs and their environment, compose services and their variables, Dockerfile, conftest
   fixtures and where they are visible, migrations, benchmarks, the endpoints' real queries), each with its source;
   a second way to measure, **served**: the application started as the project starts it, with its database as a
   service, the data seeded by a fixed seeder from the engine's catalog after the project's own migrations, and the
   request a fixed driver sends; the model only chooses among these, and its choice is checked by running it.
2. **Readiness states** (environment ready, checks reproduced, workload valid, experiment executed, result
   evaluable), so a preparation that fails is never read as an absent opportunity or a negative result.
3. **Guardian:** masking idempotent for every pattern; `${VAR}` references are placeholders; dotted attribute paths
   and aliases are code; every repository text sent is masked first. Real secrets stay refused (tests).
4. **CI reading:** matrix expansion; `$GITHUB_ENV` and `$GITHUB_OUTPUT`; steps that need an artifact from another
   job, and bookkeeping steps, recognised; split suites as groups, the required set chosen before the experiment and
   its coverage recorded.
5. **The Director:** one pending sweep at a time; no experiment while the commit's base checks are not reproduced;
   one linter run per tool and commit, reused.
6. **Reads by POST**, when the document and an observation support it.
