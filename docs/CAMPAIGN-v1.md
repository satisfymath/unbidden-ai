# Campaign to v1.0: robustness and generalization

Written 2026-10-31 from the state after stage 10's frozen evaluation (`docs/bench/stage10-eval/README.md`: three
technical blocks, zero experiments) and its first regressions (`docs/bench/stage10-regression/checks/README.md`: the
three applications' checks reproduced on one commit). This is the one plan to v1.0; `PLAN.md` links here. Its
criteria do not move once results are known: a change is a new decision in `DECISIONS.md`, with its reason and what
it does to earlier claims.

**Vision kept.** Unbidden understands a project, discovers what it needs, acquires the capabilities to act, and acts
within a mandate with evidence. v1.0 is the smallest version of that which holds on applications it has never seen,
with the preparation a person still does declared and counted. It is not a proposal generator, and it does not
promise to run every project.

**Who does what** (every record says which):
- *Claude as developer*: reads failures, changes Unbidden's code with a test that fails before, runs regressions.
  Unbidden is improved by hand from its failures; nothing here is self-improvement of the product.
- *The harness* (`bench/`): clones at a pinned commit, writes a lab compose file, seeds synthetic data, grants a
  read-only role, writes the mandate; records what it did. Human preparation, counted per application.
- *Unbidden*: everything after the mandate: the stack, the image, the CI's plan, the checks, discovery, workloads,
  measurement, verdicts, abstentions, blocks.
- *The independent checker* (the harness's author, after the runs): the project's tests as its CI runs them, every
  L4 re-measured outside Unbidden, every consistency finding recomputed, abstentions checked against the data.

## 1. Scope proposed for v1.0

Python applications and libraries: `pyproject.toml` (uv, Poetry, PDM), `requirements.txt` or `setup.py` at the root
(a uv workspace counts); tests run by GitHub Actions with pytest; for performance work, a FastAPI/Starlette, Django
or Flask server on PostgreSQL that starts with its database only; API documented by OpenAPI, or read without
credentials, or with an API key or password the project's tests use. macOS arm64 native; Linux arm64 and x86-64
only where walked (section 11). Out: other languages' full cycles (Go, Ruby, Rust are in denominators, not
supported), OAuth with external providers, a web UI, new model providers, PR13.

Each variant below is **claimed only after a repository or a controlled fixture exercises it** (section 3's table);
until then it is "not tested", never "supported".

## 2. Capabilities pending, and dependencies

| # | Capability | Depends on | Status 2026-10-31 |
|---|---|---|---|
| C1 | Environment as product input: repository + mandate + credential refs -> copy, stack, plan with provenance, image, checks, coverage and blocks (section 4) | — | `unbidden prepare` (826c8e3): copy, stack with provenance, image, plan, checks, blocks; one path with the daemon and the benchmark. Still the harness's: the lab compose, data, roles |
| C2 | CI plan robustness: conditions, matrices, split suites, make, tox, interpreters, workspaces, test requirements, container runtimes | C1 | eight corrections in stage 10 (`stage10-regression/checks`), each tested; level A run 1 at c840697: 13 of 20 honest (`stage10-campaign/level-a-c840697`), six block classes, four fixed generally at 3a01c91 (sudo edits of the runner, install scripts, compose-started engines and other OS in matrices, tool-only pyproject); **tox not expanded yet** (humanize, click); Django's runner out of scope (healthchecks); run 2 pending |
| C3 | Workloads from checkable resources: benchmark > tests/fixtures/clients > observed requests > documented operations + constrained data > model code last (section 5) | C2 | model-written first; validation strong (D-059), construction weak (mealie, Spoolman) |
| C4 | Measurement and functional equivalence (perf-v4 + content comparison with correspondences; host-load deferral) | — | done: deferral (10c5cc0) with one recorded repeat per commit (9bcfc05, 1a2b969) |
| C5 | Discovery A: non-FK relevant queries; B: N+1 (section 7) | C3 | not started; gated behind C2 and C3 |
| C6 | Consistency semantics: what is compared is declared; bounded SQL reads are partial; bearer and POST reads (section 8) | — | declared comparison before reading (unlike quantities inconclusive), whole SQL reads by key pages (4805759), stored records the whole API read lacks are discrepancies (5097c23), anonymous probe of endpoints declared to need a credential; open: API reads at their bounds (codex-lb's 100,000) |
| C7 | Product closing: install walk, compatibility diagnosis, guided config, evidence report, cancel/recover/clean, demo, integration proposal (section 11) | C1 | stage 9's walk on one platform |

Order: C1/C2 and C6's blocks first (deterministic, no model); C3 before any corpus-wide Level C; C4's deferral
before the next measurements; C5 after C2/C3 hold on the development corpus; C7 in parallel with the frozen runs.

## 3. Corpus

### Development (20, including every repository used so far; never independent evidence again)

| # | Repository | Shape | Variants it exercises (claimed once run) |
|---|---|---|---|
| 1 | full-stack-fastapi-template (fork) | FastAPI + Postgres | uv, src-less package, linear Alembic, in-process tests |
| 2 | mealie | FastAPI + Postgres | Poetry groups, Python 3.14, fixtures re-exported through a package, Alembic, a database matrix (sqlite/postgres) with a Postgres service |
| 3 | Conduit (realworld) | FastAPI + Postgres | async tests, served mode, POST reads |
| 4 | LNbits | FastAPI + Postgres | tests needing network (said), bearer/oauth kinds |
| 5 | Spoolman | FastAPI + Postgres | integration tests directory, Alembic conventions |
| 6 | Prefect | FastAPI + Postgres | matrix x pytest-split, build-written files, pre-commit scopes, 229 opportunities |
| 7 | codex-lb | FastAPI + Postgres | CI `if:` branches, make recipes, bun build in a Python job, merge migrations |
| 8 | Aegra | FastAPI + Postgres (pgvector) | uv workspace with src layouts, `uv python install`, member metadata |
| 9 | rag-api | FastAPI + Postgres (pgvector) | requirements + test_requirements, testcontainers (left out), CI env |
| 10 | healthchecks | Django + Postgres/SQLite | Django test runner (not pytest): *Level A only unless a pytest path exists* |
| 11 | rich | library | property probes (crashes), L4 by FixLab |
| 12 | marshmallow | library | tox envlist, CI parity (the false L4) |
| 13 | pyjwt | library | tox, extras |
| 14 | humanize | library | hatch |
| 15 | starlette | library/framework | scripts/test, async |
| 16 | click | library | tox, pytest plugins |
| 17 | httpx | library | scripts, async |
| 18 | sqlmodel | library | Poetry/uv, SQLModel fixtures |
| 19 | CTFd (v3.8.9) | Flask + Postgres (MySQL/MariaDB/SQLite too) | uv with extras, `make test`, one workflow per database with a service container, flask-restx Swagger, tests that log in |
| 20 | TimeTracker (v5.18.5) | Flask + Postgres | pip `requirements.txt` + `requirements-test.txt`, three manifests at the root, Postgres service container in CI, Redis opt-in |

19 and 20 were chosen by a written rule before any run: the stage 10 rule's search with `topic:flask` (then
`topic:django`, not needed), stars descending, stage 10's eight criteria, the first two that pass; never for a defect
or an easy win. Inspections, in order (metadata unless files are named): 1 30-Days-Of-Python (no license, a course),
2 superset (1395 MB), 3 flask (the framework), 4 dash and 5 peewee (frameworks/libraries), 6 simple-login/app
(config.py, main.yml: sessions in Redis, a Redis service in its CI: criterion 5), **7 CTFd: passes** (pyproject.toml,
Makefile, postgres.yml, config.py: Apache-2.0, uv, `make test` under a Postgres service, cache falls back to the
filesystem without Redis, 122 test files, 44 MB), 8 eve and 11, 16, 27, 29, 40 (NOASSERTION), 9 ProxyPool and 33
(no database), 10, 14, 21, 22, 31 (frameworks), 12, 13, 15, 17, 18, 23, 24, 28, 30, 35, 37, 39 (libraries), 19
sqlite-web (SQLite only), 20 Zappa and 25 (tools/images), 26 openalgo (407 MB), 32 indico (config.py: `REDIS_CACHE_URL`
and `CELERY_BROKER` required: criterion 5), 34 (475 MB), 36 and 38 (courses), 41-45, 48, 50-52, 54, 57, 58, 60, 61,
65, 66, 68, 71, 73, 78 (libraries/tools), 46 FitTrackee (506 MB), 47, 49, 53, 55, 56, 62-64, 67, 72, 74-76, 79, 80
(no database, NOASSERTION, tutorials or frameworks by metadata), 59 (323 MB), 70 Blogin (requirements.txt, compose:
MySQL only, no CI tests), 77 asu (pyproject.toml: no database, Redis), **69 TimeTracker: passes** (config.py, ci.yml,
docker-compose.yml: GPL-3.0, Flask on Postgres, Redis opt-in, `requirements-test.txt`, a Postgres service in CI, 28
MB). The scale benchmark's other pilot/holdout repositories (TypeScript, Go, Ruby, Rust) stay in
their records as denominators of stage 7; they are out of v1.0's scope.

Controlled fixtures (`tests/unit/test_ci_conditions.py`, `test_stack_reach.py`, `test_workload_validation.py`,
`test_equivalence.py`) cover each variant in isolation; the table records which repository exercises it for real.

### Reserved (8, independent evaluation)

Selection rule, fixed now: GitHub's search API, unauthenticated, query
`language:Python stars:>150 pushed:>2026-05-01 archived:false` with `topic:fastapi`, then `topic:django`, then
`topic:flask` (three searches, each sorted by stars descending), candidates examined in that order, stage 10's eight
criteria (`stage10-evaluation.md`) plus: not in the development corpus, not among the 90 candidates stage 10
inspected, not a dependency Unbidden itself uses. Inspection limited to eligibility (metadata, manifests, compose,
settings, workflows, README), recorded per candidate before the next is examined; the first eight that pass form the
set. The list, pinned commits and the checker's oracles (foreign keys, indexes, listing timings on the seeded data)
are kept in `~/unbidden-lab/reserved/` (outside the repository and any workspace Unbidden reads) until the freeze
commit records their hashes. If fewer than eight pass within the three searches' first 300 candidates, the set is
what was found and the shortfall is stated; no criterion is relaxed. No application is replaced after a run.

## 4. Environment preparation as a product capability (C1)

Ordinary input: a repository path or an authorized URL, a mandate, credential references, and only the extra
configuration that is strictly needed. Unbidden, within the mandate: an isolated copy at the commit; the stack
(interpreters, dependencies, commands, services) with provenance (which file said what); a preparation plan;
provisioning where allowed (network to the mandate's registries only); the checks; coverage and blocks recorded.
Provisioning with authorized network and the offline experiment stay separate; a CI step left out says how its
function is met (the image's interpreter for `uv python install`; a note for a JavaScript build). An exit code
without a test report is not checks reproduced. A credential or a permission only a person can give is asked as
such; a technical decision is Unbidden's to make and record.

Per application, measured and reported (section 9): minutes of human preparation; human technical decisions;
auxiliary files a person wrote; corrections to Unbidden needed; time and cost until checks ran. The harness's lab
modules remain human preparation until C1 replaces them, and are counted as such; nothing manual is hidden in them.

## 5. Workloads on checkable resources (C3)

Preference order: an existing benchmark; the project's tests, fixtures, factories and clients; requests and
queries observed (traffic, the sandbox's statement log); documented operations with data generated from the
schema's constraints; new model code last, bounded. The model selects and fills gaps; it does not write the whole
preparation when reusable evidence exists. Before measuring: rows inserted with valid relations; the relevant
operation executed (the engine shows it); a correct, non-empty functional answer where one is due; setup never
inside the timed window; state restored after mutating operations; time and resource limits. Empty tables never
support "no opportunity": *not exercised* is told apart from *no benefit observed*. The generic generator's limits
are recorded; a project's factories or API are tried first. No repository is named in code.

First real targets: codex-lb's regression (its experiment, now measurable), then Mealie with the general mechanism.

## 6. Measurement and equivalence (C4)

Kept: perf-v4 (D-060) with the content comparison of dec7ba2 (no format-based normalization, lists in order, one
correspondence per session for generated ids and times, adversarial controls in the unit tests); A/A, irrelevant
candidate, regression, wrong answer, confirmation in new sessions, the family correction; every verdict states its
scope. To add: host-load deferral (a measurement waits while the 1-minute load exceeds a fixed threshold, up to a
fixed time, then records "deferred, host busy" and the reason; it never stops another workload and never repeats
until a result pleases). Inconclusive attempts stay; the retry policy is written before the run (at most one
repeat per experiment per commit, recorded as such). Promotions judged by an earlier comparator keep their records
with their validity stated (fst: revalidated under dec7ba2; mealie: unconfirmed).

## 7. Discovery (C5), after C2 and C3 hold

A. Relevant queries on non-foreign-key columns: from observed statements, filters and joins, plans, available
frequency and volume; a full scan alone is neither a problem nor a reason for an index. B. N+1: count and repetition
of statements per operation as the number of entities grows; an improvement must be functionally equivalent and
measured. Each family ships with controls where acting is wrong. No other performance category in this version. The
rag-api `custom_id` scan is a human development observation, never attributed to Unbidden nor used as evidence.

## 8. Consistency semantics (C6)

Before two quantities are compared, the plan records entity, population, filters, period or instant, unit,
aggregation, permissions affecting visibility, and the evidence that the API's field and the query's column are the
same thing; otherwise inconclusive (Prefect's states-vs-executions plan is the case). Generally: bearer and the
credential kinds already in scope; SQL reads by batches or adequate aggregations; API pagination and completeness;
documented POST reads; data changing during a read. A 1,000-row limit yields a partial read, never a claim about the
whole; an equal count never shows the records agree. Test cases where totals match but records, filters or relations
differ.

## 9. Staged development campaign and the preparation gate

Levels: **A** preparation and checks (`bench/checks_only.py`, no model); **B** investigation and workload validation
(only after the needed checks reproduce); **C** change and verification (only on a supported opportunity). Every
repository stays in the denominator; per level: success, time, cost, human intervention, failure causes.

**Preparation gate** (goals of readiness, not statistical proof), before the reserved set is opened:
- at least 16 of the 20 development repositories reproduce their required checks autonomously, within the scope;
- no known failure allows a false promotion or an action outside the mandate;
- the evaluator's built-in controls pass (`bench/promotion_cases.py`, 7 of 7, on a quiet host);
- repeatable full cycles on at least three development applications and two problem families;
- every remaining block classified (environment / workload / consistency / credential / out of scope).
If the gate is missed, the general causes are fixed; the corpus is not recomposed.

Status (2026-11-01): level A runs 1-5 (`stage10-campaign/level-a-<sha>/README.md`): honest counts 13, 12, 14, 14,
14 of 20 against the tool's 15, 16, 17, 17, 18 (the tool counts a suite that ran; the README counts the project's
checks reproduced, with every failure explained as the sandbox's and recorded). Fixed generally along the way: sudo
runner edits, install/check/build/report scripts, matrix entries (compose-started engines, other OS), tool-only
pyproject, tox environments, apt packages into the image, benchmark jobs last, `GITHUB_ACTIONS`, failure messages
kept, every declared service container started, service-port expressions, `UV_NO_SYNC`, CI requirement files and
extras for pyproject manifests, host mapping by the variable's engine, `/var/log` writable. Open at run 5: CTFd
(name resolution of its sidecar under pytest), TimeTracker (unstable pytest internal error), healthchecks (Django's
runner: out of scope). Run 6 at 647d714 (`level-a-647d714/README.md`): tool 19, **honest 17 of 20** under the stated
rule (passed, or every failure explained as the sandbox's with its cause recorded: no git, no pager, no network,
today's resolution); 8 pass outright. Criterion 1 of the gate is met under that rule and not under the strict one;
both numbers are reported. Run 7 at 0ea665d (`level-a-0ea665d/README.md`): tool 19, **honest 18 of 20, 10 outright**
(CTFd and Aegra pass once the compose file's application environment stays out of the CI job's tests; the /var/log
cascade explained CTFd's name resolution). Open: TimeTracker (unstable: an xdist worker dies at the sandbox's limits,
no CI baseline of its own), healthchecks (limit).

## 10. Independent evaluation

Frozen before any run, in one commit: product, harness, the eight applications with their commits and data,
model policy (Meta only; Spark; Wonder only in a bounded comparison on an identified reasoning failure, declared),
goals, criteria, budget, repetitions. On all eight: preparation and checks; discovery without hints; investigation
within limits; outcomes told apart (improvement / supported absence / block / inconclusive). No product change during
the runs; later corrections are development. Targets: at least 6 of 8 with their required checks reproduced; at least
one natural improvement on an independent application, verified by the checker; that cycle repeated from a clean
state on the same frozen product; zero false promotions and zero actions outside the mandate observed. A supported
absence is a valid result and does not replace the improvement; zero false in a small sample does not show zero
risk. Seeded cases, if any, are recorded apart from natural findings. If no useful opportunity appears, that is the
report; no project is substituted.

## 11. Product closing (C7), in parallel with the frozen runs

Install and clean walk; compatibility diagnosis (`unbidden doctor` says what is in and out of scope and why);
guided configuration; a readable evidence report; cancel, recover, clean; a reproducible demo; documentation and the
integration proposal (no PR, merge, tag or deploy). Linux arm64 (OrbStack VM, virtualized) and x86-64 (Rosetta,
emulated) walked where available and declared as such; an unwalked platform is not supported.

## 12. Exit criteria for v1.0 (fixed)

1. The preparation gate (section 9) met on the development corpus.
2. The independent evaluation (section 10) met its four targets.
3. Controls 7 of 7 on the frozen product.
4. Walk and demo reproduced on at least macOS arm64; other platforms as walked.
5. The final matrix delivered (promise and tested scope, capabilities, development vs evaluation results, human
   interventions, precision and coverage, cost and latency, failures and limits, candidate commit, integration and
   rollback).
Any unmet criterion keeps "experimental candidate", with the concrete blocks named.

## 13. Budget, time and stop conditions

**Ledger, verified 2026-10-31:** cap US$37.2945 cumulative (never reset; the dashboard's credits authorize nothing
beyond it); spent US$26.0846; available US$11.2099: `s10-dev` 4.91 of 13.00, `s10-eval` 2.50 of 3.50, `s10-close`
3.80 of 3.80. Meta API only: Spark by default; Wonder only in a bounded comparison on an identified reasoning
failure; no local fallback (denied in every mandate).

**Estimated cost from the records** (list price x reported tokens):
- Level A on 20 repositories: US$0 (no model).
- Levels B/C on the ~10 database applications: US$0.3-1.2 per application per mode from stage 10's runs (codex-lb
  0.56, Aegra 0.36, rag-api 0.06, Spoolman 0.36, Conduit 0.52, Prefect 0.2-0.25/hour up to 1.1); with workload
  retries: **US$6-8**.
- Reserved evaluation, 8 applications, B-1 and A-1, plus one repeat of the improvement cycle: **US$4-6**.
- Closing (demo, walks make few calls): **US$1-1.5**.
- Total **US$11-15.5**, contingency 25%: **US$14-19.5** against US$11.21 available.

**Allocation now** (no cap change): `s10-dev` keeps 4.91 for Levels B/C; `s10-eval` 2.50 and `s10-close` 3.80 stay
reserved. Levels A, the code, the tests, the independent reproductions and the documentation need no model and
proceed regardless.

**Incremental budget request, prepared** (for David; nothing is spent against it until authorized): pending work =
Levels B/C on 10 development applications (about 20 runs), the reserved evaluation (16 runs + 1 repeat), closing;
estimate US$14-19.5; shortfall at the upper bound **US$8.30**; proposed new cumulative cap **US$45.60** (= 37.2945 +
8.30), the ledger continuing to count from the same verification. Envelopes after approval, counted from stage 10's
split as now: `s10-dev` 17.50, `s10-eval` 6.50, `s10-close` 4.60 (total 28.60 = 20.30 + 8.30), or the split David
prefers; recorded with `unbidden spend --amend-cap --envelopes` before any call against it.

**Time:** Level A, 1-2 days of compute; Levels B/C with corrections, 3-5 days; the gate; the reserved selection (one
day, inspections recorded); the frozen runs, 1-2 days; closing in parallel.

**Stop conditions:** the cap reached (no call is made past it; enforced before each call); the gate missed after
two rounds of general corrections on the same cause (report, do not recompose); an unauthorized action or a false
promotion observed (stop, record, fix as a decision before anything else); the reserved set exhausted without an
improvement (report the limitation; v1.0 not declared).
