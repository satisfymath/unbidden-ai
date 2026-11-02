# Unbidden 0.9.0, experimental candidate: the product branch, not 1.0

**Status: 0.9.0, experimental candidate.** Not 1.0: the criteria of v1.0 are in `docs/CAMPAIGN-v1.md` and were not
met when the campaign paused at its gate (D-063); they are not changed here. The one that blocks 1.0: no useful cycle
has been shown on an application not used in development. This candidate adds the product around the same engine:
an installable wheel, a guided setup, one executor per workspace with a background agent, and the dashboard and chat
on the engine's own records (D-064). Nothing is published, tagged, released, merged or deployed.

## The exact point

- Code: product branch `feat/63-product-onboarding` (code at `2d72ce4`, the commit CI validated; the head adds documentation only), cut from `main` at `d560b6f` (the merge of
  PR #2: 0.9.0 and the web workspace). `pyproject.toml` says `0.9.0`; `unbidden --version` prints `unbidden 0.9.0`.
  `uv.lock` pins every Python dependency (Python 3.12). This file is updated after the commit it names: read it from
  the branch head.
- Verified platform (and only this one, by hand): macOS on Apple Silicon (arm64), 2026-11-01; Docker with its buildx
  and compose plugins. Linux x86-64 runs in GitHub Actions only (below). Linux by hand, Intel macOS and Windows were
  not tested.
- Models: Meta's API (`muse-spark-1.3` on the `code` route) in the validation (option `api`). The local route
  (Ollama, `muse-glimmer:30b-mxfp8-dflash`) is supported and was exercised in earlier stages; options `local` and
  `mixed` were configured by tests, not walked with a model.

## What it supports (v1.0 scope), and what it does not

| Area | Supported (exercised) | Not supported, or not exercised |
|---|---|---|
| Install | one wheel with the web workspace inside, installed by `install.sh` as a uv tool with its own Python 3.12, sha256 verified; from the GitHub release through `curl -fsSL https://unbidden.cl/install.sh \| sh`, or from local artifacts; `update`, `uninstall` keeping data | PyPI |
| Projects | a git repository whose Python project is at the root: `pyproject.toml` (uv or Poetry locks), `requirements.txt` or `setup.py`; the interpreter chosen from the project's own declarations (CI matrix, Dockerfile, `.python-version`, `requires-python`, locks), the rule recorded | a Python project in a subdirectory (no per-subproject environment); interpreters outside 3.8-3.13 |
| Checks | the project's tests (pytest) from its GitHub Actions test job: local reusable workflows and composite actions followed, an action's test-command input read as the command, the job's service containers as sidecars, the job's `uv sync` groups; without such a job, pytest over the repository. Run once at the base of every commit (`observe.checks`) and three rounds on each side of every experiment | CI suites sharded by matrix into groups (not one command); jobs that need network, privileges or the repository's secrets while they run; other CI systems |
| Running system | Docker Compose projects on this machine: containers, published ports, the live OpenAPI, PostgreSQL catalogs read inside their containers (also when started from a compose file Unbidden does not read) | Kubernetes, remote hosts, cloud accounts |
| Databases | PostgreSQL over the network, a read-only role, bounded reads | MySQL, SQLite connections, IAM auth |
| HTTP APIs | OpenAPI 3.0 and 3.1 (recursive schemas included), served under the document's `servers` path; an API key in a header, or no credential; only the operations the document says that credential can call; page, offset/limit and cursor pagination, completeness judged by how counts behave; documented-vs-observed deviations recorded per operation and field; rate limits waited out on reads; writes with an `Idempotency-Key`, undone by a DELETE, each authorized just before it is sent | OAuth, bearer tokens, keys in a query string; APIs that read through `POST` (every POST is treated as a write); SOAP, GraphQL; writes without an observable undo |
| Findings | unindexed foreign keys (traced to the endpoints and SQL or ORM code that use them), whole-table scans, API-reported numbers against stored data, crashes found by property tests, the project's own linters and type checkers | other kinds of defect |
| Operation | one executor per workspace (a kernel lock on `.unbidden/engine.lock`); `start`/`stop`/`status` of a background agent; stale locks recovered and interrupted jobs resumed; the kill switch untouched by `stop` | starting at boot (nothing is installed as a service); two agents on one workspace; NFS workspaces |
| Dashboard and chat | `unbidden ui` and `start --ui` over the repository's own state, read-only; demo and historical sources; actions (approve, reject, approve writes, kill, resume) on live sources; chat that informs by rules and analyzes with one routed call | deploy and rollback from the dashboard (they name the CLI command); the chat acting on anything |

## What it may do, and when a result is accepted

The mandate (`.unbidden/mandate.yaml`, written by `unbidden setup` or by hand) decides what runs on its own:
`observe`, `run_experiments`, `provision_dependencies`, `use_new_capabilities`, `delegate_synthetic`,
`open_pull_requests`, `merge_pull_requests`, `deploy`, `rollback`, `act_on_connections` (each `allow`,
`require_approval` or `deny`); the registries builds may reach (`egress.package_registries`); where model calls may
go (`models.profile`, `local_fallback`, `local_inference`: the three options `local`, `mixed`, `api` are fixed
combinations of these); a monthly spend cap; the connections and their permissions. The setup assistant shows the
effective permissions computed by the `PolicyEngine` before writing.

**Autonomy modes** (unchanged): `supervised` asks before a pull request and never merges or deploys; `autopilot`
opens pull requests for proven work and people merge; `autonomous` also merges L4 work, deploys with the team's steps
and rolls back, and cannot be switched on without `operations.deploy_steps` and a passed `unbidden drill`.

**Credentials** are never in the repository or the mandate: they live in `~/.unbidden/.env` (written by setup, mode
600) and `.unbidden/.env`, referenced by name (`credential_ref`); a broker hands them to the one call that needs them;
prompts, logs and stored records are scanned and masked (credential-looking values, personal data); a credential a
service refuses is reported as an access problem for a person, but a read it simply does not reach is left out.

**Evidence levels** (each claim's confidence is capped by its level):

| Level | Meaning, precisely |
|---|---|
| L1 | Reasonable suspicion: a check or a model points at something; nothing reproduced |
| L2 | Reproduced: the finding is observed (a scan, a query plan, a discrepancy between an API and its data) |
| L3 | Improved in the lab: a change measured better in the sandbox, but the project's checks did not validate it on both sides |
| L4 | Functionally validated: the project's own checks pass on both sides (three rounds each), and the measurement passes criteria **perf-v4** (D-060): perf-v3's sessions (four alternating sessions per side on fresh databases, an exact permutation test on session medians at alpha 0.05, at least 20% faster, and for an index, the index seen in use on every measured call), plus the same responses on both sides, an A/A control of base sessions and a confirmation in new sessions in a new order. Verdicts under older criteria are listed as pending revalidation |
| L5 | Operational result: measured on the running system after deploy, its confounders listed |
| L6 | Persisted: L5 held over the mandate's period |

A goal's result is an acceptance with sealed conditions (`applied`, `accepted`, `rejected`, `inconclusive`,
`stale`), the model's own claim recorded apart. A conclusion that needs a whole set is withheld when a read is
partial (unknown completeness, or a query that reached its limit): a discrepancy found stands; "none" does not.

## Models and budget

Every remote call reserves its worst cost in `~/.unbidden/spend.db` before it is sent and settles to the reported
cost after; calls past the cap a person entered are refused. The mandate's monthly cap is checked in that one ledger
for every process of a workspace, so the dashboard's chat and the engine count against the same cap. An
authorization can be split into envelopes, each enforced the same way (`unbidden spend --envelopes dev=12,eval=12,demo=6
--envelopes-total 30 --source ...`; every call then names one with `UNBIDDEN_ENVELOPE`); a cap is raised without
resetting what was spent (`--amend-cap`). The ledger is an estimate (list price x tokens), not a bill. Setup calls no
model; its optional paid probe asks first and shows the worst cost. What costs tokens and what does not, command by
command: `docs/INSTALL.md`.

## Known limitations (each seen in a run)

- **No useful cycle on an independent application yet.** On Conduit (development) the full cycle runs: reproduce,
  find, measure, propose, decline what does not hold. On the evaluation's applications it did not.
- **No public release.** Install from local artifacts; `unbidden update` without `--version` finds nothing.
- **Linux not verified by hand**: GitHub Actions is the only Linux evidence (below).
- An empty HOME has no Docker CLI plugins: without buildx the first build records a `compatibility` block
  (`unknown flag: --progress`). `doctor` checks the daemon and both plugins (`docker buildx`, `docker compose`) and explains a missing one.
- A dashboard served apart keeps its own model runs and egress in `~/.unbidden/web/<source>-state.db`; `unbidden
  egress` lists them beside the engine's with their origin (`dashboard apart`), and the spend ledger is one. Two
  workspaces with the same repository name share a monthly cap. `unbidden ui` has no `--state-dir`.
- The chat's deterministic repertoire is the rules' list (status, tables, charts, explain, compare two runs, change a
  chart, undo); everything else needs a model.
- Performance workloads are written by a model, and the verdict depends on the data they seed: the same index on
  Conduit measured 18% with one workload and 25% with another.
- The world checks find unindexed foreign keys and table scans; the value of an index on a table that is empty in the
  lab cannot be measured there.
- Masking credential-looking or personal values in prompts hides them from the model too.
- A few real projects, run a few times each: no claim about rates.

## Install and check

The one guide is `docs/INSTALL.md`. The short form, from a checkout, until a release exists:

```sh
git clone https://github.com/satisfymath/unbidden-ai.git && cd unbidden-ai
git checkout feat/63-product-onboarding       # the candidate named above (code 2d72ce4 + docs)
make dist                                      # Node 24 builds the web workspace; uv build; SHA256SUMS
(cd dist && python3 -m http.server 8777 --bind 127.0.0.1 &)
UNBIDDEN_INSTALL_BASE=http://127.0.0.1:8777 sh install.sh --yes --version 0.9.0
unbidden --version                             # unbidden 0.9.0
```

Prerequisites a person provides: git; Docker with its buildx and compose plugins (`docker buildx version` and
`docker compose version` must answer; Docker Desktop and OrbStack install them for the user); for options `mixed` and
`api`, a Meta key, which `unbidden setup` asks for and saves in `~/.unbidden/.env` (mode 600), and a spend cap entered
by a person (`unbidden spend --verified-balance`); for options `local` and `mixed`, Ollama with a model that fits the
machine (setup offers the download; `unbidden doctor --fix` pulls it later). Developers: `uv sync` and `make check`
(ruff, pyright, pytest; the Docker tests skip without a daemon).

## The walk

```sh
cd your-repo
unbidden                     # the assistant: project, priorities, models (local | mixed | api), credentials,
                             # autonomy (supervised | autopilot | autonomous), connections, budget, dashboard;
                             # the diff of the mandate before writing; no model called
unbidden doctor              # required and optional, for the option chosen
unbidden start --ui          # the agent in the background; the dashboard served from its process
unbidden status              # pid, log, stale or not; dashboard URL; kill switch
unbidden chat "why did the last check block?"   # inform by rules, analyze with one routed call; never act
unbidden stop                # ends agent and dashboard; the job in progress returns to the queue
unbidden ui                  # a dashboard served apart: same widgets, same conversation
unbidden ui --stop           # ends only that dashboard
unbidden start               # resumes interrupted jobs; a second start answers "already running: pid N"
```

Without a terminal: `unbidden setup --non-interactive --models api --mode supervised --budget 1.5 --dashboard later
--model-key-stdin --yes --json` (the key on stdin, never in argv or output).

**Walked on 2026-11-01, macOS arm64**, with the installed tool from an empty HOME (`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`,
credentials file written by setup), on a dedicated clone of the fork `satisfymath/rich` at `9d8f9a372cc5`, option
`api`, mode `supervised`, monthly cap US$1.5. Reused from the host, declared: the real spend ledger
(`UNBIDDEN_HOME=/Users/david/.unbidden`, envelope `s11-product`), the machine's Meta key passed on stdin, and
`DOCKER_CONFIG=/Users/david/.docker` after the first attempt without it recorded two `compatibility` blocks for the
missing buildx plugin (kept in the record).

| Step | Result |
|---|---|
| install | `unbidden --version` = 0.9.0; the dashboard's assets inside the wheel |
| setup | mandate `frontier`, `local_inference: deny`, `local_fallback: deny`; `.env` mode 600; the key's name in the JSON, never its value |
| doctor | exit 0: Ollama and local model optional, Meta API and Docker required and present |
| cycle (`start --ui --port 8830 --interval 60`) | the project's checks at the base passed (981 collected, 0 failed); a robustness probe with 3 calls to `muse-spark-1.3` found 1 property violation, kept for a person (L1); 14 events, 0 opportunities (no improvement was needed for this walk) |
| dashboard served by the agent | summary live and current, the agent's pid, the key present (name only), the 14 events by type |
| chat | status by rules without a model; one analysis call (US$0.0051) citing the record's counts and the two Docker blocks; 2 widgets created by rules, provenance `live:rich-s11`, an empty table marked `missing` |
| stop and reopen | `stop` withdrew agent and dashboard; `unbidden ui` on another port showed the same 2 widgets and 8 messages; `ui --stop` ended it |
| stop and resume | a second `start` answered `already` with the same pid, one `watch` process; `kill -9` of the agent: `status` running false, stale true, 1 job running; `start` resumed 1 interrupted job; clean `stop`, no KILL file, 0 processes left; 14 events before and after |
| spend | US$0.0438 (4 calls) in `s11-product`; the machine's cumulative cap unchanged |

Record: `docs/PRODUCT-ONBOARDING-PLAN.md`, "Validación real acotada". Not walked by hand: Linux, options `local` and
`mixed` with a model, `autopilot` and `autonomous`, a project with connections.

## CI on Linux x86-64

Run [41333127432](https://github.com/satisfymath/unbidden-ai/actions/runs/41333127432) on `2d72ce4` (`ubuntu-latest`,
x86-64, 2026-11-01), every job green. Reported apart, as each covers a different thing:

| Job | What ran | Result |
|---|---|---|
| `check` | `uv sync --frozen`, ruff, ruff format, pyright, `pytest -q` (the deterministic suite, mocks for every model) | 939 passed, 2 skipped, 6 deselected (slow) |
| `frontend` | `npm ci`, lint, typecheck, vitest, `npm run build`, Playwright (Chromium) against the Python server serving the built assets on the demo and a historical record | vitest 10 passed; Playwright 7 passed |
| `installed` | the wheel built with the web workspace inside; `install.sh --yes --version 0.9.0` from a local server into an empty HOME; `unbidden --version`; `setup --non-interactive --models api --mode supervised` in a fresh repository; `doctor --json` (Ollama and the local model optional, Meta API required); the home screen; `setup --mode autonomous` refused with exit 4 and nothing written; `start` → `status` (running) → a second `start` refused → one `watch` process → `stop` → `status` (not running, not stale), no KILL file; `unbidden ui` serving the built `index.html` from the installed package (no Node on that path), reused on a second call, `chat` by rules (inform; an action refused), `ui --stop`; Docker reported (present on the runner, with buildx and compose); `install.sh --uninstall --yes` keeping the data | all steps passed |
| `secrets` | gitleaks over the history | clean |

What this does and does not show: artifact install and command resolution on Linux x86-64, yes; onboarding and the
deterministic walk, yes; the daemon's start/stop/status and the dashboard from the installed package, yes; Docker,
only its presence (no sandbox build, no cycle); no model was called (US$0). "Linux validated end to end" would
require a real cycle with Docker and a model on a Linux host, which was not run. The real cycle, the chat analysis
and the dashboard with real events were run on macOS arm64 only (`docs/bench/product-walk-2026-11-01/`).
`release.yml` (manual, publishes nothing) could not be dispatched from the branch: GitHub only runs a
`workflow_dispatch` workflow that exists on the default branch, so it waits for the merge.

## Preparing a project apart

```
unbidden prepare /path/or/url --rev v1.2.3 --into ~/unbidden-lab/name
```

Copies the repository apart at a commit, reads its stack (and says why each version was chosen), builds the
dependency image with network to the mandate's package registries only, reads the CI's test plan (what was left out
and why), runs the project's own checks offline in the sandbox and prints the outcome with its evidence: tests
collected and failed, or why none ran. A block is printed as the finding. `unbidden doctor` inside a repository adds
the scope diagnosis: whether its stack, tests and database are inside what this version supports, and why not when
not. What a person still prepares for the lab (a compose file of the application, synthetic data, a read-only role)
is not part of this command and is counted as human preparation in every record.

## The mandate, by hand

`unbidden setup` writes it; `unbidden setup <section>` changes one part; `unbidden mode` and `unbidden models` change
the two most common. It can also be edited: `unbidden init` writes the supervised default. A mandate, without secrets
(secrets go in `~/.unbidden/.env` or `.unbidden/.env`, mode 600, referenced by name):

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
  models: {profile: frontier, local_fallback: deny, local_inference: deny}    # what the option `api` writes
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
  revocations, spend), `unbidden why <opportunity>`, `unbidden connections`, `unbidden egress`, `unbidden spend`;
  the dashboard and `unbidden chat` read the same records.
