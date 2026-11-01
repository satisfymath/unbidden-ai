// Schema 1 of the browser ⇄ server contracts; the server's `unbidden/web/contracts.py` is the source of truth and
// every object coming from the network or from the chat is parsed here before it reaches the canvas.
import { z } from "zod";

export const SCHEMA = 1;

export const EvidenceRef = z.object({
  kind: z.string(),
  locator: z.string(),
  sha256: z.string().nullable().optional(),
  note: z.string().nullable().optional(),
  captured_at: z.string().optional(),
});
export type EvidenceRef = z.infer<typeof EvidenceRef>;

export const Mode = z.enum(["demo", "historical", "live"]);
export type Mode = z.infer<typeof Mode>;
export const Freshness = z.enum(["current", "historical", "demo", "stale"]);
export type Freshness = z.infer<typeof Freshness>;

export const Provenance = z.object({
  source: z.string(),
  mode: Mode,
  scope: z.string().nullable().optional(),
  observed_at: z.string().nullable().optional(),
  freshness: Freshness,
  completeness: z.enum(["complete", "partial", "missing"]).default("complete"),
  limit: z.number().nullable().optional(),
  note: z.string().nullable().optional(),
  evidence: z.array(EvidenceRef).default([]),
});
export type Provenance = z.infer<typeof Provenance>;

export const FilterOp = z.enum(["eq", "ne", "gt", "lt", "gte", "lte", "in", "contains"]);
export const Transform = z.object({
  select: z.array(z.string()).max(32).nullable().optional(),
  filter: z.array(z.object({ field: z.string(), op: FilterOp, value: z.unknown().optional() })).max(16).default([]),
  group_by: z.string().nullable().optional(),
  aggregate: z.object({ field: z.string(), fn: z.enum(["count", "sum", "mean", "median", "p95", "min", "max"]) }).nullable().optional(),
  sort: z.object({ field: z.string(), dir: z.enum(["asc", "desc"]).default("asc") }).nullable().optional(),
  limit: z.number().int().min(1).max(5000).default(500),
}).strict();
export type Transform = z.infer<typeof Transform>;

export const DataRef = z.object({
  dataset: z.string().regex(/^[a-z][a-z0-9_.]*$/),
  params: z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()])).default({}),
  transform: Transform.default({ filter: [], limit: 500 }),
}).strict();
export type DataRef = z.infer<typeof DataRef>;

export const Column = z.object({
  name: z.string(),
  type: z.enum(["string", "number", "datetime", "boolean", "json"]),
  unit: z.string().nullable().optional(),
});
export type Column = z.infer<typeof Column>;

export const DataResult = z.object({
  schema: z.number().optional(),
  columns: z.array(Column),
  rows: z.array(z.record(z.string(), z.unknown())),
  provenance: Provenance,
  truncated: z.boolean().default(false),
  total: z.number().nullable().optional(),
});
export type DataResult = z.infer<typeof DataResult>;

export const WidgetType = z.enum([
  "activity", "resources", "finding", "experiment", "chart", "table", "metrics", "code", "diff", "minimal_case",
  "tests", "screenshots", "sql", "need", "acceptance", "system_map", "proposal", "note",
]);
export type WidgetType = z.infer<typeof WidgetType>;
export const ViewKind = z.enum(["line", "bar", "scatter", "distribution", "table", "metrics", "list", "map", "text"]);
export type ViewKind = z.infer<typeof ViewKind>;
export const WidgetStatus = z.enum(["ready", "loading", "empty", "blocked", "revoked", "inconclusive", "stale", "error"]);
export type WidgetStatus = z.infer<typeof WidgetStatus>;
export const EntityKind = z.enum([
  "opportunity", "experiment", "proposal", "connection", "deployment", "need", "block", "goal", "action", "resource",
]);
export const EntityRef = z.object({ kind: EntityKind, id: z.string().min(1).max(200) });
export type EntityRef = z.infer<typeof EntityRef>;

export const View = z.object({
  kind: ViewKind.default("table"),
  x: z.string().nullable().optional(),
  y: z.string().nullable().optional(),
  series: z.string().nullable().optional(),
  columns: z.array(z.string()).max(32).nullable().optional(),
  bins: z.number().int().min(2).max(100).nullable().optional(),
  unit: z.string().nullable().optional(),
  language: z.string().nullable().optional(),
  options: z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()])).default({}),
}).strict();
export type View = z.infer<typeof View>;

export const Position = z.object({ x: z.number().min(-1e6).max(1e6), y: z.number().min(-1e6).max(1e6) });
export const Size = z.object({ w: z.number().min(160).max(2400), h: z.number().min(80).max(2000) });

export const WidgetSpec = z.object({
  schema: z.number().default(SCHEMA),
  id: z.string().regex(/^[A-Za-z0-9_\-:.]{1,64}$/),
  type: WidgetType,
  title: z.string().min(1).max(160),
  position: Position,
  size: Size,
  pinned: z.boolean().default(false),
  z: z.number().int().default(0),
  dataRef: DataRef.nullable().optional(),
  view: View.default({ kind: "table", options: {} }),
  provenance: Provenance.nullable().optional(),
  status: WidgetStatus.default("ready"),
  entity: EntityRef.nullable().optional(),
  content: z.record(z.string(), z.unknown()).default({}),
  created_by: z.enum(["composer", "user", "chat"]).default("user"),
}).strict();
export type WidgetSpec = z.infer<typeof WidgetSpec>;

