"""The conversation: a planner chooses typed tools; a runtime validates and applies them to the canvas.

Two planners share one runtime. `RulePlanner` is deterministic and offline: it reads the request for a few intents
(a chart of latency, a table of failed tests, spend by run, explain a block, change a chart's kind, compare two
runs, undo). `BrainPlanner` gives the same tools to a model through `Brain.complete` (purpose `web.chat`: by the
engine's rule for unknown purposes it is light and local-only; Guardian, egress, classification, spend and the kill
switch all apply). Neither planner runs code from the model: a tool call is validated against the widget contracts
and the dataset catalogue, and a request to *show* never runs an experiment or acquires an access.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from unbidden.contracts.experiment import Experiment, Proposal
from unbidden.contracts.llm import LLMRequest, Message, Tier, ToolSpec
from unbidden.contracts.opportunity import Opportunity
from unbidden.director.blocks import COLLECTION as BLOCKS
from unbidden.director.blocks import Block
from unbidden.web import datasets
from unbidden.web.contracts import (
    ChatMessage,
    ChatRequest,
    ChatToolCall,
    DataRef,
    Edge,
    EntityRef,
    Position,
    PresentationUpdate,
    Provenance,
    Size,
    ToolError,
    ToolResult,
    View,
    WidgetSpec,
    WidgetType,
)
from unbidden.web.presentation import PresentationStore
from unbidden.web.sources import Source

Emit = Callable[[str, dict[str, Any]], None]


# Tool arguments ----------------------------------------------------------------------------------------------


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWidgetArgs(_Args):
    type: WidgetType
    title: str = Field(min_length=1, max_length=160)
    dataRef: DataRef | None = None
    view: View | None = None
    entity: EntityRef | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    size: Size | None = None
    near: str | None = Field(default=None, description="a widget id to place the new one next to")


class UpdateWidgetArgs(_Args):
    id: str
    title: str | None = Field(default=None, max_length=160)
    view: dict[str, Any] | None = None  # merged into the widget's view
    dataRef: DataRef | None = None
    size: Size | None = None


class ConnectArgs(_Args):
    source: str
    target: str
    kind: Literal["annotation", "trace"]
    label: str = Field(min_length=1, max_length=80)
    justification: str = Field(min_length=8, max_length=400)


class ExplainArgs(_Args):
    entity: EntityRef
    question: str = Field(default="", max_length=400)


class NoArgs(_Args):
    pass


TOOLS: dict[str, tuple[type[BaseModel], str]] = {
    "inspect_data": (
        DataRef,
        "Read a dataset with a bounded transform; returns columns, a sample of rows and provenance.",
    ),
    "create_widget": (
        CreateWidgetArgs,
        "Add a widget to the canvas from a validated specification (type, title, "
        "dataRef, view). Charts need a dataRef; x/y must be columns of the dataset.",
    ),
    "update_widget": (UpdateWidgetArgs, "Change a widget's title, view (kind, x, y, series), dataRef or size."),
    "connect_widgets": (
        ConnectArgs,
        "Draw an edge between two widgets as an annotation or a trace, with a "
        "justification. Evidence edges come only from the world model, never from here.",
    ),
    "undo_presentation": (
        NoArgs,
        "Undo the last change of the canvas (a card, an edge, a move). Nothing of the engine is reverted.",
    ),
    "explain": (
        ExplainArgs,
        "Explain an entity (opportunity, experiment, block, need, connection, proposal) from "
        "the record, with evidence references.",
    ),
}


def tool_specs() -> list[ToolSpec]:
    return [ToolSpec.from_model(name, description, model) for name, (model, description) in TOOLS.items()]


# The runtime -------------------------------------------------------------------------------------------------


def _overlaps(a: WidgetSpec, x: float, y: float, w: float, h: float) -> bool:
    return not (
        x + w + 24 <= a.position.x
        or a.position.x + a.size.w + 24 <= x
        or y + h + 24 <= a.position.y
        or a.position.y + a.size.h + 24 <= y
    )


class ToolRuntime:
    def __init__(self, source: Source, presentation: PresentationStore, selected: list[str]) -> None:
        self.source = source
        self.presentation = presentation
        self.selected = selected
        self.created: list[str] = []

    # Context --------------------------------------------------------------------------------------------------

    def layout(self) -> Any:
        return self.presentation.current(self.source.id)

    def selected_widgets(self) -> list[WidgetSpec]:
        by_id = {w.id: w for w in self.layout().widgets}
        return [by_id[i] for i in self.selected if i in by_id]

    def entities(self) -> list[EntityRef]:
        return [w.entity for w in self.selected_widgets() if w.entity is not None]

    def experiment_in_context(self) -> Experiment | None:
        store = self.source.store
        for e in self.entities():
            if e.kind == "experiment":
                found = store.get("experiments", e.id, Experiment)
                if found:
                    return found
            if e.kind in ("opportunity", "proposal"):
                opp_id = e.id
                if e.kind == "proposal":
                    p = store.get("proposals", e.id, Proposal)
                    opp_id = p.opportunity_id if p else e.id
                exps = [x for x in store.list("experiments", Experiment) if x.opportunity_id == opp_id]
                if exps:
                    return exps[-1]
        with_samples = [
            x for x in store.list("experiments", Experiment) if x.sessions or x.samples_before_ms or x.samples_after_ms
        ]
        return with_samples[-1] if with_samples else None

    def experiments_in_context(self) -> list[Experiment]:
        out: list[Experiment] = []
        for e in self.entities():
            exp = None
            if e.kind == "experiment":
                exp = self.source.store.get("experiments", e.id, Experiment)
            elif e.kind == "opportunity":
                found = [x for x in self.source.store.list("experiments", Experiment) if x.opportunity_id == e.id]
                exp = found[-1] if found else None
            if exp and exp.id not in {x.id for x in out}:
                out.append(exp)
        return out

    def chart_in_context(self) -> WidgetSpec | None:
        charts = [w for w in self.selected_widgets() if w.type == "chart"]
        if charts:
            return charts[-1]
        all_charts = [w for w in self.layout().widgets if w.type == "chart"]
        return all_charts[-1] if all_charts else None

    # Tools ----------------------------------------------------------------------------------------------------

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        spec = TOOLS.get(name)
        if spec is None:
            return ToolResult(
                ok=False,
                tool=name,
                summary="no such tool",
                error=ToolError(code="unsupported", detail=f"no tool named {name!r}"),
            )
        model, _ = spec
        try:
            args = model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                tool=name,
                summary="invalid arguments",
                error=ToolError(code="invalid", detail=exc.errors()[0].get("msg", str(exc))[:300]),
            )
        try:
            return getattr(self, f"tool_{name}")(args)
        except datasets.DatasetError as exc:
            return ToolResult(
                ok=False,
                tool=name,
                summary="the data reference is not valid",
                error=ToolError(code="invalid", detail=str(exc)),
            )

    def tool_inspect_data(self, ref: DataRef) -> ToolResult:
        probe = ref.model_copy(
            update={"transform": ref.transform.model_copy(update={"limit": min(ref.transform.limit, 20)})}
        )
        result = datasets.resolve(self.source, probe)
        if not result.rows:
            return ToolResult(
                ok=False,
                tool="inspect_data",
                summary="no rows",
                error=ToolError(
                    code="no_data", detail=result.provenance.note or "no rows", need=result.provenance.note
                ),
            )
        return ToolResult(
            ok=True,
            tool="inspect_data",
            summary=f"{result.total} rows, {len(result.columns)} columns",
            data={
                "columns": [c.model_dump(mode="json") for c in result.columns],
                "sample": result.rows[:5],
                "total": result.total,
                "provenance": result.provenance.model_dump(mode="json"),
            },
        )

    def _place(self, size: Size, near: str | None) -> Position:
        layout = self.layout()
        by_id = {w.id: w for w in layout.widgets}
        anchors = [by_id[i] for i in ([near] if near else []) + self.selected if i in by_id]
        anchor = anchors[0] if anchors else (layout.widgets[-1] if layout.widgets else None)
        if anchor is None:
            return Position(x=80, y=120)
        candidates = [
            (anchor.position.x + anchor.size.w + 48, anchor.position.y),
            (anchor.position.x, anchor.position.y + anchor.size.h + 48),
            (anchor.position.x - size.w - 48, anchor.position.y),
            (anchor.position.x + anchor.size.w + 48, anchor.position.y + anchor.size.h + 48),
        ]
        for x, y in candidates:
            if not any(_overlaps(w, x, y, size.w, size.h) for w in layout.widgets):
                return Position(x=x, y=y)
        bottom = max(w.position.y + w.size.h for w in layout.widgets)
        return Position(x=anchor.position.x, y=bottom + 48)

    def _validate_view(self, ref: DataRef | None, view: View) -> tuple[View, Provenance | None, str | None]:
        """A chart's axes must be columns of its dataset. Returns the view, provenance and a status note."""
        if ref is None:
            return view, None, None
        probe = ref.model_copy(update={"transform": ref.transform.model_copy(update={"limit": 50})})
        result = datasets.resolve(self.source, probe)
        names = [c.name for c in result.columns]
        numeric = [c.name for c in result.columns if c.type == "number"]
        if view.kind in ("line", "bar", "scatter", "distribution"):
            # A measured column (one with a unit) before a counter; `i`, `position` and `session` are indexes.
            measured = [c.name for c in result.columns if c.type == "number" and c.unit] or numeric
            if view.kind == "distribution":
                view.x = view.x or (measured[0] if measured else None)
                view.y = None
            else:
                if view.y is None and measured:
                    view.y = measured[0]
                if view.x is None and names:
                    view.x = next((n for n in names if n != view.y), names[0])
            for axis in ("x", "y", "series"):
                v = getattr(view, axis)
                if v is not None and v not in names:
                    raise datasets.DatasetError(f"{axis}={v!r} is not a column of {ref.dataset}: {', '.join(names)}")
            unit = next((c.unit for c in result.columns if c.name == (view.y or view.x)), None)
            view.unit = view.unit or unit
        return view, result.provenance, result.provenance.note if not result.rows else None

    def tool_create_widget(self, args: CreateWidgetArgs) -> ToolResult:
        view = args.view or View(
            kind="table" if args.type in ("table", "tests") else "metrics" if args.type == "metrics" else "text"
        )
        if args.type == "chart" and args.dataRef is None:
            return ToolResult(
                ok=False,
                tool="create_widget",
                summary="a chart needs data",
                error=ToolError(code="invalid", detail="a chart widget needs a dataRef"),
            )
        view, provenance, note = self._validate_view(args.dataRef, view)
        size = args.size or Size(w=460, h=320)
        widget = WidgetSpec(
            type=args.type,
            title=args.title,
            position=self._place(size, args.near),
            size=size,
            dataRef=args.dataRef,
            view=view,
            entity=args.entity,
            content=args.content,
            status="empty" if note else "ready",
            provenance=provenance,
            created_by="chat",  # type: ignore[arg-type]
        )
        layout = self.layout()
        self.presentation.save(
            self.source.id,
            PresentationUpdate(
                base_version=layout.version,
                widgets=[*layout.widgets, widget],
                edges=layout.edges,
                viewport=layout.viewport,
                config=layout.config,
                reason=f"chat: add {widget.type} «{widget.title[:40]}»",
            ),
        )
        self.created.append(widget.id)
        summary = f"añadido «{widget.title}»" + (f" (sin datos: {note})" if note else "")
        return ToolResult(
            ok=True,
            tool="create_widget",
            summary=summary,
            widget_id=widget.id,
            data={"status": widget.status, "note": note},
        )

    def tool_update_widget(self, args: UpdateWidgetArgs) -> ToolResult:
        layout = self.layout()
        found = next((w for w in layout.widgets if w.id == args.id), None)
        if found is None:
            return ToolResult(
                ok=False,
                tool="update_widget",
                summary="no such widget",
                error=ToolError(code="not_found", detail=f"no widget {args.id}"),
            )
        changes = []
        if args.title:
            found.title, changes = args.title, [*changes, "título"]
        if args.size:
            found.size, changes = args.size, [*changes, "tamaño"]
        if args.dataRef:
            found.dataRef, changes = args.dataRef, [*changes, "datos"]
        if args.view:
            merged = {
                **found.view.model_dump(),
                **{k: v for k, v in args.view.items() if v is not None or k in ("x", "y", "series")},
            }
            found.view, changes = View.model_validate(merged), [*changes, "vista"]
        if args.dataRef or args.view:
            found.view, prov, note = self._validate_view(found.dataRef, found.view)
            found.provenance = prov
            found.status = "empty" if note else "ready"
        if not changes:
            return ToolResult(
                ok=False,
                tool="update_widget",
                summary="nothing to change",
                error=ToolError(code="invalid", detail="no field given"),
            )
        self.presentation.save(
            self.source.id,
            PresentationUpdate(
                base_version=layout.version,
                widgets=layout.widgets,
                edges=layout.edges,
                viewport=layout.viewport,
                config=layout.config,
                reason=f"chat: update {', '.join(changes)} of «{found.title[:40]}»",
            ),
        )
        return ToolResult(
            ok=True,
            tool="update_widget",
            summary=f"actualizado {', '.join(changes)} de «{found.title}»",
            widget_id=found.id,
        )

    def tool_connect_widgets(self, args: ConnectArgs) -> ToolResult:
        layout = self.layout()
        ids = {w.id for w in layout.widgets}
        if args.source not in ids or args.target not in ids:
            return ToolResult(
                ok=False,
                tool="connect_widgets",
                summary="no such widget",
                error=ToolError(code="not_found", detail="source or target is not on the canvas"),
            )
        if args.source == args.target:
            return ToolResult(
                ok=False,
                tool="connect_widgets",
                summary="same widget",
                error=ToolError(code="invalid", detail="a widget cannot be connected to itself"),
            )
        edge = Edge(source=args.source, target=args.target, kind=args.kind, label=args.label, note=args.justification)
        self.presentation.save(
            self.source.id,
            PresentationUpdate(
                base_version=layout.version,
                widgets=layout.widgets,
                edges=[*layout.edges, edge],
                viewport=layout.viewport,
                config=layout.config,
                reason=f"chat: connect «{args.label}»",
            ),
        )
        return ToolResult(
            ok=True, tool="connect_widgets", summary=f"conectados ({args.kind}: {args.label})", edge_id=edge.id
        )

    def tool_undo_presentation(self, _: NoArgs) -> ToolResult:
        before = self.presentation.history(self.source.id)
        reasons = {r["version"]: r["reason"] for r in self.presentation.reasons(self.source.id)}
        undone = self.presentation.undo(self.source.id)
        if undone is None:
            return ToolResult(
                ok=False,
                tool="undo_presentation",
                summary="nothing to undo",
                error=ToolError(code="refused", detail="the canvas has no earlier version"),
            )
        what = reasons.get(int(before["version"]), "the last change")
        return ToolResult(ok=True, tool="undo_presentation", summary=f"deshecho: {what}")

    def tool_explain(self, args: ExplainArgs) -> ToolResult:
        store = self.source.store
        e = args.entity
        text, evidence = "", []
        if e.kind == "opportunity":
            opp = store.get("opportunities", e.id, Opportunity)
            if opp is None:
                return self._not_found("opportunity", e.id)
            d, v = opp.details.get("decision") or {}, opp.details.get("verdict") or {}
            text = (
                f"{opp.title}\n\n{opp.summary}\n\nNivel L{int(opp.evidence_level)}, estado {opp.status.value}. "
                f"Decisión: {d.get('chosen', '—')} — {d.get('reason', 'sin motivo registrado')}."
            )
            if v:
                text += (
                    f"\nVeredicto: {v.get('outcome') or ('mejoró' if v.get('improved') else 'sin mejora')}; "
                    + "; ".join(v.get("reasons") or [])
                )
            if opp.details.get("blocked"):
                text += f"\nBloqueado: {opp.details['blocked'].get('why')}"
            evidence = [x.model_dump(mode="json") for x in opp.evidence[:6]]
            events = store.events(correlation_id=opp.id, limit=50)
            text += (
                "\n\nHistorial: " + "; ".join(f"{ev.ts:%H:%M} {ev.type.value}" for ev in events[-8:]) if events else ""
            )
        elif e.kind == "block":
            block = store.get(BLOCKS, e.id, Block)
            if block is None:
                return self._not_found("block", e.id)
            text = (
                f"Bloqueo ({block.kind}) en «{block.operation}».\n\nEvidencia: {block.evidence[:400]}\n\n"
                f"Lo mínimo que lo desbloquea: {block.needs}.\nAl darlo continúa: {block.continues}."
            )
            evidence = [{"kind": "config", "locator": ".unbidden/mandate.yaml", "note": "egress.package_registries"}]
        elif e.kind == "experiment":
            exp = store.get("experiments", e.id, Experiment)
            if exp is None:
                return self._not_found("experiment", e.id)
            opp = store.get("opportunities", exp.opportunity_id, Opportunity)
            v = (opp.details.get("verdict") if opp else None) or {}
            text = (
                f"Experimento {exp.id} sobre «{opp.title if opp else exp.opportunity_id}»: "
                f"{len(exp.sessions)} sesiones, "
                f"{len(exp.control)} de control, {len(exp.confirmation)} de confirmación; coste US${exp.cost.usd:.4f}."
            )
            if v:
                text += f"\nVeredicto: {v.get('outcome', '—')} (L{v.get('evidence_level', '?')}): " + "; ".join(
                    v.get("reasons") or []
                )
            evidence = [{"kind": "experiment", "locator": exp.id}]
        else:
            conn = store._conn
            row = conn.execute("SELECT doc FROM docs WHERE collection = ? AND id = ?", (e.kind + "s", e.id)).fetchone()
            raw = json.loads(row[0]) if row else None
            if raw is None:
                return self._not_found(e.kind, e.id)
            text = json.dumps({k: raw[k] for k in list(raw)[:12]}, ensure_ascii=False, default=str)[:1500]
        return ToolResult(ok=True, tool="explain", summary=text[:200], data={"text": text, "evidence": evidence})

    def _not_found(self, kind: str, id_: str) -> ToolResult:
        return ToolResult(
            ok=False,
            tool="explain",
            summary=f"no {kind} {id_}",
            error=ToolError(code="not_found", detail=f"no {kind} with id {id_} in this workspace"),
        )