- `.unbidden/state.db`: opportunities with their history, experiments with every measured session raw, verdicts
  and revocations, goal runs, acceptances, model runs, egress attempts; `.unbidden/artifacts/`: patches, workloads,
  probe files, logs; `.unbidden/logs/agent.log`: the background agent's output.
- To keep a run's evidence, move the whole `.unbidden/` out of the repository after it (the harnesses do); the
  spend ledger is per machine and is never reset. A kept `.unbidden/` can be served read-only as a historical source
  (`python -m unbidden.web --record`).

## Stop, clean up, recover, roll back

- `unbidden stop` ends the background agent cleanly: the job in progress returns to the queue without spending an
  attempt; the kill switch is not touched. `unbidden start` resumes; after a crash or `kill -9`, `status` says the last
  run ended without `stop` and the next `start` requeues what was running.
- `unbidden kill` stops everything now (no new job or model call, in every process; running sandbox containers
  killed; pushes, pull requests, merges, deploys and rollbacks check it immediately before acting); `unbidden resume`
  lifts it; `kill --stop` also ends the agent.
- Experiments work on snapshots, never on the repository; a proposal is a local branch (or a pull request where the
  mandate allows), reverted like any commit. A deploy is rolled back with the mandate's own steps; a failed one leaves
  a hold only a person releases (`unbidden hold`).
