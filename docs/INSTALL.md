# Installing Unbidden

This is the one install guide. Unbidden 0.9.0 (experimental candidate; not 1.0) ships as one Python wheel with the
web workspace already built inside. The installer puts it in its own environment with its own Python 3.12 through
[uv](https://docs.astral.sh/uv/); nothing else on the machine changes. The end user needs no Node and no Python of
their own.

Verified by hand on macOS on Apple Silicon (arm64) only. Linux x86-64 runs in GitHub Actions (CI jobs `check`,
`frontend`, `installed`; CI run [41333127432](https://github.com/satisfymath/unbidden-ai/actions/runs/41333127432) on `2d72ce4`, 2026-11-01: `check`, `frontend`, `installed` and `secrets` all green).

## One line

> **Available once the first release is published.** There is no release on GitHub yet, so this line fails today with
> "no published release found". Until then use the [local-artifact procedure](#installing-from-local-artifacts-today)
> below, which is also how the installer is tested.

```sh
curl -LsSf https://github.com/satisfymath/unbidden-ai/releases/latest/download/install.sh | sh
```

What it does, in order: detects the platform; finds `uv` or asks to install it with its official installer; downloads
`unbidden_ai-X.Y.Z-py3-none-any.whl` and `SHA256SUMS` from the release; verifies the sha256 and refuses on a mismatch;
runs `uv tool install --python 3.12 --reinstall` on the wheel; tells you if the tool directory is not on your PATH.
It never uses `sudo` and never prints a secret.

## Installing from local artifacts (today)

Build the files from a checkout (`make dist`: builds the web workspace with Node 24, then `uv build` and
`SHA256SUMS`), serve the directory, point the installer at it. `http://` is accepted only for loopback addresses.

```sh
make dist                                   # dist/unbidden_ai-0.9.0-py3-none-any.whl (~950 KB), .tar.gz, SHA256SUMS
(cd dist && python3 -m http.server 8777 --bind 127.0.0.1 &)
UNBIDDEN_INSTALL_BASE=http://127.0.0.1:8777 sh install.sh --yes --version 0.9.0
unbidden --version                          # unbidden 0.9.0
```

Only the person building the wheel needs Node; the wheel carries the built assets, so the installed tool serves the
dashboard without it. To try the install without touching your real environment, give the installer a throwaway
home:

```sh
export HOME=$(mktemp -d) UV_TOOL_DIR=$HOME/tools UV_TOOL_BIN_DIR=$HOME/bin
```

Environment the installer reads: `UNBIDDEN_VERSION` (same as `--version`), `UNBIDDEN_INSTALL_BASE` (where the wheel
and `SHA256SUMS` live; default: the GitHub release of that version), `UNBIDDEN_REPO` (default
`satisfymath/unbidden-ai`), and uv's own `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_INSTALL_DIR`.

Exit codes: 2 bad usage, 3 unsupported platform, 4 uv declined, 5 no release found, 6 download failed, 7 wheel not
listed in `SHA256SUMS`, 8 checksum mismatch, 9 the installed command reports another version.

## Prerequisites, in three groups

### 1. What Unbidden installs

Only itself: a uv tool with its own Python 3.12 (uv downloads an interpreter if none is managed, ~30 MB, once) and its
dependencies (~136 MB with scipy, numpy, pydantic, psycopg). Nothing else is installed, no service is registered,
nothing starts at boot. Installing, `unbidden --version`, `unbidden setup` and `unbidden doctor` need no Docker,
Ollama, key or token.

### 2. What the machine provides

Each function has one dependency; `unbidden doctor` reports every one of them as **required** or **optional** for the
model option the mandate chose (`unbidden/setup/requirements.py`), and exits 1 only when a required one fails.

| The machine provides | Needed for | Required when |
|---|---|---|
| `git` | the repository Unbidden lives in | always |
| Docker, with the **buildx** plugin and the **compose** plugin | the sandbox (the project's checks, experiments, probes) builds images with `docker build --progress=plain`, which needs BuildKit/buildx; the world map runs `docker compose ps` | the mandate allows observing or experimenting (every option by default). `doctor` checks the daemon (`docker info`) and both plugins (`docker buildx version`, `docker compose version`), required whenever Docker is |
| [Ollama](https://ollama.com) with a model that fits the machine | local inference | options `local` and `mixed`; not used in `api` |
| a Meta API key (`MODEL_API_KEY`) | remote inference | option `api` (required) and `mixed` (optional: heavy work goes local without it) |
| a GitHub token (`GITHUB_TOKEN`) | opening pull requests | only when the mode opens them; without it proposals stay local branches |

Credentials are saved by `unbidden setup` in `~/.unbidden/.env` (mode 600), referenced by name; never written to the
repository, the mandate, the logs or the JSON output.

Local model sizes, as `unbidden/brain/hardware.py` recommends them (weights plus a 32k-token cache; the machine keeps
up to 10 GB for Docker and the system). The assistant shows the size before offering the download and never downloads
without confirmation (`setup --pull-model` or `doctor --fix` do it on request):

| Model | Loaded | Where |
|---|---|---|
| `muse-glimmer:30b-mxfp8-dflash` / `muse-glimmer:30b-q8_0` | 42 GB / 38 GB | Apple Silicon / GGUF |
| `muse-glimmer:30b-mlx` / `muse-glimmer:30b-q4_K_M` | 24 GB / 22 GB | Apple Silicon / GGUF |
| `llama3.1:8b` | 6.5 GB | both |
| `llama3.2:3b` | 3 GB | both |

### 3. Where the project's code runs

The repository you point Unbidden at is never executed on your machine directly: builds, checks and experiments run
in the sandbox (`unbidden/sandbox/provision.py`), offline, with network only to the mandate's package registries while
the image is built. That is why Docker is the one dependency of every function that touches code.

## The walk

```sh
cd your-repo
unbidden                     # first time: the setup assistant; afterwards: the home screen
unbidden doctor              # what works here, and what is required or optional for the option you chose
unbidden start --ui          # the agent in the background, serving the dashboard from its own process
unbidden status              # agent pid, log, whether the last run ended badly; dashboard URL; kill switch
unbidden ui --open           # open (or reuse) the dashboard in the browser
unbidden chat "how many opportunities are open?"
unbidden stop                # ends the agent cleanly (and the dashboard it served)
unbidden start               # resumes: interrupted jobs return to the queue first
```

### `unbidden` and `unbidden setup`

The first `unbidden` inside a repository without `.unbidden/` opens the assistant (`unbidden setup`; every sentence
it says is in `unbidden/setup/text.py`). It calls no model. Sections, in order: project (repository, branch, head,
whether the stack is inside what this version supports), priorities, models (the three options below), credentials,
autonomy and scope, connections (optional), budget, dashboard. It shows the diff of `.unbidden/mandate.yaml` before
writing, records `MANDATE_CHANGED`, and can be interrupted: answered sections are kept in `.unbidden/setup.json`,
`unbidden setup <section>` redoes one, `setup --all` redoes all, `setup --show` prints the effective configuration.

Without a terminal:

```sh
unbidden setup --non-interactive --models local|mixed|api --mode supervised|autopilot|autonomous \
  [--mode-fallback supervised|autopilot] --budget <USD> --dashboard now|later|never \
  [--model-key-stdin] [--github-token-stdin] [--private-code deny|allow] [--priorities a,b] \
  [--pull-model] [--probe] --yes [--json]
```

`--yes` applies (the diff is shown either way); `--model-key-stdin` reads the key from the first stdin line and
`--github-token-stdin` the token from the next, so neither appears in argv, the shell history or the output.
Afterwards `unbidden` alone is the home screen: repository, head, mode, profile, whether the agent runs (pid, since
when, log) or ended without `stop`, the kill switch, opportunities, last scan, spend on this machine, and the next
command.

### `unbidden start`, `stop`, `status`

`start` runs `unbidden watch` in its own session, detached from the terminal, with its output in
`.unbidden/logs/agent.log`; closing the terminal does not stop it. With `--ui [--port 8765]` the same process also
serves the dashboard (`unbidden/web/embed.py`: one store, one egress record, one monthly cap check); `--interval S`
is the pause between looks at HEAD. `unbidden watch` is the same agent in the foreground, and ends with the terminal
(it says so when it starts).

One executor per workspace (`unbidden/daemon/owner.py`): a kernel lock on `.unbidden/engine.lock`. A second `start`
answers `already running: pid N`; `scan`, `try`, `deploy`, `drill`, `map`, `forge build|stats`, `probe` and
`investigate` refuse with exit 2 while another process owns the workspace. Short decisions (`approve`, `reject`,
`mode`, `kill`, `resume`) never take the lock: the loop reads them on its next cycle.

`stop` sends SIGTERM and waits for the lock: the job in progress returns to the queue without spending an attempt,
the process ends (SIGKILL past `--timeout`, default 60 s). `stop` never touches the kill switch. If the agent died
without `stop` (a crash, `kill -9`, a closed laptop), `status` says `stale` and the next `start` resumes the
interrupted jobs (`Store.requeue_running`). Nothing survives a reboot: no launchd, systemd or crontab entry is
written; after a reboot the agent is not running and `status` says so.

`unbidden kill` freezes everything, in every process, by writing `.unbidden/KILL`; the freeze persists until
`unbidden resume`, and `start` after `kill` starts a process that waits. `kill --stop` also ends the agent.

### `unbidden ui` and `unbidden chat`

`ui` opens the repository's dashboard over its own `.unbidden/state.db`, read-only, or reuses the one that is alive
(`.unbidden/ui.json`, mode 600, holds the URL with its session token; the token is never in argv). `--open` opens the
browser; `--port` is the preferred port (the next free one is taken if busy). `ui --stop` stops only a dashboard
served apart, never the agent; the dashboard served by the agent (`start --ui`) ends with `unbidden stop`. Closing the
browser tab stops nothing.

`chat "..."` is the dashboard's chat from the terminal, over the same records and the same route; without a message
it reads stdin or prompts. It informs and analyzes, never acts: approve, reject, deploy, roll back, merge, freeze and
resume are refused and pointed at the CLI command or the dashboard's actions panel, which go through the project's
effective permissions.

## The three model options

The assistant asks which option explicitly; it may recommend one (and say why), it never chooses. Every option is a
`models` section of the mandate (`unbidden/guardian/mandate_edit.py`, `MODEL_OPTIONS`).

| Option | Mandate | Where calls go | Needs |
|---|---|---|---|
| `local` | `profile: local` | only a model on this machine (Ollama); nothing leaves. Heavy work is slower and smaller | Ollama and a model that fits |
| `mixed` | `profile: local-first` (`local_fallback: allow`) | light work local; heavy work whose content may leave goes to Meta's API first and falls back to the local model when the remote call fails | Ollama and a model; a Meta key (optional: without it heavy work goes local) |
| `api` | `profile: frontier`, `local_inference: deny`, `local_fallback: deny` | Meta's API only; no local model is needed or used. A call that may not leave the machine is refused and says why | a Meta key |

In every option secrets and production data never leave the machine; private code leaves only renamed by the privacy
bridge or when `private_code_to_frontier: allow` (the assistant asks; `deny` keeps it behind the bridge); the egress
gate re-checks every payload (`unbidden egress --payload` shows what left, byte for byte). `unbidden models` and
`unbidden route` change and explain the routing afterwards.

## Autonomy and effective permissions

A mode sets what reaches GitHub and production; the other permissions are granted on their own and never inherited
from another project, and a credential's own powers never widen the mandate.

| Mode | What it does |
|---|---|
| `supervised` | prepares everything, asks before a pull request; never merges or deploys |
| `autopilot` | opens pull requests on its own for proven work; people merge |
| `autonomous` | also merges L4 work, deploys with the team's steps and rolls back |

`autonomous` requires `operations.deploy_steps` in the mandate and a passed rollback drill (`unbidden drill`). Without
both, the assistant and `unbidden mode autonomous` refuse and list what is missing; nothing is chosen for you: in the
assistant the follow-up question has no default, and `setup --non-interactive --mode autonomous` needs
`--mode-fallback supervised|autopilot` or ends with exit 4, the previous mandate intact.

The assistant ends the autonomy section with the **effective permissions** table, computed by the `PolicyEngine`
over the written mandate (`unbidden/setup/effective.py`): observe the repository, its CI and running services; run
experiments in the offline sandbox; install dependencies while building; send synthetic or public content to remote
models; use capabilities it built for itself; open pull requests; merge pull requests; deploy with the team's steps;
roll back a deploy; write through connections. Each row says `allow`, `require_approval` or `deny` and the rule
behind it.

## What consumes tokens, and what does not

| Action | Remote model calls |
|---|---|
| the installer, `unbidden --version`, `update`, `uninstall` | none |
| `unbidden setup` | none. `--probe` (or the assistant's question) runs one paid inference call to confirm the key, after showing its worst cost at list price; the configuration is saved either way |
| `unbidden` (home), `status`, `doctor`, `route`, `spend`, `egress` | none |
| `unbidden ui`: opening, restoring the layout, showing records, widgets created by the rules | none |
| `chat`, informing (counts, status, tables, charts, explain a block, change a chart, compare two runs, undo) | none remote: the deterministic rules answer; when the option allows local inference the local model may plan the same tool calls (`chat.inform` is light and local-only) |
| `chat`, analyzing (why, recommend, risk, summary) | one call without tools over a bounded digest of the records, routed like heavy work: Meta's API in `api`, and in `mixed` when the digest may leave; the local model in `local`; refused with the router's reason otherwise |
| the agent's cycle (`start`, `watch`, `scan`, `try`, `probe`) | calls for its own work (research, labs, planning), within the mandate's `maximum_monthly_spend_usd` and the machine ledger |

The monthly cap is one for every process of a workspace: the dashboard and the engine share the ledger
(`SpendLedger.workspace_month_spend`). Every remote call reserves its worst cost in `~/.unbidden/spend.db` before it
is sent and settles after; `unbidden spend` shows the cap a person entered, what was spent and the envelopes. The
ledger is never reset by an install, update or uninstall.

## The dashboard: persistence and provenance

Layout and conversation live in `~/.unbidden/web/presentation.db`, keyed by source. Closing the browser, stopping the
dashboard (`ui --stop`) or the agent (`stop`), and opening again with `unbidden ui` or `start --ui` shows the same
widgets and messages (verified: the same 2 widgets and 8 messages after `stop` and a reopen). Every widget carries its
provenance: source, mode (`live`, `historical`, `demo`), freshness and completeness, so an empty table says the record
has no rows rather than looking like a result.

### Demo, historical, live

The same web workspace serves three kinds of source (`unbidden/web/sources.py`):

| Mode | How | What it is |
|---|---|---|
| `demo` | `python -m unbidden.web --demo` | fixtures built through the engine's contracts; every event marked demo |
| `historical` | `python -m unbidden.web --record <dir or json>` | a published record (`docs/bench/...`) read-only, with the record's own times; freshness `historical` |
| `live` | `unbidden ui`, `start --ui`, or `python -m unbidden.web --workspace <repo>` | the repository's own `.unbidden/state.db`, read-only; events stream as they happen |

Demo and historical never run the agent and never write. Actions (kill, resume, approve, reject, approve writes) are
real on live sources only; deploy and rollback name the CLI command instead of running.

## Update, rollback, uninstall

```sh
unbidden update                     # the latest published release (none yet: see "One line")
unbidden update --version 0.9.0     # a fixed version: also how you roll back after a failed update
unbidden uninstall                  # shows what would happen
unbidden uninstall --yes            # uv tool uninstall unbidden-ai; data stays
unbidden uninstall --purge --yes    # also deletes ~/.unbidden and this repository's .unbidden/ (listed first)
```

`update` runs the same `install.sh` that is shipped inside the package (`unbidden/distribution/install.sh`; a test
keeps the two files identical), so the checksum gate and the Python 3.12 pin are identical. The installer's own flags
do the same job: `sh install.sh --version <previous>` and `sh install.sh --uninstall --yes`.

**Data kept** by an install, update or plain uninstall: `~/.unbidden` (the shared `.env` with credentials, the spend
ledger `spend.db`, `budget.yaml`, `web/presentation.db`) and `.unbidden/` in every repository (mandate, store,
records, logs). Only `--purge --yes` removes them.

## PATH

`uv tool install` puts the `unbidden` executable in uv's tool bin directory (`uv tool dir --bin`, usually
`~/.local/bin`). If that directory is not on your PATH the installer prints the exact line; or let uv do it with
`uv tool update-shell`.

| Shell | Line |
|---|---|
| zsh | `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc` |
| bash | `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc` |
| fish | `fish_add_path ~/.local/bin` |

## Platform support

| Platform | Status |
|---|---|
| macOS on Apple Silicon (arm64) | verified by hand (2026-11-01): install from local artifacts into an empty HOME, `--version`, setup (option `api`), doctor, the agent with its dashboard on a real repository, chat, stop and reopen, a second start refused, `kill -9` recovered, uninstall keeping the data |
| Linux x86-64, glibc >= 2.28 | the GitHub Actions `ubuntu-latest` runner is the authoritative check: CI job `installed` (wheel, installer into an empty HOME, setup `api`, doctor, start/status/stop, ui and chat by rules, uninstall) and `release.yml`'s `smoke-linux-x86_64` (manual). Not verified by hand. Results: green on run 41333127432 (`2d72ce4`, 2026-11-01); see `docs/RELEASE.md`, "CI on Linux x86-64" |
| macOS on Intel, Linux arm64, Windows, musl | untested; the installer stops with a message. A source install with `uv` may work |

The wheel is pure Python; the native pieces (scipy, numpy, pydantic-core, google-re2, psycopg-binary) come from PyPI
as prebuilt wheels for those two platforms, which is what the support table reflects. An x86-64 VM on Apple Silicon
runs under emulation and is not counted as a Linux test.

## What each test reused from the host

The validation of 2026-11-01 (macOS arm64, fork `satisfymath/rich` at `9d8f9a372cc5`, option `api`, mode
`supervised`, monthly cap US$1.5) ran the installed tool from an empty HOME, with these exceptions, stated so that the
walk is not read as a stranger's machine:

- **The real spend ledger**: `UNBIDDEN_HOME=/Users/david/.unbidden`, so every paid call counted against the real
  cap, in the envelope `s11-product` (`UNBIDDEN_RUN=s11-validation`).
- **The machine's Meta key**, read from the real `~/.unbidden/.env` and passed to `setup --model-key-stdin` on stdin;
  it was never shown and setup wrote it to the empty HOME's credentials file (mode 600).
- **`DOCKER_CONFIG=/Users/david/.docker`**, because an empty HOME has no Docker CLI plugins. The first attempt
  without it recorded two `compatibility` blocks (`unknown flag: --progress`: no buildx); they stay in the record as
  they happened. The restart with it built the image and the project's checks passed.

Everything else was the empty HOME: `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, the installed tool, the credentials file
written by setup.

What happened: project checks passed (981 collected, 0 failed); a robustness probe with 3 calls to Meta's API found 1
property violation, kept for a person (L1); 14 events, 0 opportunities (no improvement was needed to validate the
walk); the dashboard served by the agent showed those events; one chat analysis call (US$0.0051) cited the record's
counts and the two Docker blocks; 2 widgets created by rules with provenance `live:rich-s11`; `stop` and a reopen
kept them; a second `start` was refused; `kill -9` of the agent left a stale lock and the next `start` resumed 1
interrupted job; total spend US$0.0438. Details: `docs/PRODUCT-ONBOARDING-PLAN.md`, "Validación real acotada".

## Known limitations

- **No public release yet.** The one-line install does not work until the first release is published; `unbidden
  update` without `--version` reports the same.
- **Linux not verified by hand**: GitHub Actions is the only Linux evidence (CI run [41333127432](https://github.com/satisfymath/unbidden-ai/actions/runs/41333127432) on `2d72ce4`, 2026-11-01: `check`, `frontend`, `installed` and `secrets` all green; what
  the `installed` job does and does not cover is in `docs/RELEASE.md`, "CI on Linux x86-64").
- `doctor` checks the daemon and the buildx and compose plugins, each explained; without buildx a cycle records a
  `compatibility` block on the first build instead of work (seen on 2026-11-01 with an empty HOME).
- A dashboard served apart (`unbidden ui`) keeps its own model runs and egress in `~/.unbidden/web/<source>-state.db`;
  the agent's are in the repository's `.unbidden/state.db`. `unbidden egress` lists both, each row with its origin
  (`engine` or `dashboard apart`); `unbidden spend` always counted both (one machine ledger).
- Two workspaces with the same repository name share a monthly cap (the ledger keys spend by workspace name).
- `unbidden ui` has no `--state-dir`: the canvas and the conversation always live in `~/.unbidden/web`
  (`python -m unbidden.web --state-dir` has one).
- The chat's deterministic repertoire is the rules' list: status, tables, charts, explain a block, compare two runs,
  change a chart, undo. Everything else needs a model, and in option `api` that is a remote call or a refusal with
  its reason.
- The product walk has no recorded demo yet; `demo/autonomous.sh` is the older CLI demo on marshmallow and runs from
  a checkout with `uv run`, not from the installed tool.
