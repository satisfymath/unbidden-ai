# Unbidden: a reproducible point (stage 6)

What this covers, and only this: the evidence of stages 3-6 (`docs/bench/ecosystem/RESULTS.md`) is about projects
whose systems are PostgreSQL databases, REST APIs described by OpenAPI 3.0 or 3.1 (header API keys; page, offset or
cursor pagination; writes with an `Idempotency-Key` header undone by a DELETE on the written resource), a git
repository with docker compose, and web pages it can load locally. It is not evidence that Unbidden can connect to
any system: OAuth, SOAP or GraphQL, other auth schemes, writes without an observable undo, and real production
systems were not exercised.

## The exact point

- Code: commit **f8d3fc2** on branch `feat/56-consolidation`. Its product, harness and dependencies are identical to
  94765da, on which the frozen stage 6 evaluation and the recorded demo ran (`docs/bench/stage6-freeze.md`,
  `docs/bench/stage6-demo.md`); it adds the records and one test fix (a goals test fixed to a date failed after
  midnight UTC, found from a clean checkout). `uv.lock` pins every Python dependency (Python 3.12).
- Tools: `uv`, Docker (Docker Desktop on macOS used here), git; for the local model, Ollama with a Meta model
  (used here: `muse-glimmer:30b-mxfp8-dflash`); for the remote models, a Meta API key.
- Remote models: `muse-spark-1.3` on the `code` route (default), `muse-wonder-1.0` only as a declared comparison;
  `sam-3.1` optional (page perception `vision_sam`). Prices: dev.meta.ai list prices (D-042).

## Install and check

```sh
git clone git@github.com:satisfymath/unbidden-ai.git && cd unbidden-ai
git checkout f8d3fc2
uv sync                      # dependencies from uv.lock
make check                   # ruff, pyright, unit tests (about 570, under a minute)
echo 'MODEL_API_KEY=...' >> ~/.unbidden/.env && chmod 600 ~/.unbidden/.env   # never in the repository
uv run unbidden doctor       # docker, models, keys, sandbox: what works and what does not
uv run unbidden spend        # the machine-wide spend ledger and its cap
```

Spend: every remote call reserves its worst cost in `~/.unbidden/spend.db` before it is sent and is refused past
the cap a person entered (`unbidden spend --verified-balance USD --source ... --reserve FRACTION`). The ledger is an
estimate (list price x reported tokens), not a bill.

## A mandate, without secrets

`.unbidden/mandate.yaml` in the project (secrets go in `.unbidden/.env`, mode 600, referenced by name):

```yaml
mandate:
  workspace: boardapp
  autonomy: {observe: allow, run_experiments: allow, deploy: allow, rollback: allow,
             act_on_connections: deny, use_new_capabilities: allow, open_pull_requests: deny,
             merge_pull_requests: deny, provision_dependencies: deny, delegate_synthetic: allow}
  egress: {package_registries: [], remote_models: {destinations: [api.meta.ai], max_payload_bytes: 120000}}
  models: {profile: frontier, private_code_to_frontier: allow, screenshots_to_frontier: deny}
  operations:
    deploy_steps: [[docker, compose, -p, boardapp-staging, up, -d, --build]]
    check_steps: [[python, -m, unittest]]
    check_image: python:3.12-slim
  connections:
    - {id: board-db, kind: postgres, location: 127.0.0.1:55432/boardpicks, environment: staging,
       username: board_reader, credential_ref: BOARD_READER_PW, permissions: [read], content_may_leave: true}
    - {id: board-api, kind: http_api, location: http://127.0.0.1:18086, docs: http://127.0.0.1:18086/openapi.json,
       environment: staging, credential_ref: BOARD_DEPOT_KEY, permissions: [read], content_may_leave: true}
  goals:
    - id: board-flags
      statement: Every bin with a shortfall must be flagged on the restock board with a red SHORT badge ...
      bounds: {environment: staging, max_changes: 2}
```

`content_may_leave` and `private_code_to_frontier` are a person's statement that this lab's data and code are
synthetic; on real projects leave them out (data then stays local; code leaves only renamed by the privacy bridge).

## The lab, up and down

```sh
uv run python -m bench.ecosystem.depot_lab up          # PostgreSQL, Depot, the picker app (127.0.0.1 only)
uv run python -m bench.ecosystem.board_lab reset style # the board with one seeded defect (or `healthy`)
uv run python -m bench.ecosystem.board_workspace "$PWD" --policy spark --perception dom
(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden watch --once)
uv run python -m bench.ecosystem.board_check           # the independent, model-free checker
uv run python -m bench.ecosystem.board_lab down && uv run python -m bench.ecosystem.depot_lab down
```

Every lab resource carries the label `unbidden.lab=ecosystem` and listens on 127.0.0.1; `down` removes only those.

## Evidence

- `unbidden activity`, `unbidden connections`, `unbidden spend`, `unbidden egress` in the workspace;
- the workspace's `.unbidden/state.db` (goal runs with their evidence: scans and their digests, patches, checks,
  deploys; actions; model runs with model, route, tokens and cost; egress attempts by digest);
- screenshots under `.unbidden/artifacts/pages/<run>/`; the checker's `verdict.json` and screenshots.

## The demo

`uv run python -m bench.ecosystem.board_demo "$PWD"`: see `docs/bench/stage6-demo.md` for what it shows, what the
harness prepares, and a recorded run with its cost.

## Integration order of the stacked branches (proposed; no PR or merge in this stage)

`main` is at the merged `hackathon-build`. Every later branch is stacked on the previous one, so they integrate in
this order, each into `main` after the one before it:

1. `feat/18-runtime-truth` .. `feat/38-eval-v2`: the evidence and boundary work (stage 2); branches 14-17 are already
   contained in this stack under rebased commits (same subjects).
2. `feat/42-postgres-network` .. `feat/47-ecosystem-dev-fixes`: connections, Forge API clients, typed actions, goals.
3. `feat/48-stage4-plan` .. `feat/54-blocked-needs`: authorization of effects, complete reads, postconditions,
   extension, routing on Meta, blocked needs.
4. `feat/55-send-time-authorization`: writes authorized as they leave; the page goal; images through the router.
5. `feat/56-consolidation`: OpenAPI by version, inconclusive page checks, perception metrics, Linen, this release.

One commit outside the stack: `feat/20-scale-eval` a77ef43 (docs: v5 paired against v4 on dev), a report only; it
can be cherry-picked onto the stack before step 1 merges, or left in its branch as a record.
