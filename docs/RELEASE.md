# Unbidden: release candidate (stage 8): an experimental candidate, not 1.0

**Status: experimental candidate.** Not 1.0: the exit criteria are in `docs/PLAN.md` (stage 8, "Exit criteria"),
each with its evidence; the ones without evidence say what blocks 1.0. Nothing is published, released, merged or
deployed.

## The exact point

- Code: commit **CANDIDATE** on branch `feat/58-reproduce`. `uv.lock` pins every Python dependency (Python 3.12).
  This file is updated after the commit it names, so read it from the branch head, not from that commit.
- Tested on (and only on): macOS 27.0.1 on Apple Silicon (arm64); Docker Desktop with Engine 29.8.2 (linux/arm64
  containers); uv 0.13.1; git 2.56; Ollama 0.40.9 with `muse-glimmer:30b-mxfp8-dflash`; the Meta Model API
  (`muse-spark-1.3` on the `code` route). Linux and x86-64 hosts were not tested.
- Projects whose experiments ran here: Python 3.9 (Conduit), 3.10-3.12 (full-stack-fastapi-template, mealie, Rich,
  LNbits); Node and Go through their adapters, on development fixtures only.

## What it supports, and what it does not

| Area | Supported (exercised) | Not supported or not exercised |
|---|---|---|
| Repository | a git repository; Python projects declared by `pyproject.toml` (uv or Poetry locks), `requirements.txt` or `setup.py`; the interpreter chosen from the project's declarations (CI matrix, Dockerfile, `.python-version`, `requires-python`, locks), the rule recorded | build systems that need network at test time; interpreters outside 3.8-3.13 |
| Checks | the project's own tests (pytest), ruff, pyright, mypy where declared; the CI's GitHub Actions job read for its command and its service containers (PostgreSQL and the like become sidecars) | CI jobs defined only through reusable workflows or composite actions (read partly: LNbits); other CI systems |
| Running system | Docker Compose projects on this machine: containers, published ports, the live OpenAPI, PostgreSQL catalogs (read inside the container, read-only), also for a service started from a compose file it does not read | Kubernetes, remote hosts, cloud accounts |
| Databases | PostgreSQL over the network, read-only role, bounded reads, revocation | MySQL, SQLite connections (SQLite only as a test database), IAM auth |
| HTTP APIs | OpenAPI 3.0 and 3.1, an API key in a header; page, offset/limit and cursor pagination; deviations between the document and the answers recorded per operation and field; writes with an `Idempotency-Key` header undone by a DELETE | OAuth, tokens obtained by a flow, keys in a query string, SOAP, GraphQL, writes without an observable undo |
| Code hosts | GitHub with a token (read; pull requests where the mandate allows) | others |
| Models | local (Ollama) and Meta's API, routed per content label; private code leaves only renamed | other providers |

## What it may do, and when a result is accepted

The mandate (`.unbidden/mandate.yaml`) says what runs on its own: `observe`, `run_experiments`,
`provision_dependencies`, `use_new_capabilities`, `delegate_synthetic`, `open_pull_requests`, `merge_pull_requests`,
`deploy`, `rollback`, `act_on_connections` (each `allow`, `require_approval` or `deny`), the registries builds may
reach (`egress.package_registries`), where model calls may go, a monthly spend cap, and the connections with their
permissions. Credits never widen permissions.

- An experiment is judged by the project's own checks, run on both sides in the sandbox (no network while it runs);
  a change is an improvement only when the checks agree on both sides and the measurement passes its criteria
  (evidence levels L1-L6, `README.md`).
- A goal's result is an acceptance with sealed conditions: `applied` (changed), `accepted` (every condition verified
  by Unbidden's own checks), `rejected`, `inconclusive` (a condition could not be verified) or `stale`; the model's
  own claim is recorded apart and never decides.
- A request to a person names the blocked operation, its evidence, the minimum that unblocks it and what continues;
  one request per need; the work it holds runs again as soon as the mandate shows it met. An access that blocks
  nothing is listed as optional, never as a requirement.

## Known limitations (each seen in stage 8 or before)

- Proactive runs build no API integration; an API is read when a goal needs it.
- An API whose listing declares no total under a name the reader knows (`total`, `count`, `total_count`) is read
  completely only as "unknown": a goal that needs the whole set blocks (Conduit). There is no general way yet to
  tell such a read complete.
- Workloads for performance experiments are written by a model; on asyncpg-based code (Conduit) most attempts did
  not run at the base. No improvement was demonstrated on Conduit or LNbits in this stage.
- The world checks find unindexed foreign keys and table scans; a project whose foreign keys are indexed (LNbits)
  gets no finding from them, correctly, and there are few other kinds of database finding.
- Masking credential-looking values in prompts (`password="password"` in tests) hides them from the model too.
- Results come from a few real projects run once or a few times each; no claim about rates.

## Install and check

```sh
git clone https://github.com/satisfymath/unbidden-ai.git && cd unbidden-ai
git checkout CANDIDATE        # the candidate named above
uv sync                       # dependencies from uv.lock
make check                    # ruff, pyright, unit tests (about 640, under a minute)
uv run unbidden doctor        # Docker, local model, Meta key, GitHub, mandate: what works and what does not
uv run unbidden spend         # the machine-wide spend ledger and its cap
```

