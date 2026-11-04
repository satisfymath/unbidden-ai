# Unbidden

**Intelligence that doesn't wait for instructions.**

Unbidden is a proactive engineering agent you install like a CLI. It lives in a repository, runs the team's
own checks in an offline sandbox, finds improvements it can prove, measures them, and proposes them as pull
requests that carry their evidence. With the autonomy you grant it, it can also merge, deploy, watch
production and roll back. A dashboard and a chat read the same records; neither can make it act.

It runs on Meta models. **Muse Glimmer** runs locally through Ollama and is the only model that ever sees
secrets, logs or production data. **Muse Spark** (Meta Model API) takes the heavy work when the content is
allowed to leave. Private code reaches Spark only after the privacy bridge has renamed it.

Built at the Meta Global AI Developer Hackathon (October 26 – November 4, 2026). Current version: **0.17.0,
experimental candidate** (not 1.0; what that means is in [`docs/RELEASE.md`](docs/RELEASE.md)).

## What it has done on real repositories

| Repository | What Unbidden did on its own | Evidence |
|---|---|---|
| [full-stack-fastapi-template](https://github.com/satisfymath/full-stack-fastapi-template) (fork) | Found that `item.owner_id` leads no index, a gap nothing upstream had reported. Wrote the migration and a workload, measured it, then published, merged and deployed it ([#1](https://github.com/satisfymath/full-stack-fastapi-template/pull/1)) | Lab: `GET /api/v1/items/` median 13.0 → 4.1 ms, Mann-Whitney p = 3.4e-08, CI green 3 rounds per side (L4). Production: 10.5 → 1.7 ms |
| Same fork, outage drill | A release whose health check fails was deployed. Unbidden called the outage in 11 s, rolled back to the last healthy deploy in 15 s with the team's own steps, and placed a hold only a person can release | `unbidden deploys`; D-015 |
| Same fork, investigation | Read-only, local model, four tool calls. It named the commit and line that broke health | Correct; confidence capped at 0.60 because nothing was reproduced (D-016) |
| [Rich](https://github.com/satisfymath/rich) (fork), searched blind | Spark wrote property tests for public functions and found an `IndexError` and a `ZeroDivisionError` in `rich.cells.split_text`. The first is on the line of issue #4239, which Unbidden was never told about; the second appears in no issue. It wrote the fix and proposed it ([#1](https://github.com/satisfymath/rich/pull/1)) | Fails at the base, passes with the fix, no regressions in Rich's suite (L4, 58 s). It also resolves #4239's reproduction |
| A private TypeScript monorepo | Sent code through the bridge with every non-public word renamed and a local outsider review. It analyzed each package the way its CI does | 0 domain words sent. 1,309 false type errors avoided; 857 lint findings outside the CI's scope declined |

Every number above was measured during the event. How it was measured, and what went wrong on the way, is in
[`docs/DECISIONS.md`](docs/DECISIONS.md); every result at the level it reached is in [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

## Install

The full guide, with prerequisites, the walk, what costs tokens and what does not, and the limitations:
[`docs/INSTALL.md`](docs/INSTALL.md). Unbidden installs as one wheel with the dashboard built inside, in its own
environment with its own Python 3.12 (uv). The end user needs no Node and no Python of their own.

**One line** (macOS on Apple Silicon, Linux x86-64; the script is served from [unbidden.cl](https://unbidden.cl) and
downloads the wheel of the latest GitHub release, verified against its `SHA256SUMS`):

```sh
curl -fsSL https://unbidden.cl/install.sh | sh
```

**From local artifacts** (how the installer is tested, and how to install an unreleased build):

```sh
make dist                                   # from a checkout: dist/unbidden_ai-0.17.0-py3-none-any.whl + SHA256SUMS
(cd dist && python3 -m http.server 8777 --bind 127.0.0.1 &)
UNBIDDEN_INSTALL_BASE=http://127.0.0.1:8777 sh install.sh --yes --version 0.17.0
unbidden --version                          # unbidden 0.17.0
```

What the machine provides (each reported by `unbidden doctor` as required or optional for the option you chose):
git; Docker with the buildx and compose plugins (the project's code runs only in the sandbox); Ollama for the
`local` and `mixed` options; a Meta API key for `mixed` and `api`; a GitHub token only to open pull requests.

Then:

```sh
cd your-repo
unbidden              # the app: the setup assistant the first time, then the live feed; --plain for text
unbidden doctor       # what works here, what is required for your option, what is optional
unbidden start --ui   # the agent in the background, serving the dashboard from its own process
unbidden status       # agent pid and log, dashboard URL, kill switch
unbidden stop         # ends the agent cleanly; `unbidden start` resumes interrupted jobs
```

Verified by hand on macOS arm64 only; Linux x86-64 runs in GitHub Actions (CI jobs `check`, `frontend`, `installed`;
CI run [41333127432](https://github.com/satisfymath/unbidden-ai/actions/runs/41333127432) on `2d72ce4`, 2026-11-01: `check`, `frontend`, `installed` and `secrets` all green). `unbidden update` and `unbidden uninstall` keep `~/.unbidden` and every repository's `.unbidden/`.

## Where your code goes

The assistant derives the option from what the machine has (a key, a local model) and says why; `setup models` overrides it:

| Option | Profile | Where calls go | Needs |
|---|---|---|---|
| `local` | `local` | only a model on this machine (Ollama); nothing leaves | Ollama |
| `mixed` | `local-first` | light work local; heavy work whose content may leave goes to Meta's API first, local fallback when the remote fails | Ollama; a Meta key (optional) |
| `api` | `frontier`, local inference and local fallback denied | Meta's API only; a call that may not leave the machine is refused and says why | a Meta key |

Every request is labeled with its most sensitive part:
`instructions < synthetic < public_code < private_code < production_data < secret`. In every option secrets and
production data stay on the machine; private code leaves only renamed by the privacy bridge, or when the mandate says
`private_code_to_frontier: allow`; code counts as public only when GitHub confirms the repository is public. The
egress gate re-checks the label and scans every payload before it leaves, whatever the router decided.
`unbidden route` explains where each task would go without calling any model; `unbidden egress --payload` shows,
byte for byte, everything that left.

## Autonomy

The mode is set by a person and audited; the assistant shows the effective permissions the mandate grants.

```sh
unbidden mode supervised   # asks before a pull request; never merges or deploys
unbidden mode autopilot    # opens proven pull requests on its own; people merge
unbidden drill             # proves rollback works: deploy previous, health green, deploy back
unbidden mode autonomous   # also merges L4 work, deploys with the team's steps, rolls back;
                           # refuses without `operations.deploy_steps` and a passed drill
```

In every mode:
- Only proposals at L4 are merged, pinned to the commit that was measured.
- A merge waits until the previous deploy has been judged.
- A degraded deploy or an outage triggers a rollback and a hold, and only a person can release the hold (`unbidden hold release`).
- `unbidden kill` freezes everything in every process until `unbidden resume`; `unbidden stop` only ends the agent.

## Evidence levels

| Level | Meaning |
|---|---|
| L1 | Reasonable suspicion |
| L2 | Reproduced |
| L3 | Improved in the lab |
| L4 | Functionally validated with the team's own checks |
| L5 | Operational result measured in production, with its confounders listed |
| L6 | Persisted over time |

A claim's confidence is capped by its level. Only L4 and above becomes a pull request by default.

## Dashboard and chat

`unbidden start --ui` serves the dashboard from the agent's own process; `unbidden ui [--open]` opens or reuses one
over the repository's `.unbidden/state.db`, read-only. Opening it, restoring the layout and showing records call no
model. Widgets carry their provenance (source, mode, freshness, completeness); layout and conversation persist in
`~/.unbidden/web/presentation.db`, so closing the browser or stopping the agent loses nothing. Closing the tab stops
nothing; `ui --stop` stops only a dashboard served apart; the one the agent serves ends with `unbidden stop`.

The chat, in the dashboard or as `unbidden chat "..."`, has three intents: **inform** (counts, status, tables,
charts: answered by deterministic rules over the records, no remote call), **analyze** (why, recommend, risk,
summary: one call routed like heavy work, within the mandate's monthly cap, refused with the router's reason when it
may not go anywhere) and **act** (approve, deploy, kill...: always refused and pointed at the CLI or the actions
panel). The same web workspace also serves a `--demo` (fixtures) and published records (`--record`, historical),
neither of which runs the agent.

## Commands

| Command | What it does |
|---|---|
| `unbidden` | the setup assistant the first time, the home screen afterwards (state, agent, blocks, next action) |
| `setup` | three questions at most: the model key when none is found, how much it may do on its own, apply; the rest is found (repository, GitHub access, scope, compose connections, machine) or kept at a default, changed by name (`setup budget`, `setup connections`); `--non-interactive` with flags |
| `doctor`, `status`, `map` | check the machine for the chosen option; agent, dashboard and kill switch; what Unbidden knows and cannot see |
| `start`, `stop`, `watch` | the agent in the background (`--ui` serves the dashboard), ended cleanly; or in the foreground of this terminal |
| `ui`, `chat` | open or reuse the dashboard (`--stop` ends one served apart); the chat from the terminal |
| `scan`, `inbox`, `show`, `try`, `why`, `decide` | find opportunities, inspect them, run an experiment, see every decision and payload |
| `review`, `approve`, `reject` | decide on waiting proposals |
| `mode`, `drill`, `deploy`, `deploys`, `hold`, `kill`, `resume` | autonomy and operations |
| `health`, `errors`, `probe`, `investigate`, `forge`, `logs` | services against their baseline; recurring errors; property-based crash search; a failure between two versions; self-built capabilities |
| `models`, `route`, `spend`, `egress` | model option, routing explanation, the machine ledger, outbound audit |
| `update`, `uninstall` | the installer from inside the tool; data stays unless `--purge --yes` |

Most commands accept `--json`; the ones that only act (`approve`, `review`, `reject`, `kill`, `resume`, `watch`,
`probe`, `approve-writes`) do not. One executor per workspace: a second `start` answers "already running", and the
commands that execute jobs refuse with exit 2 while another process owns the workspace.

## Documentation

- [`docs/INSTALL.md`](docs/INSTALL.md): the install guide, the walk, prerequisites, tokens, persistence, limitations.
- [`docs/RELEASE.md`](docs/RELEASE.md): the current candidate, what it supports and what it does not.
- [`docs/EVIDENCE.md`](docs/EVIDENCE.md): every result at the level it reached, the cross-repository benchmark and its
  frozen holdout, the negatives, and the cost.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the pieces fit, and what is guaranteed and what is not.
- [`docs/DECISIONS.md`](docs/DECISIONS.md): every design decision, with the measurement behind it.
- [`docs/bench/`](docs/bench): benchmarks and calibrations.

## Development

```sh
make setup
make check   # ruff, pyright, pytest
make dist    # the wheel with the web workspace inside, and SHA256SUMS
```

Apache-2.0.
