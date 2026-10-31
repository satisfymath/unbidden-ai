# Implementation path and status

Deliveries, each openable and testable. Status is kept here as work lands (✓ done, ◐ partial, ○ not started).

| # | Delivery | Status |
|---|---|---|
| 1 | Glass shell, infinite canvas, persistence (server + presentation store + undo/redo) | ○ |
| 2 | Widgets on real records: read-only reader, demo fixtures, historical record (conduit DEMO-B-1), composer | ○ |
| 3 | Contextual chat that creates and modifies widgets (rule planner; Brain planner wired) | ○ |
| 4 | Live events (SSE, cursor, reconnection, staleness) and adaptive composition on a dev workspace | ○ |
| 5 | Supported actions (kill switch, policy verdicts, CLI handoff), onboarding, packaging, polish | ○ |

## Run

```
# server (any mode); prints the URL with the session token
uv run python -m unbidden.web --demo                       # fixtures
uv run python -m unbidden.web --record docs/bench/stage9-demo/DEMO-B-1   # a closed run
uv run python -m unbidden.web --workspace ~/unbidden-fe-dev/sample       # live, read-only on state.db

# frontend in development (proxies /api to the server)
cd frontend && npm ci && npm run dev

# built distribution (no Node needed afterwards)
make web-build            # writes unbidden/web/static/, served by the same server
```

## Verify

```
make check                      # engine lint, types, tests (unchanged)
uv run pytest tests/web -q      # server, reader, planner, presentation
cd frontend && npm run lint && npm run typecheck && npm test
cd frontend && npm run e2e      # Playwright against the demo server
```

## Pending integrations (not done, listed so nobody takes them as finished)

- `unbidden ui` in `cli.py` (one line; see BASE.md).
- A paid chat turn on the Meta API: the purpose `web.chat` is local-only by the engine's rule for unknown purposes;
  no budget was authorised for this branch, so the path is wired and tested with the mock provider only.
- Approve / reject / deploy from the UI: need the store's writer (the daemon) to accept commands; the UI shows the
  CLI command instead.
