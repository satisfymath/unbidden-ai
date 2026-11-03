"""Contracts between the browser and the local server (schema 1). Mirrored in `frontend/src/contracts/`.

Every object the browser sends is validated here before it is stored or acted on: a widget is a specification the
registry can render, never code; a data reference names a dataset and a bounded transform, never a query.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from unbidden.contracts.common import EvidenceRef, new_id, utc_now

SCHEMA = 1

Mode = Literal["demo", "historical", "live"]
Freshness = Literal["current", "historical", "demo", "stale"]
Completeness = Literal["complete", "partial", "missing"]
WidgetStatus = Literal["ready", "loading", "empty", "blocked", "revoked", "inconclusive", "stale", "error"]
WidgetType = Literal[
    "activity",
    "resources",
    "finding",
    "experiment",
    "chart",
    "table",
    "metrics",
    "code",
    "diff",
    "minimal_case",
    "tests",
    "screenshots",
    "sql",
    "need",
    "acceptance",
    "system_map",
    "proposal",
    "note",
]
ViewKind = Literal["line", "bar", "scatter", "distribution", "table", "metrics", "list", "map", "text"]
EdgeKind = Literal["evidence", "trace", "annotation"]
EntityKind = Literal[
    "opportunity", "experiment", "proposal", "connection", "deployment", "need", "block", "goal", "action", "resource"
]
FilterOp = Literal["eq", "ne", "gt", "lt", "gte", "lte", "in", "contains"]
AggregateFn = Literal["count", "sum", "mean", "median", "p95", "min", "max"]


class WebContract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# Data references ------------------------------------------------------------------------------------------------


class Filter(WebContract):
    field: str = Field(min_length=1, max_length=64)
    op: FilterOp
    value: Any = None


class Aggregate(WebContract):
    field: str = Field(min_length=1, max_length=64)
    fn: AggregateFn


class Sort(WebContract):
    field: str = Field(min_length=1, max_length=64)
    dir: Literal["asc", "desc"] = "asc"


class Transform(WebContract):
    select: list[str] | None = Field(default=None, max_length=32)
    filter: list[Filter] = Field(default_factory=list, max_length=16)
    group_by: str | None = None
    aggregate: Aggregate | None = None
    sort: Sort | None = None
    limit: int = Field(default=500, ge=1, le=5000)


class DataRef(WebContract):
    dataset: str = Field(pattern=r"^[a-z][a-z0-9_.]*$", max_length=64)
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    transform: Transform = Field(default_factory=Transform)


class Column(WebContract):
    name: str
    type: Literal["string", "number", "datetime", "boolean", "json"]
    unit: str | None = None


class Provenance(WebContract):
    source: str  # workspace id
    mode: Mode
    scope: str | None = None  # revision, deploy, run
    observed_at: datetime | None = None
    freshness: Freshness
    completeness: Completeness = "complete"
    limit: int | None = None
    note: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DataResult(WebContract):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    columns: list[Column]
    rows: list[dict[str, Any]]
    provenance: Provenance
    truncated: bool = False
    total: int | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# Widgets and the canvas -----------------------------------------------------------------------------------------


class Position(WebContract):
    x: float = Field(ge=-1e6, le=1e6)
    y: float = Field(ge=-1e6, le=1e6)


class Size(WebContract):
    w: float = Field(ge=160, le=2400)
    h: float = Field(ge=80, le=2000)


class View(WebContract):
    kind: ViewKind = "table"
    x: str | None = None
    y: str | None = None
    series: str | None = None
    columns: list[str] | None = Field(default=None, max_length=32)
    bins: int | None = Field(default=None, ge=2, le=100)
    unit: str | None = None
    language: str | None = None  # for code views
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class EntityRef(WebContract):
    kind: EntityKind
    id: str = Field(min_length=1, max_length=200)


class WidgetSpec(WebContract):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    id: str = Field(default_factory=lambda: new_id("w"), pattern=r"^[A-Za-z0-9_\-:.]{1,64}$")
    type: WidgetType
    title: str = Field(min_length=1, max_length=160)
    position: Position = Field(default_factory=lambda: Position(x=0, y=0))
    size: Size = Field(default_factory=lambda: Size(w=420, h=300))
    pinned: bool = False
    z: int = 0
    dataRef: DataRef | None = None
    view: View = Field(default_factory=View)
    provenance: Provenance | None = None
    status: WidgetStatus = "ready"
    entity: EntityRef | None = None
    content: dict[str, Any] = Field(
        default_factory=dict
    )  # static content (a finding's text, a diff), escaped on render
    created_by: Literal["composer", "user", "chat"] = "user"

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Edge(WebContract):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    id: str = Field(default_factory=lambda: new_id("e"), pattern=r"^[A-Za-z0-9_\-:.]{1,64}$")
    source: str
    target: str
    kind: EdgeKind
    label: str | None = Field(default=None, max_length=80)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=400)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Viewport(WebContract):
    x: float = 0
    y: float = 0
    zoom: float = Field(default=1.0, ge=0.05, le=4)


class CanvasConfig(WebContract):
    auto_add: bool = True
    reduced_motion: bool = False
    layout: Literal["manual", "grid"] = "manual"


class Presentation(WebContract):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    workspace: str
    version: int = 0
    widgets: list[WidgetSpec] = Field(default_factory=list, max_length=400)
    edges: list[Edge] = Field(default_factory=list, max_length=2000)
    viewport: Viewport = Field(default_factory=Viewport)
    config: CanvasConfig = Field(default_factory=CanvasConfig)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PresentationUpdate(WebContract):
    base_version: int = Field(ge=0)
    widgets: list[WidgetSpec] = Field(max_length=400)
    edges: list[Edge] = Field(default_factory=list, max_length=2000)
    viewport: Viewport = Field(default_factory=Viewport)
    config: CanvasConfig = Field(default_factory=CanvasConfig)
    reason: str = Field(default="edit", max_length=120)


# Conversation ---------------------------------------------------------------------------------------------------


class ChatToolCall(WebContract):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolError(WebContract):
    code: Literal["no_data", "invalid", "not_found", "refused", "unsupported"]
    detail: str
    need: str | None = None


class ToolResult(WebContract):
    ok: bool
    tool: str
    summary: str
    widget_id: str | None = None
    edge_id: str | None = None
    error: ToolError | None = None
    data: dict[str, Any] | None = None


ChatState = Literal["thinking", "reading", "building", "done", "error", "cancelled"]


class ChatMessage(WebContract):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    id: str = Field(default_factory=lambda: new_id("msg"))
    role: Literal["user", "assistant", "tool"]
    content: str = Field(max_length=20_000)
    created_at: datetime = Field(default_factory=utc_now)
    context: dict[str, Any] = Field(default_factory=dict)
    state: ChatState | None = None
    tool_calls: list[ChatToolCall] = Field(default_factory=list)
    results: list[ToolResult] = Field(default_factory=list)
    planner: Literal["rule", "brain"] | None = None
    model: str | None = None
    route: ChatRoute | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ChatRoute(WebContract):
    """How a turn was answered: what it asked for, which purpose was routed, where the model ran, or why it could
    not. `blocked` carries the router's own reason; `hint` what would allow it (a command, never a change made)."""

    intent: Literal["inform", "analyze", "act"]
    purpose: str | None = None  # chat.inform, chat.analyze
    tier: str | None = None  # local, code, frontier
    model: str | None = None
    reason: str | None = None  # the router's reason for the route taken
    blocked: str | None = None
    hint: str | None = None
    action: str | None = None  # the operation an `act` message asked for


class ChatRequest(WebContract):
    content: str = Field(min_length=1, max_length=4000)
    selected: list[str] = Field(default_factory=list, max_length=20)  # widget ids in context
    planner: Literal["auto", "rule", "brain"] = "auto"


# Actions --------------------------------------------------------------------------------------------------------


class ActionRequestWeb(WebContract):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    operation: Literal[
        "kill", "resume", "evaluate", "approve", "reject", "deploy", "rollback", "approve_writes", "answer"
    ]
    subject: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=400)
    option: str | None = Field(default=None, max_length=40)  # answer: the option chosen
    value: str | None = Field(default=None, max_length=400)  # answer: the value the option takes
    capability: str | None = Field(default=None, max_length=80)
    expected_revision: str | None = Field(default=None, max_length=64)
    expires_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=120)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ActionResponse(WebContract):
    ok: bool
    operation: str
    effect: Literal["done", "refused", "not_supported_here", "already"]
    detail: str
    verdict: dict[str, Any] | None = None
    cli: str | None = None
