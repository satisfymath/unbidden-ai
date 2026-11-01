// The inspector of the selected card: provenance, evidence, the entity's history, and the view's controls.
import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import type { DataRef, ViewKind, WidgetSpec } from "@/contracts";
import { useStore } from "@/data/store";
import { REGISTRY } from "@/widgets/registry";
import { useOpportunity } from "@/widgets/EntityWidgets";
import { EventRow } from "@/widgets/MiscWidgets";
import { EvidenceList, ProvenanceLine, fmtDate } from "@/widgets/common";

type DatasetInfo = { id: string; title: string; fields: { name: string; type: string; unit?: string | null }[]; params: string[] };

export function Inspector() {
  const open = useStore((s) => s.inspectorOpen);
  const setOpen = useStore((s) => s.setInspectorOpen);
  const selection = useStore((s) => s.selection);
  const presentation = useStore((s) => s.presentation);
  const patchWidget = useStore((s) => s.patchWidget);
  const removeWidgets = useStore((s) => s.removeWidgets);
  const api = useStore((s) => s.api);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const widget = useMemo(() => presentation?.widgets.find((w) => w.id === selection[0]) ?? null, [presentation, selection]);
  const { detail } = useOpportunity(widget?.entity?.kind === "opportunity" ? widget.entity.id : null);
  useEffect(() => {
    if (!api || datasets.length) return;
    api.datasets().then((d) => setDatasets(d.datasets as DatasetInfo[])).catch(() => undefined);
  }, [api, datasets.length]);
  if (!open || !widget) return null;
  const def = REGISTRY[widget.type];
  const ds = datasets.find((d) => d.id === widget.dataRef?.dataset);
  const fields = ds?.fields ?? [];
  const setView = (patch: Partial<WidgetSpec["view"]>) => patchWidget(widget.id, { view: { ...widget.view, ...patch } }, "cambiar vista");
  const setRef = (patch: Partial<DataRef>) => widget.dataRef && patchWidget(widget.id, { dataRef: { ...widget.dataRef, ...patch } }, "cambiar datos");
  const isChart = widget.type === "chart";
  return (
    <aside className="inspector glass glass-2" aria-label="inspector">
      <header>
        <def.icon size={16} style={{ color: "var(--accent)" }} />
        <b className="grow ellipsis">{widget.title}</b>
        <button className="btn ghost icon" onClick={() => setOpen(false)} aria-label="cerrar inspector"><X size={16} /></button>
      </header>
      <div className="body scroll">
        <section>
          <h4>Tarjeta</h4>
          <div className="col" style={{ gap: 8 }}>
            <label className="field">título<input value={widget.title} maxLength={160} onChange={(e) => patchWidget(widget.id, { title: e.target.value || widget.title }, "renombrar")} /></label>
            <div className="fields-2">
              <label className="field">ancho<input type="number" min={160} max={2400} value={Math.round(widget.size.w)} onChange={(e) => patchWidget(widget.id, { size: { ...widget.size, w: Math.max(160, Math.min(2400, Number(e.target.value))) } }, "tamaño")} /></label>
              <label className="field">alto<input type="number" min={80} max={2000} value={Math.round(widget.size.h)} onChange={(e) => patchWidget(widget.id, { size: { ...widget.size, h: Math.max(80, Math.min(2000, Number(e.target.value))) } }, "tamaño")} /></label>
            </div>
            <div className="row tiny muted">
              <span>{def.label} · {widget.created_by === "chat" ? "creada por el chat" : widget.created_by === "composer" ? "compuesta del registro" : "creada por ti"}</span>
              <span className="grow" />
              <span className={`chip ${widget.status === "ready" ? "ok" : "warn"}`}>{widget.status}</span>
            </div>
          </div>
        </section>
        {widget.dataRef ? (
          <section>
            <h4>Datos</h4>
            <div className="col" style={{ gap: 8 }}>
              <label className="field">dataset
                <select value={widget.dataRef.dataset} onChange={(e) => setRef({ dataset: e.target.value, params: {}, transform: { filter: [], limit: widget.dataRef?.transform.limit ?? 500 } })}>
                  {datasets.map((d) => <option key={d.id} value={d.id}>{d.id} — {d.title}</option>)}
                </select>
              </label>
              {Object.keys(widget.dataRef.params).length ? <div className="tiny mono muted">{Object.entries(widget.dataRef.params).map(([k, v]) => `${k}=${String(v)}`).join(" · ")}</div> : null}
              {isChart ? (
                <div className="fields-2">
                  <label className="field">tipo
                    <select value={widget.view.kind} onChange={(e) => setView({ kind: e.target.value as ViewKind })}>
                      {(["line", "bar", "scatter", "distribution"] as const).map((k) => <option key={k} value={k}>{({ line: "líneas", bar: "barras", scatter: "dispersión", distribution: "distribución" })[k]}</option>)}
                    </select>
                  </label>
                  <label className="field">serie
                    <select value={widget.view.series ?? ""} onChange={(e) => setView({ series: e.target.value || null })}>
                      <option value="">— ninguna —</option>
                      {fields.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                    </select>
                  </label>
                  <label className="field">x
                    <select value={widget.view.x ?? ""} onChange={(e) => setView({ x: e.target.value || null })}>
                      <option value="">— automático —</option>
                      {fields.map((f) => <option key={f.name} value={f.name}>{f.name}{f.unit ? ` (${f.unit})` : ""}</option>)}
                    </select>
                  </label>
                  <label className="field">y
                    <select value={widget.view.y ?? ""} onChange={(e) => setView({ y: e.target.value || null })} disabled={widget.view.kind === "distribution"}>
                      <option value="">— automático —</option>
                      {fields.filter((f) => f.type === "number").map((f) => <option key={f.name} value={f.name}>{f.name}{f.unit ? ` (${f.unit})` : ""}</option>)}
                    </select>
                  </label>
                </div>
              ) : null}
              {widget.type === "table" ? (
                <label className="field">columnas (vacío = todas)
                  <input value={(widget.view.columns ?? []).join(", ")} onChange={(e) => setView({ columns: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} placeholder={fields.map((f) => f.name).join(", ")} />
                </label>
              ) : null}
              <label className="field">límite de filas
                <input type="number" min={1} max={5000} value={widget.dataRef.transform.limit} onChange={(e) => setRef({ transform: { ...widget.dataRef!.transform, limit: Math.max(1, Math.min(5000, Number(e.target.value))) } })} />
              </label>
              <label className="field">filtros (JSON, validados en el servidor)
                <textarea defaultValue={JSON.stringify(widget.dataRef.transform.filter)} onBlur={(e) => {
                  try {
                    const f = JSON.parse(e.target.value || "[]");
                    if (Array.isArray(f)) setRef({ transform: { ...widget.dataRef!.transform, filter: f } });
                  } catch { /* the server will not see it */ }
                }} />
              </label>
            </div>
          </section>
        ) : null}
        <section>
          <h4>Procedencia</h4>
          {widget.provenance ? (
            <div className="col" style={{ gap: 6 }}>
              <ProvenanceLine provenance={widget.provenance} />
              {widget.provenance.note ? <div className="small ink2">{widget.provenance.note}</div> : null}
              <div className="tiny muted">fuente {widget.provenance.source} · observado {fmtDate(widget.provenance.observed_at)}</div>
            </div>
          ) : (
            <div className="tiny muted">Sin procedencia registrada: esta tarjeta no apunta a un dataset.</div>
          )}
        </section>
        {widget.entity ? (
          <section>
            <h4>Entidad</h4>
            <div className="tiny mono muted" style={{ marginBottom: 6 }}>{widget.entity.kind}: {widget.entity.id}</div>
            {detail ? (
              <>
                <EvidenceList items={(detail.opportunity.evidence ?? []) as { kind: string; locator: string; note?: string | null }[]} />
                <div className="col" style={{ marginTop: 8, gap: 0 }}>
                  <div className="tiny muted" style={{ marginBottom: 4 }}>Historial ({detail.events.length} eventos)</div>
                  {detail.events.slice(-12).reverse().map((e, i) => (
                    <EventRow key={i} e={{ seq: null, ts: e.ts, type: e.type, actor: "", payload: e.payload }} />
                  ))}
                </div>
              </>
            ) : null}
          </section>
        ) : null}
        {widget.type === "note" ? (
          <section>
            <h4>Texto</h4>
            <textarea className="field" style={{ width: "100%" }} defaultValue={String(widget.content.text ?? "")} onBlur={(e) => patchWidget(widget.id, { content: { text: e.target.value.slice(0, 4000) } }, "editar nota")} />
          </section>
        ) : null}
        <section>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn sm" onClick={() => patchWidget(widget.id, { pinned: !widget.pinned }, "fijar")}>{widget.pinned ? "Desfijar" : "Fijar"}</button>
            <button className="btn sm danger" disabled={widget.pinned} onClick={() => removeWidgets([widget.id])}>Quitar del lienzo</button>
          </div>
          <div className="tiny muted" style={{ marginTop: 6 }}>Quitar una tarjeta no elimina ningún experimento ni registro del motor.</div>
        </section>
      </div>
    </aside>
  );
}
