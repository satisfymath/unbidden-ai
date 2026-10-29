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

This file is updated after the commit it names, so read it from the branch head, not from that commit.

```sh
git clone git@github.com:satisfymath/unbidden-ai.git && cd unbidden-ai
git checkout f8d3fc2         # the release named above
uv sync                      # dependencies from uv.lock
make check                   # ruff, pyright, unit tests (about 580, under a minute)
uv run unbidden doctor       # docker, models, keys, sandbox: what works and what does not
uv run unbidden spend        # the machine-wide spend ledger and its cap
```

The Meta key lives in `~/.unbidden/.env` (mode 600, never in the repository) as `MODEL_API_KEY=<key>`; add it once,
by editing that file (do not append a second line if one is there). What `doctor` says, and what it means:
- `workspace not initialized`: expected outside a project; a project becomes a workspace with `unbidden init` in its
  repository (the lab's scripts below do it for the lab's projects);
- `the model listing refuses the key (401)`: seen on 2026-10-29 while chat calls with the same key worked; it does
  not by itself mean the key must be replaced; `unbidden spend` and a run's `model_runs` show whether calls succeed.

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

## Integration proposal (verified on the git graph, 2026-10-29; no PR or merge in this stage)

**Candidate:** the head of `feat/57-transfer` once stage 7 closes (its commit recorded in `docs/PLAN.md`); until
then, `feat/56-consolidation` @ 536fafe (release f8d3fc2).

**Relation with `main`:** `main` is 790a711, the merge of PR #1 (`hackathon-build`); its tree is identical to
b3f7433, which is where the whole stack starts. The stack is one linear line from b3f7433 to the candidate (227
commits at `feat/57-transfer`, no merge commits). Branches 01-13, 18-19 and 21-57 are ancestors of the candidate:
integrating the candidate integrates them all; they need no separate merge. Branches 14-17 are not ancestors, but
every one of their commits is in the stack under a rebased commit (same subject); nothing of theirs is lost.

**Commits that are not in the candidate and must not be lost:** one, `feat/20-scale-eval` a77ef43 (docs: v5 paired
against v4 on dev; 4 files, a 30,000-line JSON). Either cherry-pick it onto the candidate before integrating, or keep
the branch as its record.

**Checks before integrating:** `make check` on the candidate (ruff, pyright, about 600 unit tests); the release walk
in this file from a clean checkout; a test merge into `main` (done on 2026-10-29 in a scratch worktree: no conflict).

**Strategy:** one merge of the candidate into `main` (`git merge --no-ff`), not 50 branch-by-branch merges, since
the stack is linear and already contains every branch. A fast-forward is not possible: main's merge commit is not in
the stack. **Rollback:** `main` is moved back to 790a711 (the merge is one commit; reverting it with
`git revert -m 1` restores main's tree exactly, since main's tree equals b3f7433). The stacked branches stay on the
remote either way.
