# Unbidden: release candidate (stage 9): an experimental candidate, not 1.0

**Status: experimental candidate.** Not 1.0: the exit criteria and their evidence are in `docs/PLAN.md` (stage 9,
"Exit criteria"). The one that blocks 1.0: no useful cycle has been shown on an application not used in development
(the frozen evaluation, `docs/bench/stage9-evaluation.md`, ended in four technical blocks). Nothing is published,
tagged, released, merged or deployed.

## The exact point

- Code: commit **CANDIDATE** on branch `feat/59-v1`. `uv.lock` pins every Python dependency (Python 3.12). This file
  is updated after the commit it names: read it from the branch head.
- Verified platform (and only this one): macOS 27.0.1 on Apple Silicon (arm64); OrbStack with Docker Engine 29.8.2
  (linux/arm64 containers) and its compose plugin; uv 0.13.1; git 2.56. Linux and x86-64 hosts were not tested.
- Models: Meta's API (`muse-spark-1.3` on the `code` route); stage 9's runs used no local model. The local route
  (Ollama, `muse-glimmer:30b-mxfp8-dflash`) is supported and was exercised in earlier stages.

## What it supports (v1.0 scope), and what it does not

| Area | Supported (exercised) | Not supported, or not exercised |
|---|---|---|
| Projects | a git repository whose Python project is at the root: `pyproject.toml` (uv or Poetry locks), `requirements.txt` or `setup.py`; the interpreter chosen from the project's own declarations (CI matrix, Dockerfile, `.python-version`, `requires-python`, locks), the rule recorded | a Python project in a subdirectory (no per-subproject environment); interpreters outside 3.8-3.13 |
| Checks | the project's tests (pytest) from its GitHub Actions test job: local reusable workflows and composite actions followed, an action's test-command input read as the command, the job's service containers as sidecars, the job's `uv sync` groups; without such a job, pytest over the repository. Run once at the base of every commit (`observe.checks`) and three rounds on each side of every experiment | CI suites sharded by matrix into groups (not one command); jobs that need network, privileges or the repository's secrets while they run; other CI systems |
| Running system | Docker Compose projects on this machine: containers, published ports, the live OpenAPI, PostgreSQL catalogs read inside their containers (also when started from a compose file Unbidden does not read) | Kubernetes, remote hosts, cloud accounts |
| Databases | PostgreSQL over the network, a read-only role, bounded reads | MySQL, SQLite connections, IAM auth |
| HTTP APIs | OpenAPI 3.0 and 3.1 (recursive schemas included), served under the document's `servers` path; an API key in a header, or no credential; only the operations the document says that credential can call; page, offset/limit and cursor pagination, completeness judged by how counts behave; documented-vs-observed deviations recorded per operation and field; rate limits waited out on reads; writes with an `Idempotency-Key`, undone by a DELETE, each authorized just before it is sent | OAuth, bearer tokens, keys in a query string; APIs that read through `POST` (every POST is treated as a write); SOAP, GraphQL; writes without an observable undo |
| Findings | unindexed foreign keys (traced to the endpoints and SQL or ORM code that use them), whole-table scans, API-reported numbers against stored data, crashes found by property tests, the project's own linters and type checkers | other kinds of defect |

## What it may do, and when a result is accepted

The mandate (`.unbidden/mandate.yaml`) decides what runs on its own: `observe`, `run_experiments`,
`provision_dependencies`, `use_new_capabilities`, `delegate_synthetic`, `open_pull_requests`, `merge_pull_requests`,
`deploy`, `rollback`, `act_on_connections` (each `allow`, `require_approval` or `deny`); the registries builds may
reach (`egress.package_registries`); where model calls may go (`models.profile`, `local_fallback`,
`local_inference`); a monthly spend cap; the connections and their permissions.

**Credentials** are never in the repository or the mandate: they live in `.unbidden/.env` (mode 600) and
`~/.unbidden/.env`, referenced by name (`credential_ref`); a broker hands them to the one call that needs them;
prompts, logs and stored records are scanned and masked (credential-looking values, personal data); a credential a
service refuses is reported as an access problem for a person, but a read it simply does not reach is left out.

**Evidence levels** (each claim's confidence is capped by its level):

| Level | Meaning, precisely |
|---|---|
| L1 | Reasonable suspicion: a check or a model points at something; nothing reproduced |
| L2 | Reproduced: the finding is observed (a scan, a query plan, a discrepancy between an API and its data) |
| L3 | Improved in the lab: a change measured better in the sandbox, but the project's checks did not validate it on both sides |
| L4 | Functionally validated: the project's own checks pass on both sides (three rounds each), and the measurement passes criteria **perf-v3**: four alternating sessions per side on fresh databases, an exact permutation test on session medians (alpha 0.05), at least 20% faster, and for an index, the index seen in use on every measured call. Verdicts under older criteria are listed as pending revalidation |
| L5 | Operational result: measured on the running system after deploy, its confounders listed |
| L6 | Persisted: L5 held over the mandate's period |

A goal's result is an acceptance with sealed conditions (`applied`, `accepted`, `rejected`, `inconclusive`,
`stale`), the model's own claim recorded apart. A conclusion that needs a whole set is withheld when a read is
partial (unknown completeness, or a query that reached its limit): a discrepancy found stands; "none" does not.

## Models and budget