- A lab verdict that does not hold is revoked, not erased (`unbidden/lab/revoke.py`): kept with its reason.
- Clean up: sandbox containers carry `unbidden.sandbox` (`docker ps -a --filter label=unbidden.sandbox`); dependency
  images are `unbidden-deps-*`; the workspace is `.unbidden/`. The benchmark labs own their resources by identity
  (`unbidden.lab.id=<lab>`): `... down` removes only that lab's containers and networks and keeps its data; `--volumes`
  removes the data too.
- Roll back the tool itself: `unbidden update --version <previous>` or `sh install.sh --version <previous>`; data
  untouched. `unbidden uninstall --yes` removes the tool and keeps `~/.unbidden` and every `.unbidden/`.

## The demo

The recorded demo is stage 9's, on the engine this candidate carries: `docs/bench/stage9-demo.md`, written from the
run's records by `bench/ecosystem/demo9_report.py` (no model writes it), with an independent check
(`bench/ecosystem/conduit_indep.py`: the endpoints' own SQL on the lab data, rolled back). Run DEMO-B-1 at 2f3986e on
Conduit, a **development** application: a demonstration, not evaluation evidence.

- Harness (not Unbidden): the repository at 029eb77, synthetic data (2,000 users, 20,000 articles, 300,000
  comments, 20,000 favorites), a read-only role, a fresh token, a proactive mandate with no goal, the `demo`
  envelope; one declared answer (a registry Unbidden names: `deb.debian.org`).
- Unbidden: the project's checks at the base (90 passed); six opportunities; two L4 under perf-v3
  (`commentaries.article_id` 24.1 -> 18.3 ms, `favorites.article_id` 9.6 -> 1.7 ms, the index used on every
  measured call), one measured "no change" (`articles.author_id`), one not measurable (its workload failed), two
  consistency questions inconclusive (completeness unknown); two local branches with migrations; nothing pushed.
  US$0.53, 46 calls, 47 minutes.
- Independent check: the comments listing 8.27 -> 0.06 ms; the article delete 0.61 -> 0.20 ms with comments indexed
  on both sides. Both L4s confirmed.

The product walk (install, setup, `start --ui`, dashboard, chat, stop and start) has no recorded demo yet; its
validation is the table under "The walk". `demo/autonomous.sh` is the older CLI demo (marshmallow, from a checkout
with `uv run`, autonomous locally, pull requests only to the fork).

## Integration proposal

Facts from the graph (origin, 2026-11-01): `main` is `d560b6f` (the merge of PR #2, 0.9.0 + the web workspace). The
product branch `feat/63-product-onboarding` was cut from it and is 27 commits ahead, among them three `--no-ff`
merges of its own side branches (`feat/63a-distribution`, `feat/63c-daemon`, `feat/63e-docs`, all merged and
deleted). A test merge of the branch into `main` in a scratch worktree is clean: 71 files, +7,885/-421, no
conflicts. The branch is published on origin for CI only; no pull request, merge, tag or release was made.

Proposal, for a person to carry out, in this order: (1) read the CI results of the branch head (above) and the walk's
evidence (`docs/PRODUCT-ONBOARDING-PLAN.md`); (2) one pull request `feat/63-product-onboarding` -> `main`, merged with
`--no-ff` (the result's tree equals the branch's); (3) only then `.github/workflows/release.yml` can be dispatched (a
`workflow_dispatch` workflow must exist on the default branch to be run): run it once in its only mode, build and
smoke-test without publishing, and read the Linux smoke report it uploads; (4) the first release, when David decides
it: tag `v0.9.0`, a GitHub release carrying `unbidden_ai-0.9.0-py3-none-any.whl`, `SHA256SUMS` and `install.sh`
(the commented block at the end of `release.yml` shows the shape), after which the one-line install in
`docs/INSTALL.md` becomes true and the "available once..." notes are removed; (5) PyPI (`unbidden-ai`, free) as a
second channel later. Rollback of (2): `git revert -m 1` of the merge commit, or a reset before anything is built on
it; the spend ledger, the labs' data and every workspace's `.unbidden/` live outside the repository. The version
stays "0.9.0, experimental candidate" until another decision is taken explicitly.
