# Frontend architecture

An optional visual workspace over what the engine already records: a floating glass shell, an infinite canvas of
typed widgets, a live activity feed and a chat that composes widgets from validated specifications. It adds no
second Director and duplicates no policy: every read goes through a read-only adapter, every model call through
`Brain.complete`, every operational effect through the engine's existing capability or is shown as the CLI command
that does it.

```
 browser (frontend/)                       python -m unbidden.web  (unbidden/web/)
 ┌────────────────────────────┐            ┌─────────────────────────────────────────────┐
 │ shell · canvas · widgets   │  HTTP/SSE  │ server.py  loopback, session token, Host/   │
 │ chat dock · inspector      │◄──────────►│            Origin check, static assets       │
 │ zustand store + zod schemas│            │ api/read      reader.py  (ReadOnlyStore)    │
 │ xyflow canvas              │            │ api/present   presentation.py (own SQLite)  │
 │ recharts charts            │            │ api/chat      chat.py  planner + tools       │
 └────────────────────────────┘            │ api/actions   actions.py (kill switch, policy)│
                                           │ sources.py    demo | historical | live        │
                                           └─────────────────────────────────────────────┘
                                                     │ read-only          │ own files
                                                     ▼                    ▼
                                           .unbidden/state.db     .unbidden/web-presentation.db
                                           (the engine's)          .unbidden/web-state.db (Brain's records)
```

## Server (`unbidden/web/`)

- **`server.py`**: standard-library `ThreadingHTTPServer`, no new Python dependency (the engine's lock is untouched).
  Binds `127.0.0.1` only. Generates a session token at start, prints the URL once (`/?s=<token>`), and requires it on
  every `/api/*` call as `Authorization: Bearer`. Rejects requests whose `Host` is not the bound address or whose
  `Origin`, when present, is not the server's own origin: a malicious page on another origin cannot read or act.
  Serves `unbidden/web/static/` when built (no Node needed for a distribution), else tells how to run Vite.
- **`reader.py`**: `ReadOnlyStore(Store)` overrides only `__init__`: opens `file:...?mode=ro&immutable=0` with
  `check_same_thread=False`, verifies `PRAGMA user_version <= SCHEMA_VERSION`, runs no migration, and inherits every
  read method, so `director.activity.build` runs unchanged on it. Every read is one short statement.
- **`sources.py`**: a `Source` is a workspace in one of three modes, under the same contracts:
  - `demo`: fixtures built in code (`demo.py`, a fictional shop with a fixed seed) through the real contracts into an
    in-memory `Store`; labelled *demostración* everywhere. `devseed.py` writes the same records through the engine's
    `Store` into a development workspace, so the live reader and the event stream can be exercised without a run.
  - `historical`: a published record directory (`docs/bench/...`) loaded into an in-memory store; labelled
    *histórico* with the record's own timestamps; no event is ever presented as current.
  - `live`: a real workspace directory opened read-only; events stream from the `events` table by `seq`.
- **`presentation.py`**: the canvas (widgets, edges, viewport, config) and the conversation per workspace, in the
  web server's own SQLite file. Undo/redo is a history of layout versions. Nothing here touches the engine's
  state: removing a widget deletes no experiment; clearing a conversation deletes no audit.
- **`chat.py`**: the planner. Tools are pydantic models (`inspect_data`, `create_widget`, `update_widget`,
  `connect_widgets`, `undo_presentation`, `explain`) whose JSON schemas are generated with `ToolSpec.from_model`.
  Two planners share the tool runtime: `RulePlanner` (deterministic, offline, used by tests and when no model is
  reachable) and `BrainPlanner` (an `LLMRequest` with the tools, purpose `web.chat`, through `Brain.complete`
  with the workspace's mandate, kill switch and the machine's spend ledger; the Brain writes its records to
  `web-state.db`, the web process's own store). The tool runtime validates every argument against the widget
  schemas and the dataset catalogue before applying; a request to *show* never runs an experiment.
- **`actions.py`**: the kill switch (a file, safe across processes, the same as `unbidden kill`/`resume`) and
  `PolicyEngine.evaluate` for showing what the mandate would decide. Writes to the engine's queue (approve,
  reject, deploy) are not done here: the engine's store has one writer; the UI shows the command.

## Frontend (`frontend/`)

React 19, TypeScript, Vite, `@xyflow/react` 12 for the canvas (custom nodes, drag, resize, edges, viewport,
minimap), `zustand` for state, `zod` for every contract, `recharts` for charts, `lucide-react` for icons,
`@tanstack/react-virtual` for long tables. Tests: `vitest` (units) and `@playwright/test` (browser).

Layout: `src/shell/` (top bar, dock, inspector, mobile list), `src/canvas/` (flow, nodes, edges, layout, undo),
`src/widgets/` (registry and one component per widget type), `src/data/` (API client, SSE client, dataset
transforms), `src/chat/`, `src/contracts/` (zod schemas mirroring `docs/frontend/CONTRACTS.md`), `src/theme/`.

Rendering budget: nodes outside the viewport are not mounted (`onlyRenderVisibleElements`), tables and logs are
paginated and virtualised, charts cap their points and say so.

Ownership on the canvas: React Flow owns the selection and mirrors it one way into the store (`onSelectionChange`);
the store owns positions, sizes, edges and the viewport, saved debounced and serialised (one save in flight, each
reading the version the previous one left). Rebuilding nodes from the store keeps each node's measured size and
selected flag, so the two never ping-pong. A programmatic focus (a chat result, "Ver widget") selects in React Flow
first and then fits the view to that card.

## Composition of the workspace

`composer.ts` builds the initial canvas from what the summary says exists, never from a repository's name:
experiments with samples → latency widgets; a world model with relations → a system map; connections → resources;
proposals → proposals; blocks and needs → requests to a person; probe rounds → live latency; project checks →
checks. A capability without data yields no widget, or a widget that says what is missing. New events add widgets
only when the user asked for "auto-add", and never move what the user placed.

## Edges on the canvas

Three kinds, visually distinct and stored with their kind: `evidence` (a `WorldModel` relation, with its evidence
refs), `trace` (finding → experiment → change → result, from `opportunity_id`/`experiment_id` links), `annotation`
(drawn by the user). An annotation never changes the World Model.

## Modes and provenance

Every data widget carries `provenance`: `source` (workspace id, mode), `scope` (revision, deploy, run), `observed_at`,
`freshness` (`current` / `historical` / `demo` / `stale`), `completeness` (`complete` / `partial` with a limit, or
`missing` with what would fill it), and `evidence` refs. The top bar states the server location (local), the
inference route (local Ollama model, Meta API, or none) and the autonomy level from the mandate, separately.
