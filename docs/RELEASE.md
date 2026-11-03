# Unbidden 0.12.4, experimental candidate: the terminal app on the product branch, not 1.0

## 0.12.4 (2026-11-03): Flask applications have endpoints

On the demo copy of ihatemoney (Flask with blueprints and Flask-RESTful, no OpenAPI document) the map had tables
and no endpoints, so `unindexed_foreign_keys` and `full_table_scans` dropped every finding (an opportunity names the
endpoints that pay for it; with none, there is nothing to measure) and the only opportunity was a ruff finding.
Endpoints were read from FastAPI routers and from a live OpenAPI document only.

- `world/flask_routes.py`: a Flask application's routes, read from the code: `Blueprint(..., url_prefix=)` and the
  prefix given to `register_blueprint`, `@bp.route(path, methods=[...])` and `@bp.get/post/...`, Flask-RESTful's
  `Api(bp, prefix=)` and `add_resource(Cls, "/path", ...)` as one endpoint per HTTP method the resource class
  defines. `<int:x>` reads as `{x}`, so a live document, when there is one, reconciles the same way. Each endpoint
  carries its handler's file and line (`static.py` adds them as inferred, `prefix_known`, `framework: flask`; a
  file that declares Flask routes is not read as a FastAPI router too).
- `world/column_use.py`: a Flask-SQLAlchemy model without `__tablename__` maps to its class name in snake case
  (`Bill` -> `bill`, `ShoppingList` -> `shopping_list`), in the static table resources too; a handler that filters
  by the column in its own body counts, and a call reaches the repository's only definition of that function
  whatever the file names say (`web.py` calling `models.py`'s `get_bills_unordered`).
- The "describe no OpenAPI" and "full endpoint paths" blind spots are not raised for endpoints read from Flask.

Seen on the demo copy, from a checkout: 83 resources instead of 20; 64 endpoints; two opportunities on the first
map: `person.project_id is a foreign key without an index, filtered on by 7 endpoint(s)` and `bill.payer_id ...
filtered on by 1 endpoint(s)` (`GET /{project_id}/`, via `list_bills` and `get_bills_unordered`). Measuring them
in the lab against a Flask server is the next walk.

## 0.12.3 (2026-11-03): a key is proven before anything runs on it; the installer speaks in steps

Seen on the first end-user walk on Linux (`curl -fsSL https://unbidden.cl/install.sh | sh`, 0.12.2, Fedora, a public
copy of ihatemoney): the person pasted a shell command where the setup asked for the Meta API key. The setup saved it,
the free model listing answered 401 and the text said inference might still work; nothing proved the key. The agent
then ran for an hour and a half with every remote call refused (`invalid_api_key`): the labs swallowed the error as
"no usable answer" and counted an attempt against the opportunity, the probe said "no model answered" in the log, the
app's bar said only "spend cap not verified", and the ledger charged US$0.04 for calls Meta had refused. Each is fixed
here, with its test:

- **A key is proven when it is pasted.** A value that cannot be a key (a command, spaces, under 16 characters) is
  refused in place and asked again. Then one short inference call (8 tokens, under a cent, in the ledger) says
  "Key accepted: muse-spark answered" or "Meta refused this key", and a refused key gets a menu: paste another, use
  a local model, or continue without one (the agent refuses to start). A key saved earlier is proven the same way,
  once per key: `~/.unbidden/keys.json` keeps its fingerprint and the verdict, never the key (`setup/keycheck.py`).
  `--probe` is gone: proving is not optional.
- **A 401 is "key rejected", never billed, never retried.** `ProviderUnauthorized` (401/403) is a `ProviderRejected`:
  the ledger row settles at US$0, `MODEL_CALLED` carries `problem: key rejected`, the labs and the research code
  re-raise it instead of treating it as a failed answer, so the loop records a `pending_person` block ("a Meta API
  key the service accepts: `unbidden key set`") and spends no attempt of the opportunity.
- **Nothing starts on a refused key.** `start` and `/start` prove a saved key once (a refused one refuses the start
  with `unbidden key set`; one that cannot be proven now only warns). `doctor`'s `meta api` line says what the key
  does, not what the listing says. The app's bar shows `MODEL KEY REFUSED · /key` from the first refused call.
- **`unbidden key`, `unbidden key set`, `unbidden key remove`, and `/key` in the app:** the key's state, a new one
  pasted hidden and proven on the spot, or gone. `setup credentials` and `setup models` use the same step.
- **A local model, made to work.** When the option needs a local model that is not there, the setup installs Ollama
  (the official installer in the person's terminal on Linux, Homebrew on macOS, after asking), starts its server,
  pulls the model that fits and proves it with one short generation; `doctor --fix` does the same. A small model is
  said to be small: it serves what never leaves the machine.
- **The installer speaks in steps.** On a terminal: `✓ uv 0.9.x`, `✓ Downloading unbidden 0.12.3`, `✓ sha256
  verified`, `✓ Installing unbidden 0.12.3`, then the installed path and the two commands that matter. What uv and
  curl print goes to a log shown only when a step fails; `--verbose`, `UNBIDDEN_INSTALL_VERBOSE=1`, and any run
  without a terminal (CI) print every line as before.

Verified here: the unit and app suites (`make check`); the installer from local artifacts into an empty HOME, on a
terminal and through a pipe; `unbidden key set` with a wrong key against the real API (refused at once, US$0 in the
ledger, `start` refused); the demo repository's walk is the person's, after the release.

## 0.12.2 (2026-11-02): the route shown is the route run; the egress gate reads code as the prompt guard does

Three things seen on the first walk on Linux (Fedora x86-64, option `api`, mode `supervised`, a public copy of the
FastAPI full-stack template), each a fix with its test:

- A lab's progress line said "asking the local model for the schema change" while the call went to Meta's API; the
  text was fixed in the code. The labs now ask the Brain where the call goes (`Brain.where`, dry) and say so:
  `asking the model at api.meta.ai (muse-spark) for the schema change`, `the local model (llama3.2:3b)`, or `no
  model` with the mandate's reason.
- `unbidden route` showed `fallback local` under a mandate with `local_fallback: deny` or `local_inference: deny`:
  both rules were applied only when a call was made (`Brain.complete`). `apply_mandate` (`brain/route_policy.py`)
  applies them in `Brain.decide`, which `route`, the chat and the labs read, so what is shown is what runs: a call that
  may run nowhere shows `denied` with the reason; a refused fallback shows `-` and names the rule. When the first model
  fails, a refused fallback is still recorded (`MODEL_FALLBACK`, `taken: false`), never taken.
- The egress gate refused five `world.endpoint_tables` requests over public code ("payload contains 1 secret(s)")
  that the prompt guard had passed. The gate scans the request serialized as JSON, where a newline is the two
  characters `\n`, so `password=user_in.password\n` read as a value ending in a backslash and no longer looked like
  code. A backslash now ends a value; a parameter's type annotation inside a parameter list (`token: TokenDep)`) and
  the template's `changethis` placeholder are not secrets. On the template's five files that were refused: 8 false
  hits before, once serialized; 0 after; the suite's real-secret cases are still refused, raw and serialized.

## 0.12.1 (2026-11-02): GitHub through gh, no OAuth App

The browser sign-in no longer needs an OAuth App of Unbidden's own: the setup's "gh" choice installs the `gh` CLI
when it is missing (the machine's package manager, in the person's terminal, after asking) and runs
`gh auth login --web`; the app steps aside for it and comes back. Unbidden reads that session as it already did
(`gh auth token`, held in memory, never copied). The device-flow module is gone. The found block now also asks
GitHub who the access found is and whether that account can push to the repository of the remote; an account
that cannot gets the same menu as no access. Tab in the app completes a command instead of moving the focus.

## 0.12.0 (2026-11-02): Spanish

What Unbidden says to the person follows a language: the app, the setup assistant, the home screen, `/help`, the
chat's own sentences and the installer's closing lines, in English or Spanish. Resolved from `UNBIDDEN_LANG`, then
the choice saved on the machine (`/language es|en`, `unbidden setup language`), then the terminal's locale, then
English; a key a translation lacks falls back to English. Not translated: the other CLI commands, the engine's
records (reasons, titles, pull request text stay as recorded) and the web dashboard, which stays Spanish. A third
language is one `text_<code>.py` per table. `docs/INSTALL.md`, "Languages".

## 0.11.0 (2026-11-02): setup asks three things

The assistant finds the repository and its GitHub remote, where GitHub access comes from (a saved token, the
environment, or the `gh` CLI's sign-in, held in memory and never copied), the scope, the connections the compose
files declare at HEAD (listed, never granted on their own), the machine, Ollama and its models, and whether a key
is saved; the model option follows from those facts. It asks the Meta API key only when none is found, how much
Unbidden may do on its own, and whether to apply. Priorities, budget, dashboard, private code and manual
connections keep their defaults, shown with the section that changes each (`unbidden setup budget`, `/setup
connections`, pre-filled from compose). A sign-in through the browser came with 0.12.1, through `gh`. Scripted setup needs no `--models` or `--mode`. `docs/INSTALL.md`,
"`unbidden setup`".

## 0.10.2 (2026-11-02): a chat question answered twice, and a start that refuses what cannot run

- A chat turn in the app or the dashboard failed on the second question with `RuntimeError: Event loop is closed`:
  each provider kept one HTTP client for life while every turn ran its own event loop. Now a client belongs to the
  loop that uses it and is closed before that loop ends (`unbidden/brain/providers/clients.py`, `Brain.aclose`).
- `unbidden start` and `/start` first check, without any network call, that the option's model exists here
  (Ollama reachable with the recommended model pulled, or the API key held). If not, nothing starts: exit 4 with
  the one command that fixes it; `--force` starts anyway. Docker absent or a missing GitHub token only warn.

## 0.10.1 (2026-11-02): the mark and the menus

The banner's ring is drawn in braille cells, round and thin, open at the upper right with the dot outside the gap,
as the logo is; the wordmark letterspaced. On the setup screen a choice (local / mixed / api, the mode, a connection
kind) or a confirmation is a menu: arrows or a click, Enter; the default highlighted. Nothing else changes.

## 0.10.0 (2026-11-02): the terminal app

`unbidden` on a terminal (at least 60 columns, `TERM` not `dumb`, no `--json`, `--plain` or `UNBIDDEN_PLAIN`) opens
a full-screen app on Textual 8: the setup assistant inside it the first time, then the live feed of the agent's
records grouped by what it is doing (discovering, investigating, experimenting, proving, deciding, asking,
guarding), a prompt for questions and `/` commands, a status bar (agent, jobs, mode, model option, spend available,
dashboard, age of the last event). The engine is unchanged: the app reads the records and calls the actions that
already existed (start, stop, kill switch, approve, reject, chat). `docs/INSTALL.md`, "A first run". Verified by hand
on macOS arm64 with the built wheel installed by `install.sh` into an empty HOME and driven in a pseudoterminal; CI
unchanged (without a terminal, `unbidden` is the text home screen). Everything below describes 0.9.0 and still holds.

**Status: 0.12.4, experimental candidate.** Not 1.0: the criteria of v1.0 are in `docs/CAMPAIGN-v1.md` and were not
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
