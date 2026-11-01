# Base, isolation and files

Branch `feat/61-adaptive-workspace`, worktree `/Users/david/unbidden-ai-fe`, cut from the engine's last **published**
commit on `origin/feat/60-experiments`:

- **Base SHA: `1a9093c`** (`feat(cli): doctor diagnoses the repository's scope`). `eae3211` existed locally on that
  branch at the time but was not on origin, so it was not used.
- Verified on 2026-10-31. The engine session was running `bench.revalidate_v4` on `~/mealie` from
  `~/unbidden-ai-s10-f9bc751` writing to `~/unbidden-ai-pr1`; none of those checkouts, databases, Docker resources or
  processes are touched by this branch.

## Rules this branch keeps

- Own Python environment (`uv sync` in this worktree), own Node modules (`frontend/node_modules`), own port (8765 by
  default, checked free at start; never kills what holds a port).
- No benchmark, no `bench.*`, no heavy run on the host. Agent runs, when needed, only in the development workspace
  below.
- No update of the base during a test in progress; new engine commits are taken at explicit checkpoints with a clean
  tree and a compatibility review (`SOURCES.md` lists what the reader depends on).
- Commits on this branch may be pushed to `origin` (satisfymath). No pull request, release or external deploy.

## Files owned by this branch

| Path | What |
|---|---|
| `frontend/` | the web application (React + TypeScript + Vite); `frontend/tests/unit` (vitest), `frontend/tests/e2e` and `frontend/playwright.config.ts` (Playwright) |
| `unbidden/web/` | the local server, the read-only adapter, presentation store, chat planner, sources |
| `tests/web/` | integration tests of the server and the adapters |
| `docs/frontend/` | this documentation |
| `Makefile` | two additive targets (`web`, `web-build`) |
| `.gitignore` | built assets and node modules |

Shared files deliberately **not** modified: `daemon/cycle.py`, `lab/*`, `director/goals.py`, `store/sqlite.py`,
`brain/tasks.py`, `cli.py`, `PLAN.md`, `CAMPAIGN-v1.md`, `uv.lock`, `pyproject.toml`.

Integration points that would need a small shared change later (proposed, not done here):

1. `cli.py`: an `unbidden ui` command that calls `unbidden.web.main()` (one import, one `command(...)` line).
2. `brain/tasks.py`: a `web.chat` entry if the chat should ever be served by a remote model. Without it the engine's
   own rule applies: an unknown purpose is light and local-only, which is what this branch relies on.
3. `pyproject.toml`: include `unbidden/web/static/**` in the wheel once a built distribution is shipped.

## Commits on this branch

`243a9e8` docs · `7d7b49e` server and adapters · `0475fb6` frontend · `081f7e2` selection fix, composer, e2e green ·
then the closing commit of 2026-10-31. Engine checks at the closing commit: ruff, pyright and 806 unit tests pass
(`bench/revalidate_v4.py` was already unformatted at the base; untouched).

## Development workspace

`~/unbidden-fe-dev/sample` is a git repository initialised with `unbidden init` whose `.unbidden/state.db` is written
only by this branch's tools (`python -m unbidden.web.devseed`). It is the only workspace the web server is pointed at
in *live* mode during development, and the only one actions are tried against. The evaluation workspaces
(`~/mealie`, `~/opentelemetry-demo`, `~/mealie-sqlite`, `~/unbidden-lab/*`) are never opened for writing by this
branch; the reader opens any workspace read-only, but development does not point it at those either.
