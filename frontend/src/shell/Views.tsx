// The secondary views: Experimentos (the opportunities with their experiments) and Actividad (events, spend,
// the closed run's cycles). Both read the same contracts as the canvas; both can put a card on the canvas.
import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Plus } from "lucide-react";
import { useStore } from "@/data/store";
import { LevelChip, StatusChip, fmtDate, fmtNum, fmtTime } from "@/widgets/common";
import { EventRow } from "@/widgets/MiscWidgets";
import { FindingWidget, ExperimentWidget } from "@/widgets/EntityWidgets";
import type { WidgetSpec } from "@/contracts";

type Opp = { id: string; title: string; status: string; evidence_level: number; source: string; category: string; decision: { chosen?: string; reason?: string }; blocked?: string | null; experiment_id?: string | null; created_at: string };

export function ExperimentsView() {
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const lastSeq = useStore((s) => s.lastSeq);
  const addWidget = useStore((s) => s.addWidget);
  const presentation = useStore((s) => s.presentation);
  const focus = useStore((s) => s.focus);
  const [items, setItems] = useState<Opp[]>([]);
  const [total, setTotal] = useState(0);
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    if (!api || !ws) return;
    api.opportunities(ws, 0, 200).then((r) => { setItems(r.items as Opp[]); setTotal(r.total); }).catch(() => undefined);
  }, [api, ws, lastSeq]);
  const current = items.find((o) => o.id === active) ?? items[0] ?? null;
  const onCanvas = (id: string) => presentation?.widgets.find((w) => w.entity?.id === id)?.id ?? null;
  const addToCanvas = (o: Opp, type: "finding" | "experiment") => {
    const existing = presentation?.widgets.find((w) => w.entity?.id === o.id && w.type === type)?.id;
    if (existing) return focus(existing);
    const id = addWidget({ type, title: type === "finding" ? (o.evidence_level >= 4 ? "Hallazgo validado" : "Hallazgo") : "Experimento", entity: { kind: "opportunity", id: o.id }, created_by: "user" });
    focus(id);
  };
  const fake = (o: Opp, type: "finding" | "experiment"): WidgetSpec => ({ schema: 1, id: `preview_${o.id}`, type, title: "", position: { x: 0, y: 0 }, size: { w: 400, h: 300 }, pinned: false, z: 0, view: { kind: "text", options: {} }, status: "ready", content: {}, created_by: "user", entity: { kind: "opportunity", id: o.id } });
  return (
    <div className="view">
      <div className="pane glass glass-2" style={{ flex: 1.3 }}>
        <header>Experimentos y hallazgos <span className="muted" style={{ fontWeight: 400 }}>· {total} oportunidades, ordenadas por evidencia</span></header>
        <div className="body scroll">
          {items.map((o) => (
            <button key={o.id} className={`list-row ${current?.id === o.id ? "active" : ""}`} onClick={() => setActive(o.id)}>
              <LevelChip level={o.evidence_level} />
              <span className="col" style={{ gap: 2, minWidth: 0 }}>
                <span className="ellipsis">{o.title}</span>
                <span className="tiny muted ellipsis">{o.source} · {o.category} · {o.decision?.chosen ?? "sin decisión"}{o.blocked ? " · bloqueada" : ""} · {fmtDate(o.created_at)}</span>
              </span>
              <StatusChip status={o.status} />
              <span className={`chip ${onCanvas(o.id) ? "accent" : "muted"}`}>{onCanvas(o.id) ? "en el lienzo" : "—"}</span>
            </button>
          ))}
          {!items.length ? <div className="state"><b>Sin oportunidades</b>Nada descubierto en este registro todavía.</div> : null}
        </div>
      </div>
      <div className="pane glass glass-2" style={{ flex: 1 }}>
        <header>
          <span className="grow ellipsis">{current ? current.title : "Detalle"}</span>
          {current ? (
            <>
              <button className="btn sm" onClick={() => addToCanvas(current, "finding")}><Plus size={12} /> hallazgo al lienzo</button>
              <button className="btn sm" onClick={() => addToCanvas(current, "experiment")}><Plus size={12} /> experimento al lienzo</button>
            </>
          ) : null}
        </header>
        <div className="body scroll col" style={{ padding: 10, gap: 12 }}>
          {current ? (
            <>
              <div className="glass" style={{ height: 300, display: "flex", flexDirection: "column" }}><FindingWidget widget={fake(current, "finding")} /></div>
              <div className="glass" style={{ height: 320, display: "flex", flexDirection: "column" }}><ExperimentWidget widget={fake(current, "experiment")} /></div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ActivityView() {
  const events = useStore((s) => s.events);
  const summary = useStore((s) => s.summary);
  const markSeen = useStore((s) => s.markSeen);
  const focus = useStore((s) => s.focus);
  const stream = useStore((s) => s.stream);
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const [timeline, setTimeline] = useState<{ ts: string | null; cycle: number; text: string; kind: string }[]>([]);
  const [filter, setFilter] = useState("");
  const parent = useRef<HTMLDivElement>(null);
  useEffect(() => { markSeen(); }, [events.length, markSeen]);
  useEffect(() => {
    if (!api || !ws || !summary?.timeline_lines) return;
    api.timeline(ws, 0, 2000).then((t) => setTimeline(t.items)).catch(() => undefined);
  }, [api, ws, summary?.timeline_lines]);
  const list = useMemo(() => {
    const rev = [...events].reverse();
    return filter ? rev.filter((e) => e.type.includes(filter) || JSON.stringify(e.payload).toLowerCase().includes(filter.toLowerCase())) : rev;
  }, [events, filter]);
  const virt = useVirtualizer({ count: list.length, getScrollElement: () => parent.current, estimateSize: () => 46, overscan: 12 });
  const a = (summary?.activity ?? {}) as { spent?: { calls: number; usd: number; basis: string }; discovered?: { total: number; by_status: Record<string, number> }; declined_because?: [string, number][]; waiting_because?: [string, number][]; learned?: Record<string, { p: number; successes: number; failures: number }> };
  const types = useMemo(() => [...new Set(events.map((e) => e.type))].sort(), [events]);
  return (
    <div className="view">
      <div className="pane glass glass-2" style={{ flex: 1.4 }}>
        <header>
          <span className="grow">Actividad en vivo <span className="muted" style={{ fontWeight: 400 }}>· {summary?.counts.events ?? 0} eventos · {({ live: "en vivo", stale: "desactualizado", disconnected: "desconectado", connecting: "conectando", closed: "cerrado" } as Record<string, string>)[stream] ?? stream}</span></span>
          <select className="field" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="filtrar por tipo" style={{ background: "rgba(243,241,236,0.08)", border: "1px solid var(--line)", borderRadius: 8, padding: "4px 8px", color: "var(--ink)" }}>
            <option value="">todos los tipos</option>
            {types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </header>
        <div className="body scroll" ref={parent}>
          <div style={{ height: virt.getTotalSize(), position: "relative" }}>
            {virt.getVirtualItems().map((v) => {
              const e = list[v.index];
              if (!e) return null;
              return (
                <div key={e.seq ?? v.index} style={{ position: "absolute", top: v.start, left: 0, right: 0, padding: "0 8px" }}>
                  <EventRow e={e} onClick={() => e.correlation_id && focus(`c_finding_${e.correlation_id}`)} />
                </div>
              );
            })}
          </div>
          {!list.length ? <div className="state"><b>Sin eventos</b>{summary?.workspace.mode === "historical" ? "El registro publicado no incluye la tabla de eventos; mira los ciclos a la derecha." : "Nada registrado todavía."}</div> : null}
        </div>
      </div>
      <div className="pane glass glass-2" style={{ flex: 1 }}>
        <header>Resumen del registro</header>
        <div className="body scroll col" style={{ padding: 14, gap: 14 }}>
          <section>
            <div className="tiny muted" style={{ marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>Descubierto</div>
            <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
              <span className="chip">{a.discovered?.total ?? 0} total</span>
              {Object.entries(a.discovered?.by_status ?? {}).map(([k, v]) => <span key={k} className="chip muted">{v} {k}</span>)}
            </div>
          </section>
          <section>
            <div className="tiny muted" style={{ marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>Gasto remoto</div>
            <div className="small">US$ {fmtNum(a.spent?.usd ?? 0)} en {a.spent?.calls ?? 0} llamada(s) <span className="tiny muted">· {a.spent?.basis ?? ""}</span></div>
          </section>
          {(a.declined_because?.length || a.waiting_because?.length) ? (
            <section>
              <div className="tiny muted" style={{ marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>Por qué descartó o espera</div>
              {[...(a.declined_because ?? []).map((x) => ["descartó", ...x] as const), ...(a.waiting_because ?? []).map((x) => ["espera", ...x] as const)].map(([k, reason, n], i) => (
                <div key={i} className="row small" style={{ alignItems: "flex-start", gap: 8, padding: "3px 0" }}>
                  <span className={`chip ${k === "espera" ? "warn" : "muted"}`}>{n} {k}</span>
                  <span className="ink2" style={{ lineHeight: 1.35 }}>{String(reason).slice(0, 200)}</span>
                </div>
              ))}
            </section>
          ) : null}
          {a.learned && Object.keys(a.learned).length ? (
            <section>
              <div className="tiny muted" style={{ marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>Aprendido (p de éxito; prior 0.6)</div>
              {Object.entries(a.learned).map(([k, v]) => <div key={k} className="row small"><span className="grow ellipsis">{k}</span><b>{v.p}</b><span className="tiny muted">{v.successes} ok · {v.failures} no</span></div>)}
            </section>
          ) : null}
          {timeline.length ? (
            <section>
              <div className="tiny muted" style={{ marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>Ciclos de la corrida (histórico)</div>
              <div className="col" style={{ gap: 2 }}>
                {timeline.slice(0, 400).map((t, i) => t.kind === "cycle" ? <div key={i} className="tiny muted" style={{ paddingTop: 6 }}>{t.text}</div> : <div key={i} className="row tiny" style={{ alignItems: "flex-start" }}><span className="mono muted" style={{ width: 44, flex: "none" }}>{t.ts ? fmtTime(t.ts) : ""}</span><span className="ink2">{t.text.slice(0, 220)}</span></div>)}
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
