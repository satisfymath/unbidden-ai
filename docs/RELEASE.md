# Unbidden: release candidate (stage 9): an experimental candidate, not 1.0

**Status: experimental candidate.** Not 1.0: the exit criteria and their evidence are in `docs/PLAN.md` (stage 9,
"Exit criteria"). The one that blocks 1.0: no useful cycle has been shown on an application not used in development
(the frozen evaluation, `docs/bench/stage9-evaluation.md`, ended in four technical blocks). Nothing is published,
tagged, released, merged or deployed.

## The exact point

- Code: commit **1c4cab7** on branch `feat/59-v1`. `uv.lock` pins every Python dependency (Python 3.12). This file
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
git checkout 1c4cab7          # the candidate named above
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
- A lab verdict that does not hold is revoked, not erased (`unbidden/lab/revoke.py`): kept with its reason.
- Clean up: sandbox containers carry `unbidden.sandbox` (`docker ps -a --filter label=unbidden.sandbox`); dependency
  images are `unbidden-deps-*`; the workspace is `.unbidden/`. The benchmark labs own their resources by identity
  (`unbidden.lab.id=<lab>`): `... down` removes only that lab's containers and networks and keeps its data; `--volumes`
  removes the data too.

## The walk (clean checkout, empty HOME)

`docs/bench/stage9-walk/walk.sh`: an empty HOME (`mktemp -d`), a fresh HTTPS clone of the candidate, only the
commands of this file, then a mandate, one cycle on the board lab, the evidence commands, stop, resume and cleanup.
Declared departures from a stranger's machine: Docker's compose plugin directory is linked from the machine user's
HOME; the HOME has no Meta key and no local model, so the cycle's model calls are refused with their reason (stage 9
uses Meta's API only, and the key is never copied); the lab's PostgreSQL volume is the machine's, kept between walks.

| Walk | Candidate | Result | What it found (fixed in the next candidate) |
|---|---|---|---|
| 1 | 2f3986e | 18 of 18 | every command ran, but the text `activity` did not show the base checks or revocations, and a probe whose model call was refused did not say why (fixed in 62e97d2) |
| 2 | 62e97d2 | 17 of 18 | the board lab's app did not answer, with nothing to show why (672014c: it starts the app again while it does not answer, and prints its state and logs when it never does) |
| 3, 4 | 672014c | 17 of 18 | the logs showed why: the board's reader role kept a password from an earlier walk's secrets, because the kept database volume outlives a HOME (fixed in 1c4cab7: every lab sets its roles' current password on each setup) |
| **5** | **1c4cab7** | **18 of 18** | clone 1 s, `uv sync` 4 s, `make check` 48 s (691 tests), `doctor` (no key, no GitHub token: said so), labs up, `init`, one cycle (map: 5 resources, 1 blind spot; the project's checks at the base passed, 2 collected; the probe's model call refused: "the mandate denies local inference, and this call may not go remote"), `activity`, `connections`, `egress`, `kill`, `resume`, labs down; no sandbox container left; the other labs' containers untouched |

Logs: `docs/bench/stage9-walk/walk{1..5}.log`. Not walked: Linux, x86-64, a HOME with the Meta key (the paid
cycle is shown by the demo instead).

## The demo

`docs/bench/stage9-demo.md`, written from the run's records by `bench/ecosystem/demo9_report.py` (no model writes
it), with an independent check (`bench/ecosystem/conduit_indep.py`: the endpoints' own SQL on the lab data, rolled
back). Run DEMO-B-1 at 2f3986e (the candidate differs from it in the activity text, a probe message and lab
scripts: three commits, none in the measured path), on Conduit, a **development** application: a demonstration,
not evaluation evidence.

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

## Integration proposal (from the git graph; no PR, merge or tag in this stage)

Facts from the graph (origin, 2026-10-30): `main` is 790a711, the merge of PR #1, whose tree is identical to
b3f7433's; b3f7433 is an ancestor of the candidate. The candidate is 291 commits past `main`, with no merge commit.
Of the other remote branches, `feat/14-routing` .. `feat/17-monorepo` carry two commits whose patches differ from
the candidate's but whose changes are in it, rewritten (984064f as bd5ea97, 032c26b as b282d22): nothing to bring.
**`feat/20-scale-eval` has one commit the candidate lacks: a77ef43** (docs: the v5 evaluation paired against v4 on
dev); it cherry-picks onto the candidate without conflict (tested in a scratch worktree).

Proposal, for a person to carry out: (1) cherry-pick a77ef43 onto `feat/59-v1`; (2) `make check`; (3) one pull
request `feat/59-v1` -> `main`, merged with `--no-ff` (tested: clean, and the result's tree equals the candidate's);
(4) the old feature branches deleted only after that merge. Rollback: `main` returns to 790a711 (`git revert -m 1`
of the merge commit, or reset before anything is built on it); the spend ledger, the labs' data and the archived
workspaces live outside the repository and are unaffected. No pull request, merge, tag or release was made.
