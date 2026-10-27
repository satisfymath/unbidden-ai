# Unbidden

**Intelligence that doesn't wait for instructions.**

Unbidden is a proactive engineering agent you install like a CLI. It lives in a repository, runs the team's
own checks in an offline sandbox, finds improvements it can prove, measures them, and proposes them as pull
requests that carry their evidence. With the autonomy you grant it, it can also merge, deploy, watch
production and roll back.

It runs on Meta models. **Muse Glimmer** runs locally through Ollama and is the only model that ever sees
secrets, logs or production data. **Muse Spark** (Meta Model API) takes the heavy work when the content is
allowed to leave. Private code reaches Spark only after the privacy bridge has renamed it.

Built at the Meta Global AI Developer Hackathon (October 26 – November 4, 2026).

## What it has done on real repositories

| Repository | What Unbidden did on its own | Evidence |
|---|---|---|
| [full-stack-fastapi-template](https://github.com/satisfymath/full-stack-fastapi-template) (fork) | Found that `item.owner_id` leads no index, a gap nothing upstream had reported. Wrote the migration and a workload, measured it, then published, merged and deployed it ([#1](https://github.com/satisfymath/full-stack-fastapi-template/pull/1)) | Lab: `GET /api/v1/items/` median 13.0 → 4.1 ms, Mann-Whitney p = 3.4e-08, CI green 3 rounds per side (L4). Production: 10.5 → 1.7 ms |
| Same fork, outage drill | A release whose health check fails was deployed. Unbidden called the outage in 11 s, rolled back to the last healthy deploy in 15 s with the team's own steps, and placed a hold only a person can release | `unbidden deploys`; D-015 |
| Same fork, investigation | Read-only, local model, four tool calls. It named the commit and line that broke health | Correct; confidence capped at 0.60 because nothing was reproduced (D-016) |
| [Rich](https://github.com/satisfymath/rich) (fork), searched blind | Spark wrote property tests for public functions and found an `IndexError` and a `ZeroDivisionError` in `rich.cells.split_text`. The first is on the line of issue #4239, which Unbidden was never told about; the second appears in no issue. It wrote the fix and proposed it ([#1](https://github.com/satisfymath/rich/pull/1)) | Fails at the base, passes with the fix, no regressions in Rich's suite (L4, 58 s). It also resolves #4239's reproduction |
| A private TypeScript monorepo | Sent code through the bridge with every non-public word renamed and a local outsider review. It analyzed each package the way its CI does | 0 domain words sent. 1,309 false type errors avoided; 857 lint findings outside the CI's scope declined |

Every number above was measured during the event. How it was measured, and what went wrong on the way, is in
[`docs/DECISIONS.md`](docs/DECISIONS.md).

## Install

Requirements:
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker
- [Ollama](https://ollama.com)
- a Meta Model API key
- optionally, a GitHub token to publish pull requests

```sh
uv tool install git+https://github.com/satisfymath/unbidden-ai
echo 'MODEL_API_KEY=...' >> ~/.unbidden/.env   # never committed, never sent anywhere but api.meta.ai
cd your-repo
unbidden init         # writes .unbidden/mandate.yaml: what it may do on its own (supervised by default)
unbidden doctor --fix # checks Docker, the API, GitHub; picks and pulls the local model this machine can run
unbidden scan         # runs the repository's own checks in the sandbox
unbidden inbox        # opportunities, most proven first
unbidden watch        # keep working in the background
```

`unbidden doctor` picks the local model to fit the machine (D-020):

| Memory | Local model |
|---|---|
| ≥ 42 GB | Glimmer 30B 8-bit |
| ≥ 24 GB | Glimmer 30B 4-bit |
| ≥ 6.5 GB | Llama 3.1 8B |
| ≥ 3 GB | Llama 3.2 3B |

## Where your code goes

Every request is labeled with its most sensitive part:

`instructions < synthetic < public_code < private_code < production_data < secret`

How each label is routed depends on the profile:

| Label | `local` | `local-first` (default) | `frontier` |
|---|---|---|---|
| secret, production data | local | local | local |
| private code | local | renamed by the bridge, then Spark | Spark only if `private_code_to_frontier: allow`, else bridge |
| public code, synthetic | local | Spark for heavy tasks, local fallback | Spark |

- **Public versus private.** Code counts as public only when GitHub confirms the repository is public. If that cannot be confirmed, the code is treated as private.
- **Final check.** The egress gate re-checks the label and scans every payload before it leaves, whatever the router decided.
- **Inspecting decisions.** `unbidden route` explains, without calling any model, where each task would go and why. `unbidden egress --payload` shows, byte for byte, everything that left the machine.

## Autonomy

The mode is set by a person and audited:

```sh
unbidden mode supervised   # proposals wait for `unbidden review`
unbidden mode autopilot    # opens proven pull requests on its own
unbidden drill             # proves rollback works: deploy previous, health green, deploy back
unbidden mode autonomous   # also merges and deploys; refuses to switch on without a passed drill
```

In every mode:
- Only proposals at L4 are merged, pinned to the commit that was measured.
- A merge waits until the previous deploy has been judged.
- A degraded deploy or an outage triggers a rollback and a hold, and only a person can release the hold (`unbidden hold release`).
- `unbidden kill` stops everything.

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

## Commands

| Command | What it does |
|---|---|
| `init`, `doctor`, `status`, `map` | Set up, check the machine, see what Unbidden knows and cannot see |
| `scan`, `inbox`, `show`, `try`, `why` | Find opportunities, inspect them, run an experiment, see every decision and payload behind it |
| `review`, `approve`, `reject` | Decide on waiting proposals |
| `watch` | The background agent |
| `mode`, `drill`, `deploys`, `hold`, `kill`, `resume` | Autonomy and operations |
| `probe` | Property-based crash search on a Python package |
| `investigate` | Read-only explanation of a failure between two versions |
| `forge`, `logs` | Capabilities Unbidden builds for itself (log adapters), judged by an oracle before use |
| `models`, `route`, `egress` | Model profile, routing explanation, outbound audit |

Every command accepts `--json`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the pieces fit, and what is guaranteed and what is not.
- [`docs/DECISIONS.md`](docs/DECISIONS.md): every design decision, with the measurement behind it.
- [`docs/bench/`](docs/bench): benchmarks and calibrations.

## Development

```sh
make setup
make check   # ruff, pyright, pytest
```

Apache-2.0.