# The rule planner --------------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


KINDS = {
    "bar": ("barra", "bars", "bar"),
    "line": ("linea", "lines", "line"),
    "scatter": ("dispersion", "scatter"),
    "distribution": ("distribucion", "histograma", "histogram", "distribution"),
}

Plan = list[tuple[str, dict[str, Any]]]


class RulePlanner:
    name = "rule"

    def plan(self, text: str, rt: ToolRuntime) -> tuple[str, Plan]:
        t = _norm(text)
        if re.search(r"\b(deshaz|deshacer|undo|revierte)\b", t):
            return "Deshago el último cambio del lienzo.", [("undo_presentation", {})]
        m = re.search(r"\b(titul|renombr|rename|title)\w*\b.*?[\"'«“](.+?)[\"'»”]", t)
        if m:
            target = rt.selected_widgets()
            if not target:
                return "Selecciona la tarjeta que quieres renombrar.", []
            return "Cambio el título.", [("update_widget", {"id": target[0].id, "title": text[m.start(2) : m.end(2)]})]
        if re.search(r"\b(mas grande|agranda|amplia|bigger|larger|enlarge)\b", t) or re.search(
            r"\b(mas pequen|reduce|smaller|achica)\w*", t
        ):
            target = rt.selected_widgets() or ([rt.chart_in_context()] if rt.chart_in_context() else [])
            if not target or target[0] is None:
                return "Selecciona la tarjeta cuyo tamaño quieres cambiar.", []
            f = 1.3 if re.search(r"grande|agranda|amplia|bigger|larger|enlarge", t) else 0.75
            w = target[0]
            return "Cambio el tamaño.", [
                (
                    "update_widget",
                    {
                        "id": w.id,
                        "size": {"w": max(160, min(2400, w.size.w * f)), "h": max(80, min(2000, w.size.h * f))},
                    },
                )
            ]
        for kind, words in KINDS.items():
            if re.search(r"\b(cambia|convierte|pon|pasa|change|switch|make|turn)\b", t) and any(w in t for w in words):
                chart = rt.chart_in_context()
                if chart is None:
                    return "No hay ningún gráfico en el lienzo ni seleccionado que pueda cambiar.", []
                return f"Cambio «{chart.title}» a {kind}.", [
                    ("update_widget", {"id": chart.id, "view": {"kind": kind}})
                ]
        if re.search(r"\bcompar", t):
            exps = rt.experiments_in_context()
            if len(exps) < 2:
                return (
                    "Para comparar necesito dos ejecuciones compatibles seleccionadas (dos tarjetas de experimento "
                    "o de hallazgo con experimento). Ahora mismo tengo " + str(len(exps)) + "."
                ), []
            a, b = exps[0], exps[1]
            ref = {"dataset": "experiment.compare", "params": {"experiment_a": a.id, "experiment_b": b.id}}
            return (
                f"Comparo las sesiones de {a.id} y {b.id}: medianas por brazo y posición.",
                [
                    (
                        "create_widget",
                        {
                            "type": "chart",
                            "title": f"Comparación · {a.id[-6:]} vs {b.id[-6:]}",
                            "dataRef": ref,
                            "view": {"kind": "bar", "x": "experiment", "y": "median_ms", "series": "arm"},
                        },
                    )
                ],
            )
        if re.search(r"\b(latenc|latency|antes y despues|before and after|rendimiento)\b", t):
            exp = rt.experiment_in_context()
            if exp is None:
                return (
                    "No hay ningún experimento con muestras en este espacio: nada que graficar. Cuando el motor "
                    "ejecute uno (`unbidden try <oportunidad>`), podré mostrar sus latencias."
                ), []
            opp = rt.source.store.get("opportunities", exp.opportunity_id, Opportunity)
            title = f"Latencia antes y después · {(opp.title if opp else exp.id)[:60]}"
            return (
                f"Grafico las muestras de latencia del experimento {exp.id} por brazo.",
                [
                    (
                        "create_widget",
                        {
                            "type": "chart",
                            "title": title,
                            "dataRef": {"dataset": "experiment.samples", "params": {"experiment_id": exp.id}},
                            "view": {"kind": "distribution", "x": "ms", "series": "arm", "bins": 24},
                            "entity": {"kind": "experiment", "id": exp.id},
                        },
                    )
                ],
            )
        if re.search(r"\b(test|prueba)\w*\b.*\b(fall|fail)", t) or re.search(r"\b(fail|fall)\w*\b.*\b(test|prueba)", t):
            exp = rt.experiment_in_context()
            params = {"experiment_id": exp.id} if exp and rt.entities() else {}
            return (
                "Añado una tabla con los tests que fallaron en alguna ronda.",
                [
                    (
                        "create_widget",
                        {
                            "type": "table",
                            "title": "Tests que fallaron",
                            "dataRef": {"dataset": "tests.failed", "params": params},
                            "view": {"kind": "table", "columns": ["arm", "round", "test"]},
                        },
                    )
                ],
            )
        if re.search(r"\b(gasto|spend|coste|costo|cost|dolar|usd)\b", t):
            by = (
                "run"
                if re.search(r"\b(corrida|run|ejecuci)", t)
                else "purpose"
                if re.search(r"prop|purpose", t)
                else "model"
                if "model" in t
                else "run"
            )
            return (
                f"Grafico el gasto remoto agrupado por {by}.",
                [
                    (
                        "create_widget",
                        {
                            "type": "chart",
                            "title": f"Gasto por {by}",
                            "dataRef": {
                                "dataset": "spend.calls",
                                "transform": {
                                    "group_by": by,
                                    "aggregate": {"field": "usd", "fn": "sum"},
                                    "sort": {"field": "sum_usd", "dir": "desc"},
                                },
                            },
                            "view": {"kind": "bar", "x": by, "y": "sum_usd"},
                        },
                    )
                ],
            )
        if re.search(r"\b(bloqueo|bloqueado|block)", t):
            blocks = rt.source.store.list(BLOCKS, Block)
            selected = [e for e in rt.entities() if e.kind == "block"]
            block = next((b for b in blocks if selected and b.id == selected[0].id), blocks[0] if blocks else None)
            if block is None:
                return "No hay ningún bloqueo registrado en este espacio.", []
            plan: Plan = [("explain", {"entity": {"kind": "block", "id": block.id}})]
            if re.search(r"\b(depend|mapa|map)", t):
                plan.append(
                    (
                        "create_widget",
                        {
                            "type": "system_map",
                            "title": "Dependencias del bloqueo",
                            "dataRef": {"dataset": "world.relations"},
                            "view": {"kind": "map"},
                            "entity": {"kind": "block", "id": block.id},
                            "content": {"focus": block.operation},
                        },
                    )
                )
                anchor = next((w.id for w in rt.selected_widgets() if w.entity and w.entity.kind == "block"), None)
                if anchor:
                    plan.append(
                        (
                            "connect_widgets",
                            {
                                "source": anchor,
                                "target": "$last",
                                "kind": "trace",
                                "label": "depende de",
                                "justification": f"the block names the operation «{block.operation[:60]}»; "
                                "the map shows the resources it reaches",
                            },
                        )
                    )
            return "Explico el bloqueo" + (" y añado sus dependencias al mapa." if len(plan) > 1 else "."), plan
        m = re.search(r"\b(tabla|table|lista|list)\b.*\b(oportunidad|opportunit|hallazgo|finding)", t)
        if m:
            return (
                "Añado una tabla con las oportunidades.",
                [
                    (
                        "create_widget",
                        {
                            "type": "table",
                            "title": "Oportunidades",
                            "dataRef": {
                                "dataset": "opportunities",
                                "transform": {"sort": {"field": "level", "dir": "desc"}},
                            },
                            "view": {"kind": "table", "columns": ["title", "level", "status", "decision"]},
                        },
                    )
                ],
            )
        if re.search(r"\b(explica|explain|por que|why|que es)\b", t):
            ents = rt.entities()
            if ents:
                return "Explico lo seleccionado.", [("explain", {"entity": ents[0].model_dump()})]
            return "Selecciona una tarjeta (hallazgo, experimento, bloqueo) y te la explico con sus referencias.", []
        return (
            "No he entendido la petición. Puedo: graficar la latencia antes y después de un experimento, añadir una "
            "tabla con los tests que fallaron, graficar el gasto por corrida, explicar un bloqueo y añadir sus "
            "dependencias al mapa, cambiar un gráfico a barras/líneas, comparar dos ejecuciones seleccionadas, "
            "renombrar o redimensionar una tarjeta, y deshacer la última tarjeta."
        ), []


