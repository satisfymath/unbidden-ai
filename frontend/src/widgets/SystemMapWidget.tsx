// The world model as columns by kind with evidence-backed relations between them. Every line here comes from a
// `Relation` of the engine's world model; nothing is inferred by the browser.
import { useEffect, useMemo, useRef, useState } from "react";
import type { WidgetSpec } from "@/contracts";
import { useDataRef } from "./useData";
import { Empty, Loading } from "./common";

const ORDER = ["repo", "ci_job", "service", "container", "image", "deployment", "api", "endpoint", "database", "table", "model", "metrics"];
const KIND_LABEL: Record<string, string> = { repo: "repositorio", ci_job: "CI", service: "servicio", container: "contenedor", image: "imagen", deployment: "despliegue", api: "API", endpoint: "endpoint", database: "base de datos", table: "tabla", model: "modelo", metrics: "métricas" };

function kindOf(id: string) {
  return id.split(":", 1)[0] ?? "resource";
}

export function SystemMapWidget({ widget }: { widget: WidgetSpec }) {
  const { result, loading, error } = useDataRef(widget.dataRef ?? { dataset: "world.relations", params: {}, transform: { filter: [], limit: 500 } });
  const [hover, setHover] = useState<string | null>(null);
  const [width, setWidth] = useState(520);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => entry && setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const focus = typeof widget.content.focus === "string" ? widget.content.focus.toLowerCase() : null;
  const layout = useMemo(() => {
    if (!result) return null;
    const ids = new Set<string>();
    for (const r of result.rows) {
      ids.add(String(r.src));
      ids.add(String(r.dst));
    }
    const kinds = [...new Set([...ids].map(kindOf))].sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99));
    const colW = Math.max(118, Math.min(170, Math.floor((width - 24) / Math.max(1, kinds.length))));
    const rowH = 32;
    const pos = new Map<string, { x: number; y: number; w: number }>();
    let maxRows = 0;
    kinds.forEach((k, ci) => {
      const members = [...ids].filter((id) => kindOf(id) === k).sort();
      maxRows = Math.max(maxRows, members.length);
      members.forEach((id, ri) => pos.set(id, { x: 12 + ci * colW, y: 30 + ri * rowH, w: colW - 22 }));
    });
    return { kinds, pos, width: 12 + kinds.length * colW, height: 40 + maxRows * rowH, colW };
  }, [result, width]);
  if (error) return <Empty kind="bad" title="No se pudo leer el mapa" detail={error} />;
  if (loading && !result) return <Loading />;
  if (!result || !layout || !result.rows.length) return <Empty kind="warn" title="Sin mapa del sistema" detail={result?.provenance.note ?? "El motor no ha construido un modelo del mundo aquí (unbidden map)."} />;
  const name = (id: string) => id.slice(id.indexOf(":") + 1);
  const related = new Set<string>();
  if (hover) for (const r of result.rows) if (r.src === hover || r.dst === hover) related.add(String(r.src)).add(String(r.dst));
  return (
    <div className="map-wrap nowheel nodrag scroll" ref={wrap} style={{ height: "100%", overflow: "auto", position: "relative" }}>
      <svg width={layout.width} height={layout.height} style={{ display: "block", minWidth: "100%" }} role="img" aria-label="mapa del sistema">
        {layout.kinds.map((k, ci) => (
          <text key={k} x={12 + ci * layout.colW} y={16} fill="#8ba1b8" fontSize={10.5} style={{ textTransform: "uppercase", letterSpacing: 1 }}>
            {KIND_LABEL[k] ?? k}
          </text>
        ))}
        {result.rows.map((r, i) => {
          const a = layout.pos.get(String(r.src));
          const b = layout.pos.get(String(r.dst));
          if (!a || !b) return null;
          const x1 = a.x + a.w;
          const y1 = a.y + 12;
          const x2 = b.x;
          const y2 = b.y + 12;
          const left = x2 < x1;
          const sx = left ? a.x : x1;
          const tx = left ? b.x + b.w : x2;
          const dx = Math.max(30, Math.abs(tx - sx) / 2);
          const d = `M ${sx} ${y1} C ${sx + (left ? -dx : dx)} ${y1}, ${tx + (left ? dx : -dx)} ${y2}, ${tx} ${y2}`;
          const active = hover && (r.src === hover || r.dst === hover);
          const dim = hover && !active;
          const inferred = r.status === "inferred" || r.status === "hypothesis";
          return (
            <g key={i} opacity={dim ? 0.15 : 1}>
              <path d={d} fill="none" stroke={active ? "#3fd8c7" : "rgba(108,176,255,0.55)"} strokeWidth={active ? 2 : 1.2} strokeDasharray={inferred ? "4 4" : undefined} />
              {active ? (
                <text x={(sx + tx) / 2} y={(y1 + y2) / 2 - 4} fill="#3fd8c7" fontSize={10} textAnchor="middle">
                  {String(r.predicate)}
                </text>
              ) : null}
            </g>
          );
        })}
        {[...layout.pos.entries()].map(([id, p]) => {
          const hit = focus && (id.toLowerCase().includes(focus) || focus.includes(name(id).toLowerCase()));
          const active = hover === id || related.has(id);
          return (
            <g key={id} transform={`translate(${p.x},${p.y})`} onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)} style={{ cursor: "default" }}>
              <rect width={p.w} height={24} rx={7} fill={active ? "rgba(63,216,199,0.18)" : hit ? "rgba(243,184,70,0.18)" : "rgba(12,30,52,0.9)"} stroke={active ? "#3fd8c7" : hit ? "#f3b846" : "rgba(146,184,222,0.3)"} />
              <text x={9} y={16} fill="#e8f0f8" fontSize={11.5} fontFamily="var(--mono)">
                {name(id).length > Math.floor(p.w / 7.2) ? name(id).slice(0, Math.floor(p.w / 7.2) - 1) + "…" : name(id)}
                <title>{id}</title>
              </text>
            </g>
          );
        })}
      </svg>
      <div className="tiny muted" style={{ position: "sticky", bottom: 0, left: 0, padding: "4px 8px", background: "var(--glass-solid)" }}>
        {result.rows.length} relación(es) con evidencia · línea discontinua: inferida · pasa el cursor para ver el predicado
      </div>
    </div>
  );
}