Every remote call reserves its worst cost in `~/.unbidden/spend.db` before it is sent and settles to the reported
cost after; calls past the cap a person entered are refused. An authorization can be split into envelopes, each
enforced the same way (`unbidden spend --envelopes dev=12,eval=12,demo=6 --envelopes-total 30 --source ...`; every
call then names one with `UNBIDDEN_ENVELOPE`); a cap is raised without resetting what was spent
(`--amend-cap`). The ledger is an estimate (list price x tokens), not a bill.

## Known limitations (each seen in a run)

- **No useful cycle on an independent application yet.** On Conduit (development) the full cycle runs: reproduce,
  find, measure under perf-v3, propose, decline what does not hold. On the evaluation's applications it did not.
- Performance workloads are written by a model, and the verdict depends on the data they seed: the same index on
  Conduit measured 18% with one workload and 25% with another.
- The world checks find unindexed foreign keys and table scans; the value of an index on a table that is empty in the
  lab cannot be measured there.
- Masking credential-looking or personal values in prompts hides them from the model too.
- A few real projects, run a few times each: no claim about rates.

## Install and check

```sh
git clone https://github.com/satisfymath/unbidden-ai.git && cd unbidden-ai
git checkout CANDIDATE        # the candidate named above
uv sync                       # dependencies from uv.lock (pyright brings its own Node)
make check                    # ruff, pyright, about 690 tests (the Docker ones skip without a daemon)
uv run unbidden doctor        # Docker, models, Meta key, GitHub, mandate: what works and what does not
uv run unbidden spend         # the machine-wide spend ledger, its cap and envelopes
```

Prerequisites a person provides: Docker with its compose plugin (`docker compose version` must answer; Docker Desktop
and OrbStack install it for the user); for remote models, a Meta key in `~/.unbidden/.env` as `MODEL_API_KEY=<key>`
(mode 600; add it once by editing the file) and a spend cap entered by a person; for local models, Ollama with a model
(`unbidden doctor --fix` picks one that fits the machine). Without the key, everything local works and `doctor` says
the remote route is off.

## A first run on a project

```sh
cd your-repository
uv run --project /path/to/unbidden-ai unbidden init           # .unbidden/ with a supervised mandate
$EDITOR .unbidden/mandate.yaml                                # autonomy, registries, connections, models
uv run --project /path/to/unbidden-ai unbidden watch --once   # one cycle: map, checks, decisions, experiments
uv run --project /path/to/unbidden-ai unbidden activity       # found, decided, checked, asked, proven, spent
```

A mandate, without secrets (secrets go in `.unbidden/.env`, mode 600, referenced by name):

```yaml
mandate:
  workspace: shop
  priorities: [correctness, performance of reads as data grows]
  business_constraints: {maximum_monthly_spend_usd: 2.0}
  autonomy: {observe: allow, run_experiments: allow, provision_dependencies: allow, delegate_synthetic: allow,
             use_new_capabilities: allow, open_pull_requests: deny, merge_pull_requests: deny, deploy: deny,
             rollback: deny, act_on_connections: deny}
  egress: {package_registries: [pypi.org, files.pythonhosted.org],
           remote_models: {destinations: [api.meta.ai], max_payload_bytes: 60000}}
  models: {profile: frontier, local_fallback: deny, local_inference: deny}
  connections:
    - {id: shop-db, kind: postgres, location: 127.0.0.1:5432/shop, environment: staging, username: shop_reader,
       credential_ref: SHOP_READER_PW, permissions: [read]}
    - {id: shop-api, kind: http_api, location: http://127.0.0.1:8000, docs: http://127.0.0.1:8000/openapi.json,
       environment: staging, credential_ref: SHOP_API_KEY, permissions: [read]}
```

`content_may_leave: true` on a connection and `private_code_to_frontier: allow` are a person's statement that the
data and code may leave (synthetic data, public code); on real projects leave them out.

## Evidence: where it is, how to keep and review it

- `unbidden activity` (found, decided and why, the project's checks at the base, blocks and requests, proofs and
  revocations, spend), `unbidden why <opportunity>`, `unbidden connections`, `unbidden egress`, `unbidden spend`.
- `.unbidden/state.db`: opportunities with their history, experiments with every measured session raw, verdicts
  and revocations, goal runs, acceptances, model runs, egress attempts; `.unbidden/artifacts/`: patches, workloads,
  probe files, logs.
- To keep a run's evidence, move the whole `.unbidden/` out of the repository after it (the harnesses do); the
  spend ledger is per machine and is never reset.

## Stop, clean up, recover, roll back

- `unbidden kill` stops everything now (no new job or model call; running sandbox containers killed; pushes, pull
  requests, merges, deploys and rollbacks check it immediately before acting); `unbidden resume` lifts it.
- Experiments work on snapshots, never on the repository; a proposal is a local branch (or a pull request where the
  mandate allows), reverted like any commit. A deploy is rolled back with the mandate's own steps; a failed one leaves
  a hold only a person releases (`unbidden hold`).
- A lab verdict that does not hold is revoked, not erased (`unbidden.lab.revoke`): kept with its reason.
- Clean up: sandbox containers carry `unbidden.sandbox` (`docker ps -a --filter label=unbidden.sandbox`); dependency
  images are `unbidden-deps-*`; the workspace is `.unbidden/`. The benchmark labs own their resources by identity
  (`unbidden.lab.id=<lab>`): `... down` removes only that lab's containers and networks and keeps its data; `--volumes`
  removes the data too.

## The walk (clean checkout, empty HOME)

WALK

## The demo

DEMO

## Integration proposal (from the git graph; no PR, merge or tag in this stage)

INTEGRATION