Prerequisites a person provides: Docker running; Ollama running with a model (`unbidden doctor --fix` picks and
pulls one that fits the machine); for remote models, a Meta key in `~/.unbidden/.env` as `MODEL_API_KEY=<key>` (mode
600, never in a repository; add it once by editing that file); for remote spend, a cap entered by a person
(`unbidden spend --verified-balance USD --source ... --reserve FRACTION`). Without the key, everything local works
and `doctor` says the remote route is unavailable.

## A first run on a project

```sh
cd your-repository
uv run --project /path/to/unbidden-ai unbidden init           # .unbidden/ with a supervised mandate
$EDITOR .unbidden/mandate.yaml                                # autonomy, registries, connections (see below)
uv run --project /path/to/unbidden-ai unbidden watch --once   # one cycle: map, checks, decisions, experiments
uv run --project /path/to/unbidden-ai unbidden activity       # what it found, decided, built, asked, spent
```

A mandate, without secrets (secrets go in `.unbidden/.env`, mode 600, referenced by name):

```yaml
mandate:
  workspace: shop
  priorities: [correctness, performance of reads as data grows]
  business_constraints: {maximum_monthly_spend_usd: 1.5}
  autonomy: {observe: allow, run_experiments: allow, provision_dependencies: allow, delegate_synthetic: allow,
             use_new_capabilities: allow, open_pull_requests: deny, merge_pull_requests: deny, deploy: deny,
             rollback: deny, act_on_connections: deny}
  egress: {package_registries: [pypi.org, files.pythonhosted.org],
           remote_models: {destinations: [api.meta.ai], max_payload_bytes: 60000}}
  models: {profile: local-first, local_fallback: allow}
  connections:
    - {id: shop-db, kind: postgres, location: 127.0.0.1:5432/shop, environment: staging, username: shop_reader,
       credential_ref: SHOP_READER_PW, permissions: [read]}
    - {id: shop-api, kind: http_api, location: http://127.0.0.1:8000, docs: http://127.0.0.1:8000/openapi.json,
       environment: staging, credential_ref: SHOP_API_KEY, permissions: [read]}
```

`content_may_leave: true` on a connection and `private_code_to_frontier: allow` are a person's statement that the
data and code are synthetic; on real projects leave them out (data then stays local; code leaves only renamed).

## Evidence: where it is, how to keep and review it

- In the workspace: `unbidden activity` (found, decided, blocked, asked, built, proven, spent), `unbidden why <opp>`
  (decisions, verdicts and every outbound payload), `unbidden connections`, `unbidden egress` (everything that left
  the machine, by digest), `unbidden spend`.
- On disk: `.unbidden/state.db` (opportunities with their history, experiments, verdicts, blocks, goal runs,
  acceptances, model runs with model, route, tokens and cost, egress attempts); `.unbidden/artifacts/` (probes,
  workloads, logs, screenshots).
- To keep a run's evidence, move the whole `.unbidden/` out of the repository after it (the stage 8 harnesses do
  this: `bench/ecosystem/conduit_eval.py`); the ledger `~/.unbidden/spend.db` is per machine and never reset.

## Stop, recover, revert

- `unbidden kill` stops everything now: no new job or model call, running sandbox containers (labelled
  `unbidden.sandbox`) killed, and pushes, pull requests, merges, deploys and rollbacks check it immediately before
  acting; `unbidden resume` lifts it.
- A hold placed after a failed deploy is released only by a person (`unbidden hold`); `unbidden deploys` lists every
  deploy and the code it ran; rollback uses the mandate's own steps.
- Experiments work on snapshots, never on the repository; a proposal is a branch or a pull request, reverted like
  any commit. Nothing is merged or deployed unless the mandate allows it.
- Clean up: `docker ps -a --filter label=unbidden.sandbox` (sandbox containers, normally already gone),
  `docker images 'unbidden-deps-*'` (dependency images, rebuilt when needed), and the workspace's `.unbidden/`.

## The walk (clean checkout, fresh HOME)

WALK

## The lab, up and down

```sh
uv run python -m bench.ecosystem.depot_lab up          # PostgreSQL, Depot, the picker app (127.0.0.1 only)
uv run python -m bench.ecosystem.board_lab reset style # the board with one seeded defect (or `healthy`)
uv run python -m bench.ecosystem.board_workspace "$PWD" --policy local --perception dom
(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden watch --once)
uv run python -m bench.ecosystem.board_check           # the independent, model-free checker
uv run python -m bench.ecosystem.board_lab down && uv run python -m bench.ecosystem.depot_lab down
```

`--policy spark` uses Meta's API (needs the key). Every lab resource carries the label `unbidden.lab=ecosystem` and
listens on 127.0.0.1; `down` removes only those. Stage 8's applications: `conduit_lab.py` / `conduit_eval.py`
(regression) and `lnbits_lab.py` / `lnbits_eval.py` (the independent application).

## Integration proposal (verified on the git graph; no PR or merge in this stage)

INTEGRATION