# Brain-backed planner ----------------------------------------------------------------------------------------

SYSTEM = """You are the assistant of Unbidden's web workspace. You answer in Spanish, briefly.
You may only act through the tools. Never invent numbers: read them with inspect_data first. If the record lacks
the data, say so and name what would produce it. A request to show something never runs an experiment, opens an
access or deploys anything. Datasets available: {catalogue}. Selected widgets: {selected}."""


class BrainPlanner:
    name = "brain"

    def __init__(self, brain: Any, model: str | None = None) -> None:
        self.brain = brain
        self.model = model

    async def run(
        self,
        text: str,
        rt: ToolRuntime,
        history: list[ChatMessage],
        emit: Emit,
        cancelled: threading.Event,
        correlation: str,
    ) -> tuple[str, list[ChatToolCall], list[ToolResult]]:
        cat = ", ".join(f"{d['id']} ({', '.join(c['name'] for c in d['fields'][:6])})" for d in datasets.catalogue())
        selected = (
            "; ".join(
                f"{w.id}: {w.type} «{w.title}»" + (f" entity {w.entity.kind}:{w.entity.id}" if w.entity else "")
                for w in rt.selected_widgets()
            )
            or "none"
        )
        messages = [Message(role="system", content=SYSTEM.format(catalogue=cat, selected=selected), source="prompt")]
        for m in history[-6:]:
            if m.role in ("user", "assistant") and m.content:
                messages.append(Message(role=m.role, content=m.content[:2000], source="prompt"))
        messages.append(Message(role="user", content=text, source="prompt"))
        calls: list[ChatToolCall] = []
        results: list[ToolResult] = []
        for _ in range(4):
            if cancelled.is_set():
                return "Cancelado antes de completar la planificación.", calls, results
            emit("state", {"state": "thinking"})
            response = await self.brain.complete(
                LLMRequest(
                    purpose="web.chat",
                    tier=Tier.LOCAL,
                    messages=messages,
                    tools=tool_specs(),
                    tool_choice="auto",
                    max_tokens=1200,
                    correlation_id=correlation,
                )
            )
            if not response.tool_calls:
                return response.content.strip() or "(sin respuesta)", calls, results
            messages.append(
                Message(
                    role="assistant", content=response.content or "", source="prompt", tool_calls=response.tool_calls
                )
            )
            for call in response.tool_calls:
                emit("state", {"state": "reading" if call.name in ("inspect_data", "explain") else "building"})
                emit("tool_call", {"id": call.id, "name": call.name, "arguments": call.arguments})
                result = rt.call(call.name, call.arguments)
                calls.append(ChatToolCall(id=call.id, name=call.name, arguments=call.arguments))
                results.append(result)
                emit("tool_result", result.model_dump(mode="json"))
                messages.append(
                    Message(
                        role="tool", content=result.model_dump_json()[:4000], source="runtime", tool_call_id=call.id
                    )
                )
        return "He aplicado las herramientas anteriores.", calls, results


