# Stage 8: an independent application (chosen and frozen before running)

Registered before Unbidden has seen it. Conduit is development and regression for this stage; this run is the
out-of-sample check, run once at the frozen product commit named at the end, after the Conduit regression.

## Choice

Rule, written before looking at any candidate's code: a public repository under an OSI license; maintained (not
archived, a release in 2026); never used in an earlier stage and not built from the RealWorld/Conduit specification;
Python, with a relational database and an HTTP API described by OpenAPI (the scope Unbidden claims, `RELEASE.md`);
its own test suite run by its CI; runnable locally with synthetic data and no external service. Among candidates
that pass, the first in the list below; candidates were listed from general knowledge of public Python web
applications, metadata read from GitHub's public API only.

| Candidate | Passes? | Why not / why |
|---|---|---|
| lnbits/lnbits | yes | MIT; FastAPI, OpenAPI 3.1 (151 paths); PostgreSQL or SQLite; pytest suites in CI against PostgreSQL; FakeWallet funding source works offline |
| Netflix/dispatch | no | archived |
| inventree/InvenTree | not reached | (Django REST, very large) |
| healthchecks/healthchecks | not reached | (Django; API not described by OpenAPI) |
| wger-project/wger | not reached | |
| sissbruecker/linkding | not reached | |

**Chosen: LNbits v1.6.2**, commit `9349da153c223b008f7d80453b53a54e09c8ed3d` (latest release, 2026-09-18). Its
domain (Lightning wallets and payments) is unrelated to anything Unbidden was developed on. What is known in advance
of how it differs from the development projects, and not changed for it: its SQL is written by hand through its own
database layer (no ORM models), its schema is created by its own migration code (not Alembic), and its CI runs
tests through reusable workflows and a composite action.

## Lab (human preparation, counted)

`bench/ecosystem/lnbits_lab.py`: a clone of the release in `~/unbidden-lab/lnbits`; the project's own Dockerfile,
built unchanged (the build itself downloads uv and Debian/PostgreSQL packages; that is the person's preparation,
not Unbidden's sandbox); a compose file written by the person (the repository has none) with PostgreSQL 16, ports on
127.0.0.1 only (app 18120, database 55450), the lab's label, a named volume; `.env` with the database URL, the
FakeWallet funding source, the admin UI off, new accounts allowed. Synthetic data through SQL: 2,000 accounts,
4,000 wallets, 400,000 settled payments (placeholders for hashes and invoices; no real person or payment); a
read-only role `lnbits_reader`; a wallet created through the app's own API, given 5,000 synthetic payments, whose
invoice (read) key is the API credential, as a person would hand over a wallet's read key. No source file of the
application is changed. Startup needed no fix.

## Protocol

`bench/ecosystem/lnbits_eval.py`, run `I-1`, proactive (no goal), from clean state: the repository at the release,
data re-seeded, a fresh read key, a new `.unbidden`. Mandate as Conduit's proactive runs (priorities: correctness,
performance of reads as data grows; PyPI as the only registries; read-only connections to the database and the API;
experiments allowed; no pull request, merge or deploy; monthly cap US$1.50). Two cycles; then the one declared answer
a person gives, if asked (adding a package registry Unbidden names, once), and two more cycles. Nothing else is
granted or told. The product and harness run from one worktree at the frozen commit; nothing is changed during the
run.

## Independent measurement (done by the harness's author after the run, never by Unbidden)

1. **Reproduction.** The project's own unit tests (`tests/unit`, the CI's `test-unit` job) run at the release in a
   plain `python:3.12` container with `uv sync` from its lock, against the lab's PostgreSQL in a separate database;
   pass/fail counts recorded. This says whether Unbidden's reproduction (or its failure) matches what the project's
   checks do outside Unbidden.
2. **Findings.** Every opportunity Unbidden records is checked against the application: the code path it names is
   read, and for a database claim the query is run with `EXPLAIN (ANALYZE, BUFFERS)` through the read-only role on
   the seeded data, twenty times, median reported. Each is labelled *confirmed*, *refuted* or *undetermined*, with the
   evidence. The labeller is the same person who built the harness (Claude): that is a limit, stated.
