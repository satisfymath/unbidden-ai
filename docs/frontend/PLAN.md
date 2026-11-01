# Implementation path and status

Deliveries, each openable and testable. Status as of 2026-10-31 (✓ done, ◐ partial, ○ not started).

| # | Delivery | Status |
|---|---|---|
| 1 | Glass shell, infinite canvas, persistence (server + presentation store + undo/redo) | ✓ |
| 2 | Widgets on real records: read-only reader, demo fixtures, historical records (conduit DEMO-B-1, fst revalidation, mealie L5), composer by capability | ✓ |
| 3 | Contextual chat that creates and modifies widgets (rule planner offline; Brain planner wired and tested with the mock provider) | ✓ |
| 4 | Live events (SSE, cursor, reconnection, staleness) on a development workspace; new findings proposed below the user's cards | ✓ |
| 5 | Supported actions (kill switch, policy verdicts, CLI handoff), onboarding, packaging (`make web-build`), polish | ◐ packaging documented, not shipped in the wheel |

## Run

```
# server (any mode); prints one URL with the session token; binds 127.0.0.1 only
uv run python -m unbidden.web --demo                                             # fixtures (labelled demo)
uv run python -m unbidden.web --record docs/bench/stage9-demo/DEMO-B-1            # a closed run, as history
uv run python -m unbidden.web --record docs/bench/stage10-revalidation/v4-f9fe965/fst-f9fe965.json
uv run python -m unbidden.web --workspace ~/unbidden-fe-dev/sample                # live, read-only on its state.db
# several at once: every flag may repeat; the top-left menu switches between them

# a development workspace with records written through the engine's Store (never an evaluation workspace)
uv run python -m unbidden.web.devseed ~/unbidden-fe-dev/sample            # once
uv run python -m unbidden.web.devseed ~/unbidden-fe-dev/sample --tick 20 --every 5   # append events while watching

# frontend in development (Vite proxies /api; add --dev to the server so it accepts that origin)
uv run python -m unbidden.web --demo --dev
cd frontend && npm ci && npm run dev          # then open http://127.0.0.1:5174/?s=<token>

# built distribution: no Node needed afterwards, the same server serves unbidden/web/static/
make web-build && uv run python -m unbidden.web --demo
```

Flags: `--planner rule|brain|auto` (auto uses the local model only when Ollama answers; `rule` never calls a
model), `--state-dir` (where the canvas and the conversation live; default `~/.unbidden/web/`), `--token` (a fixed
session token for scripts and tests), `--port` (8765; the next free one is used, nothing is ever stopped),
`--no-tick` (demo: no synthetic event every 20 s).

## Verify

```
make check                      # the engine's lint, types and tests (unchanged, tests/web included)
uv run pytest tests/web -q      # server guards, reader, datasets, presentation, chat (rules and Brain), sources, actions
cd frontend && npm run lint && npm run typecheck && npm test     # eslint, tsc, vitest (contracts, composer, sse, escaping)
cd frontend && npm run e2e      # Playwright: builds the assets, starts its own server on 8799 with a fresh state
```

The Playwright suite walks the delivered story: open the project → understand what happens → select the validated
finding → ask "Muéstrame la latencia antes y después de este experimento" → the chart appears beside the finding with
its provenance → inspector with the evidence and the opportunity's events → reload keeps the space. It also covers
chat edits (bars, compare, undo), drag/resize/zoom/remove-with-undo, scrolling inside a table without panning,
server-side rejection of a bad spec and of a cross-origin call, a historical record shown as closed, keyboard tabs and
the list view on a narrow screen.

## What was verified in a browser (screenshots during development)

Demo, three historical records and the live development workspace were opened and compared with the references:
petrol glass, floating bars, turquoise traces with labelled pills, chart/table/map cards, the chat over the dimmed
canvas, the inspector, the Experimentos and Actividad views, the settings popover. Known visual gaps: the system
map scrolls horizontally when a world has many kinds; charts cap at 1,500 points and say so.

## Pending (not done; listed so nobody takes it as finished)

- `unbidden ui` in `cli.py` (one line; see BASE.md) and the wheel including `unbidden/web/static/**`.
- A paid chat turn on the Meta API: `web.chat` is local-only by the engine's rule for unknown purposes; no budget was
  authorised for this branch; the Brain path is exercised with the mock provider in `tests/web/test_chat.py`.
  With Ollama up, `--planner auto` answers through the local model (verified on 2026-11-01 with
  `muse-glimmer:30b`: it reads the datasets with `inspect_data` and answers from them, about a minute per turn on
  this host). When every answer of the model is rejected, the rules answer and the message says so.
- Approve / reject / deploy / rollback from the UI: they need the daemon (the store's writer) to accept commands;
  the UI returns `not_supported_here` with the exact CLI command.
- Screenshot comparison: the engine stores page captures under `.unbidden/artifacts`; the card states their absence
  and what produces them; serving images was not wired.
- A real `unbidden scan` on the development workspace: the seed writes records through the engine's `Store`
  (contracts, events, rounds); an actual scan was not run during this session to avoid Docker builds beside the
  evaluation.
