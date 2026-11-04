<div align="center">

<a href="https://unbidden.cl">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/unbidden-mark-white.png">
    <img src="docs/brand/unbidden-mark-black.png" alt="Unbidden logo: an open ring with a separate dot" width="112">
  </picture>
</a>

# Unbidden

**Intelligence that doesn't wait for instructions.**

[![CI](https://github.com/satisfymath/unbidden-ai/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/satisfymath/unbidden-ai/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/satisfymath/unbidden-ai?color=444)](https://github.com/satisfymath/unbidden-ai/releases/latest)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-444)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-444)](pyproject.toml)

[Website](https://unbidden.cl) · [Install guide](docs/INSTALL.md) · [Evidence](docs/EVIDENCE.md) · [Architecture](docs/ARCHITECTURE.md) · [Commands](docs/CLI.md)

</div>

Unbidden is a proactive engineering agent you install like a CLI. It lives in a repository, runs the team's
own checks in an offline sandbox, finds improvements it can prove, measures them, and proposes them as pull
requests that carry their evidence. With the autonomy you grant it, it can also merge, deploy, watch
production and roll back. A dashboard and a chat read the same records; neither can make it act.

It runs on Meta models. **Muse Glimmer** runs locally through Ollama and is the only model that ever sees
secrets, logs or production data. **Muse Spark** (Meta Model API) takes the heavy work when the content is
allowed to leave. Private code reaches Spark only after the privacy bridge has renamed it.

> [!NOTE]
> Unbidden is an **experimental candidate, not 1.0**. [`docs/RELEASE.md`](docs/RELEASE.md) says what that means and
> what each release changed. Built at the Meta Global AI Developer Hackathon (October 26 – November 4, 2026).

## Quick start

```sh
curl -fsSL https://unbidden.cl/install.sh | sh

cd your-repo
unbidden              # the app: the setup assistant the first time, then the live feed; --plain for text
unbidden doctor       # what works here, what is required for your option, what is optional
unbidden start --ui   # the agent in the background, serving the dashboard from its own process
unbidden status       # agent pid and log, dashboard URL, kill switch
unbidden stop         # ends the agent cleanly; `unbidden start` resumes interrupted jobs
```

The script downloads the wheel of the latest [GitHub release](https://github.com/satisfymath/unbidden-ai/releases/latest),
verifies it against its `SHA256SUMS` and installs it in its own environment with its own Python 3.12 (uv). You need no
Node and no Python of your own; it never uses `sudo`.

What the machine provides (each reported by `unbidden doctor` as required or optional for the option you chose):
git; Docker with the buildx and compose plugins (the project's code runs only in the sandbox); Ollama for the
`local` and `mixed` options; a Meta API key for `mixed` and `api`; a GitHub token only to open pull requests.

Prerequisites, what costs tokens, limitations and installing an unreleased build:
[`docs/INSTALL.md`](docs/INSTALL.md). `unbidden update` and `unbidden uninstall` keep `~/.unbidden` and every
repository's `.unbidden/`.

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
byte for byte, everything that left. `unbidden export` writes the workspace's evidence (records, the redacted transcript of every
model call, spend, a manifest of sha256s) as files to publish, refusing if its secret scan finds anything
([INSTALL.md](docs/INSTALL.md#evidence-unbidden-export)).

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

## Platforms

| Platform | Status |
|---|---|
| macOS on Apple Silicon | Supported. The one-line install was run by hand on two machines |
| Linux x86-64 (glibc 2.28 or later) | Supported. Installed in CI on every push and by hand on Fedora |
| macOS on Intel, Linux arm64, Windows, musl | Untested; the installer stops with a message |

## Documentation

| Document | What it holds |
|---|---|
| [`docs/INSTALL.md`](docs/INSTALL.md) | The install guide, the walk, prerequisites, tokens, persistence, limitations |
| [`docs/CLI.md`](docs/CLI.md) | Every command, the dashboard and the chat |
| [`docs/RELEASE.md`](docs/RELEASE.md) | The current candidate, what it supports and what it does not, and the release notes |
| [`docs/EVIDENCE.md`](docs/EVIDENCE.md) | Every result at the level it reached, the cross-repository benchmark and its frozen holdout, the negatives, the cost |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the pieces fit, what is guaranteed and what is not |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Every design decision, with the measurement behind it |
| [`docs/bench/`](docs/bench) | Benchmarks and calibrations |

## Contributing

Issues and pull requests are welcome; start with [`CONTRIBUTING.md`](CONTRIBUTING.md). To report a vulnerability, follow
[`SECURITY.md`](SECURITY.md) instead of opening an issue. Everyone taking part follows the
[Code of Conduct](CODE_OF_CONDUCT.md).

```sh
make setup
make check   # ruff, pyright, pytest
make dist    # the wheel with the web workspace inside, and SHA256SUMS
```

## License

[Apache-2.0](LICENSE) © 2026 David Astudillo. See [`NOTICE`](NOTICE).
