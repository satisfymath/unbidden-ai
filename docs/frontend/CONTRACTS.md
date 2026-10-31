# Frontend contracts (schema version 1)

All objects carry `schema: 1`. Python sources: `unbidden/web/contracts.py` (pydantic). TypeScript mirrors:
`frontend/src/contracts/*.ts` (zod). The server rejects any object that does not validate.

## Workspace summary — `GET /api/summary`

```
{ schema: 1, workspace: { id, name, repo, mode: "demo"|"historical"|"live", head, schema_version },
  connection: { server: "local", route: { tier, provider, model, reachable }, autonomy: { level, observe, run_experiments, ... } },
  activity: <director.activity.build output, unchanged>,
  counts: { opportunities, experiments, proposals, events, model_runs, connections },
  capabilities: ["experiments","world","connections","probes","checks","proposals","goals","anomalies"],
  observed_at, freshness: "current"|"historical"|"demo"|"stale", last_event_seq }
```

## Events — `GET /api/events?after=<seq>&limit=` and `GET /api/events/stream` (SSE)

```
{ schema: 1, seq, ts, type, actor, entity_id, correlation_id, payload, mode }
```
SSE: `id: <seq>`, `event: engine`, data as above; `event: heartbeat` every 15 s with `{ last_seq, observed_at }`;
`event: stale` when the source could not be read. Resume with `Last-Event-ID` or `?after=`. The client deduplicates
by `seq`.

## Data references — `dataRef`

```
{ dataset: "experiment.samples" | "experiment.sessions" | "probe.rounds" | "spend.by_run" | "events.by_type" |
           "opportunities" | "tests.failed" | "world.relations" | "checks" | ...,
  params: { experiment_id?, opportunity_id?, target?, deploy?, since?, ... },
  transform?: { select?: string[], filter?: [{ field, op: "eq"|"ne"|"gt"|"lt"|"in"|"contains", value }],
                group_by?: string, aggregate?: { field, fn: "count"|"sum"|"mean"|"median"|"p95"|"min"|"max" },
                sort?: { field, dir: "asc"|"desc" }, limit?: number } }
```
`GET /api/datasets` lists datasets with their fields and units; `POST /api/data` resolves a `dataRef` and returns
`{ columns: [{name, type, unit?}], rows, provenance, truncated }`. No SQL, no code: only the transforms above.

## Widget spec

```
{ schema: 1, id, type, title, position: {x, y}, size: {w, h}, pinned?, z?,
  dataRef?, view?: { kind: "line"|"bar"|"scatter"|"distribution"|"table"|"metrics"|..., x?, y?, series?, ... },
  provenance?: { source, scope, observed_at, freshness, completeness, limit?, evidence: [EvidenceRef] },
  status: "ready"|"loading"|"empty"|"blocked"|"revoked"|"inconclusive"|"stale"|"error",
  entity?: { kind: "opportunity"|"experiment"|"proposal"|"connection"|"deployment"|"need"|"block"|"goal", id } }
```
Types: `activity`, `resources`, `finding`, `experiment`, `chart`, `table`, `metrics`, `code`, `diff`, `minimal_case`,
`tests`, `screenshots`, `sql`, `need`, `acceptance`, `system_map`, `proposal`, `note`.

## Canvas edges

```
{ schema: 1, id, source, target, kind: "evidence"|"trace"|"annotation", label?, evidence?: [EvidenceRef], note? }
```

## Presentation — `GET/PUT /api/presentation`

```
{ schema: 1, workspace, version, widgets: [WidgetSpec], edges: [Edge], viewport: {x, y, zoom},
  config: { auto_add: boolean, reduced_motion?: boolean }, updated_at }
```
`PUT` carries `base_version`; a stale base is refused (409) and the client reloads. `POST /api/presentation/undo`
and `/redo` move along the stored history (bounded to 50 versions).

## Conversation — `GET/POST /api/chat`, `DELETE /api/chat`

```
message: { schema: 1, id, role: "user"|"assistant"|"tool", content, created_at,
           context?: { selected: [widget ids] }, state?: "thinking"|"reading"|"building"|"done"|"error"|"cancelled",
           tool_calls?: [ToolCall], results?: [ToolResult], planner: "rule"|"brain", model?: string }
```
`POST /api/chat` streams SSE: `state`, `token` (when the provider streams), `tool_call`, `tool_result`, `done`.
`POST /api/chat/cancel` cancels the current turn and reports what was cancelled (planning, a read, or nothing).

## Tools (planner ⇄ runtime)

| Tool | Arguments | Effect |
|---|---|---|
| `inspect_data` | `dataRef` | read; returns columns, a sample and provenance |
| `create_widget` | `WidgetSpec` without id/position, `near?: widget id` | presentation write |
| `update_widget` | `id`, partial `view`/`dataRef`/`title`/`size` | presentation write |
| `connect_widgets` | `source`, `target`, `kind: "annotation"|"trace"`, `label`, `justification` | presentation write; `evidence` edges are never created by the planner |
| `undo_presentation` | — | presentation history |
| `explain` | `entity`, `question` | read; answers from the record with evidence refs |

Results: `{ ok, tool, summary, widget_id?, error?: { code, detail } }`. A tool that lacks data answers
`error.code = "no_data"` with `error.need` (what would fill it); nothing is fabricated.

## Actions — `POST /api/actions/<name>`

```
request:  { schema: 1, operation: "kill"|"resume"|"evaluate", subject?, reason?, expected_revision?, expires_at?, idempotency_key }
response: { ok, operation, effect: "done"|"refused"|"not_supported_here", verdict?: PolicyVerdict, cli?: "unbidden approve opp_..." }
```
`not_supported_here` is honest: the engine's store has one writer; the response names the CLI command.