3. **Claims of improvement.** If Unbidden reports a measured improvement, its patch is applied in a separate clone,
   the project's checks are run on both sides, and the measurement is repeated outside Unbidden's lab.
4. **What it asked of a person, and the cost:** the requests (pertinent to a block or not), interventions, model
   calls and spend from the ledger.

What counts as success is not one number: the record says, per capability, what happened (reproduced or the cause;
read with deviations or blocked; findings and their labels; experiments and their outcome; requests; cost). A run
with no improvement is a valid result and is reported as such.

**Budget:** the independent test's share, US$1.80; the workspace's cap is US$1.50.

**Frozen product commit:** 6bbf3a1 (product, harness and this protocol; the run uses a worktree at it).

## Result of I-1 (the evaluation, as run)

Run once on 2026-10-29 at 6bbf3a1 with LNbits at 9349da1; record in `stage8-independent/I-1/`. 104 s for four
cycles, US$0.00 of model spend: one model call, the probe's property tests written by the local model (Glimmer;
the code is labelled private, so it leaves only renamed and the route kept it local); ledger 6.2648 before and after.

| Capability | What happened | Independent measurement |
|---|---|---|
| Interpreter | Python 3.12, by the written rule: the CI's matrix (3.10, 3.12) and the project's Dockerfile (3.12) agree; pyproject and poetry.lock admit >=3.10,<3.13; the disagreement of the two concrete sources recorded | uv, in a plain container running the CI's command, picked 3.12 too |
| Reproduction | Dependencies installed from `uv.lock`; ruff and pyright ran (2 reports, 0 new opportunities). The project's own tests never ran: the probe's run failed at import, `PackageNotFoundError: lnbits` (the image installed the dependencies, not the project, which reads its own version at import) | The CI's `test-unit` job at the release, outside Unbidden: **646 passed** in 34 s. The project is reproducible as declared; the failure is Unbidden's |
| Requests to a person | One: `registry.npmjs.org`, answered once (counted). It named the block it came from, but the work blocked (a probe of Python code) did not need Node: one language's provisioning blocked the other's | — |
| Reads | The database connection read the catalog (14 tables, read-only role). The API stayed `needs_capability`: a proactive run builds no API integration (by design: integrations are built when a goal needs one) | — |
| Map and findings | 219 resources (208 endpoints from the live OpenAPI and code), **no table**: the running PostgreSQL was recognized from its image, but tables are read only for a service declared in a compose file the map reads, and the lab's compose file (`docker-compose.lab.yml`, written by the person; the repository has none) was not one of the names it reads. No check had data to look at; **0 opportunities** | Both foreign keys (`balance_check.wallet`, `balance_notify.wallet`) lead a unique index; `apipayments` has 15 indexes; the main read (a wallet's payments, newest first, 20 per page) takes **1.36 ms** median of 20 for a wallet of 5,000 payments and 0.14 ms for one of 100. Nothing to fix was found at this volume |
| Experiments | None (nothing to experiment on) | — |

**Reading.** No improvement, and it is not a justified abstention: Unbidden did not observe the database it was
connected to through its map, and could not run the project's tests. The independent measurement found nothing worth
changing either, so the silence happens to be right, for the wrong reason. The cycle was not completed on this
project.

**Fixed after the evaluation** (da7a595, labelled post-evaluation, general): the project's own package registered
in the environment as `uv sync` does; languages provisioned apart; a PostgreSQL started from an unread compose file
is read through its container's user and database. Any repeat on LNbits is reported apart as post-evaluation.

## I-2: a repeat after the evaluation (not evaluation evidence)

The same protocol and preparation, run `I-2` (`lnbits_eval.py --run I-2`), from a worktree at the commit named
below, after the Conduit regression's fourth version. It shows whether the fixes made from I-1 work; it was tuned on
I-1, so it is not out-of-sample evidence.