# The service --------------------------------------------------------------------------------------------------


class ChatService:
    def __init__(self, presentation: PresentationStore, brain_for: Callable[[Source], Any | None]) -> None:
        self.presentation = presentation
        self.brain_for = brain_for
        self._cancel: dict[str, threading.Event] = {}
        self._phase: dict[str, str] = {}
        self.rule = RulePlanner()

    def cancel(self, source_id: str) -> dict[str, Any]:
        ev = self._cancel.get(source_id)
        phase = self._phase.get(source_id)
        if ev is None or phase in (None, "done"):
            return {"cancelled": False, "detail": "no hay ningún turno en curso"}
        ev.set()
        return {"cancelled": True, "detail": f"cancelación pedida durante: {phase}; lo ya aplicado al lienzo permanece"}

    def turn(self, source: Source, request: ChatRequest, emit: Emit) -> ChatMessage:
        cancelled = threading.Event()
        self._cancel[source.id] = cancelled
        self._phase[source.id] = "planificación"
        user = ChatMessage(role="user", content=request.content, context={"selected": request.selected})
        self.presentation.add_message(source.id, user)
        emit("message", user.model_dump(mode="json", by_alias=True))
        rt = ToolRuntime(source, self.presentation, request.selected)
        emit("state", {"state": "thinking"})
        brain = None if request.planner == "rule" else self.brain_for(source)
        planner_name: Literal["rule", "brain"] = "brain" if brain is not None else "rule"
        model = None
        try:
            if brain is not None:
                import asyncio

                planner = BrainPlanner(brain)
                history = self.presentation.messages(source.id)
                reply, calls, results = asyncio.run(
                    planner.run(request.content, rt, history, emit, cancelled, f"web:{user.id}")
                )
                run = getattr(brain, "served_by", {}).get("web.chat")
                model = run.model if run else None
            else:
                reply, plan = self.rule.plan(request.content, rt)
                calls, results = [], []
                for i, (name, args) in enumerate(plan):
                    if cancelled.is_set():
                        reply += f" Cancelado antes del paso {i + 1} de {len(plan)}; lo anterior queda aplicado."
                        break
                    self._phase[source.id] = "lectura" if name in ("inspect_data", "explain") else "construcción"
                    emit("state", {"state": "reading" if name in ("inspect_data", "explain") else "building"})
                    args = _bind(args, rt)
                    call = ChatToolCall(id=f"call_{user.id[-8:]}_{i}", name=name, arguments=args)
                    emit("tool_call", call.model_dump(mode="json"))
                    result = rt.call(name, args)
                    calls.append(call)
                    results.append(result)
                    emit("tool_result", result.model_dump(mode="json"))
                reply = _narrate(reply, results)
            state: Literal["done", "cancelled"] = "cancelled" if cancelled.is_set() else "done"
        except Exception as exc:  # the turn fails as a message, never as a dead stream
            reply, calls, results, state = f"Error: {type(exc).__name__}: {str(exc)[:300]}", [], [], "error"  # type: ignore[assignment]
            if planner_name == "brain":
                reply += " (la ruta por el modelo falló; prueba de nuevo o usa el planificador por reglas)"
        finally:
            self._phase[source.id] = "done"
        assistant = ChatMessage(
            role="assistant",
            content=reply,
            state=state,
            tool_calls=calls,
            results=results,
            planner=planner_name,
            model=model,
            context={"selected": request.selected},
        )
        self.presentation.add_message(source.id, assistant)
        emit("message", assistant.model_dump(mode="json", by_alias=True))
        emit("done", {"state": state})
        return assistant


def _bind(args: dict[str, Any], rt: ToolRuntime) -> dict[str, Any]:
    """`$last` in a planned call means the widget the previous step created."""
    out = dict(args)
    for key in ("source", "target", "near"):
        if out.get(key) == "$last":
            out[key] = rt.created[-1] if rt.created else "$none"
    return out


def _narrate(reply: str, results: list[ToolResult]) -> str:
    parts = [reply]
    for r in results:
        if r.ok:
            if r.tool == "explain" and r.data:
                parts.append(str(r.data.get("text", "")))
            else:
                parts.append(r.summary)
        else:
            err = r.error
            why = f"{err.detail}" if err else r.summary
            need = f" Para tenerlo: {err.need}." if err and err.need else ""
            parts.append(f"No se pudo ({r.tool}): {why}.{need}")
    return "\n".join(p for p in parts if p)