export const EdgeKind = z.enum(["evidence", "trace", "annotation"]);
export const Edge = z.object({
  schema: z.number().default(SCHEMA),
  id: z.string(),
  source: z.string(),
  target: z.string(),
  kind: EdgeKind,
  label: z.string().max(80).nullable().optional(),
  evidence: z.array(EvidenceRef).default([]),
  note: z.string().max(400).nullable().optional(),
}).strict();
export type Edge = z.infer<typeof Edge>;

export const Viewport = z.object({ x: z.number().default(0), y: z.number().default(0), zoom: z.number().min(0.05).max(4).default(1) });
export type Viewport = z.infer<typeof Viewport>;
export const CanvasConfig = z.object({
  auto_add: z.boolean().default(true),
  reduced_motion: z.boolean().default(false),
  layout: z.enum(["manual", "grid"]).default("manual"),
}).strict();
export type CanvasConfig = z.infer<typeof CanvasConfig>;

export const History = z.object({ version: z.number(), top: z.number(), can_undo: z.boolean(), can_redo: z.boolean() });
export const Presentation = z.object({
  schema: z.number().optional(),
  workspace: z.string(),
  version: z.number(),
  widgets: z.array(WidgetSpec),
  edges: z.array(Edge),
  viewport: Viewport,
  config: CanvasConfig,
  updated_at: z.string().optional(),
  history: History.optional(),
}).strict();
export type Presentation = z.infer<typeof Presentation>;

export const ToolError = z.object({
  code: z.enum(["no_data", "invalid", "not_found", "refused", "unsupported"]),
  detail: z.string(),
  need: z.string().nullable().optional(),
}).strict();
export const ToolResult = z.object({
  ok: z.boolean(),
  tool: z.string(),
  summary: z.string(),
  widget_id: z.string().nullable().optional(),
  edge_id: z.string().nullable().optional(),
  error: ToolError.nullable().optional(),
  data: z.record(z.string(), z.unknown()).nullable().optional(),
}).strict();
export type ToolResult = z.infer<typeof ToolResult>;
export const ChatToolCall = z.object({ id: z.string(), name: z.string(), arguments: z.record(z.string(), z.unknown()) });
export const ChatState = z.enum(["thinking", "reading", "building", "done", "error", "cancelled"]);
export type ChatState = z.infer<typeof ChatState>;
export const ChatMessage = z.object({
  schema: z.number().optional(),
  id: z.string(),
  role: z.enum(["user", "assistant", "tool"]),
  content: z.string(),
  created_at: z.string(),
  context: z.record(z.string(), z.unknown()).default({}),
  state: ChatState.nullable().optional(),
  tool_calls: z.array(ChatToolCall).default([]),
  results: z.array(ToolResult).default([]),
  planner: z.enum(["rule", "brain"]).nullable().optional(),
  model: z.string().nullable().optional(),
}).strict();
export type ChatMessage = z.infer<typeof ChatMessage>;

export const EngineEvent = z.object({
  seq: z.number().nullable(),
  ts: z.string(),
  type: z.string(),
  actor: z.string(),
  entity_id: z.string().nullable().optional(),
  correlation_id: z.string().nullable().optional(),
  payload: z.record(z.string(), z.unknown()).default({}),
  mode: Mode.optional(),
});
export type EngineEvent = z.infer<typeof EngineEvent>;

export const SourceBrief = z.object({
  id: z.string(),
  name: z.string(),
  mode: Mode,
  repo: z.string().nullable().optional(),
  streams: z.boolean(),
  notes: z.array(z.string()).default([]),
});
export type SourceBrief = z.infer<typeof SourceBrief>;

export const Summary = z.object({
  schema: z.number(),
  workspace: z.object({
    id: z.string(),
    name: z.string(),
    repo: z.string().nullable(),
    mode: Mode,
    head: z.string().nullable(),
    schema_version: z.number(),
    notes: z.array(z.string()).default([]),
  }),
  connection: z.object({
    route: z.object({
      server: z.string(),
      profile: z.string(),
      local: z.object({ provider: z.string().nullable(), model: z.string().nullable(), base_url: z.string().nullable() }),
      remote: z.object({ provider: z.string().nullable(), model: z.string().nullable(), credential_file_present: z.boolean() }),
      local_inference: z.string(),
      note: z.string(),
    }),
    autonomy: z.object({
      level: z.string(),
      fields: z.record(z.string(), z.string()).default({}),
      spend_cap_usd: z.number().optional(),
      detail: z.string().optional(),
    }),
    kill_switch: z.boolean().nullable(),
    streams: z.boolean(),
  }),
  activity: z.record(z.string(), z.unknown()),
  counts: z.record(z.string(), z.number()),
  jobs: z.record(z.string(), z.number()).default({}),
  capabilities: z.array(z.string()),
  highlights: z.array(z.object({ id: z.string(), title: z.string(), level: z.number(), status: z.string(), has_experiment: z.boolean() })).default([]),
  timeline_lines: z.number().default(0),
  observed_at: z.string(),
  freshness: Freshness,
  last_event_seq: z.number(),
});
export type Summary = z.infer<typeof Summary>;

export const ActionResponse = z.object({
  ok: z.boolean(),
  operation: z.string(),
  effect: z.enum(["done", "refused", "not_supported_here", "already"]),
  detail: z.string(),
  verdict: z.record(z.string(), z.unknown()).nullable().optional(),
  cli: z.string().nullable().optional(),
});
export type ActionResponse = z.infer<typeof ActionResponse>;

export const Paged = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), offset: z.number(), limit: z.number() });
