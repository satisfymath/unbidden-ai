# Commands, dashboard and chat

The reference for the `unbidden` command. To install it, see [`INSTALL.md`](INSTALL.md); for the autonomy modes and the evidence levels, see the [README](../README.md#autonomy).

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
