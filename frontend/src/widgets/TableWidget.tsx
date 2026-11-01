// A table over a dataset: virtualised rows, chosen columns, numbers right-aligned, the cap stated.
import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { DataResult, WidgetSpec } from "@/contracts";
import { useDataRef } from "./useData";
import { DataFrame, Empty, Loading, fmtDate, fmtNum, StatusChip } from "./common";

const ROW = 28;

function cell(v: unknown, type: string, name: string) {
  if (v == null) return <span className="muted">—</span>;
  if (type === "number") return fmtNum(v);
  if (type === "datetime") return fmtDate(String(v));
  if (type === "boolean") return v ? "sí" : "no";
  if (type === "json") return <span className="mono muted" title={JSON.stringify(v)}>{Array.isArray(v) ? `${v.length} ítem(s)` : "{…}"}</span>;
  const s = String(v);
  if (name === "status" || name === "state") return <StatusChip status={s} />;
  return <span title={s}>{s.length > 80 ? s.slice(0, 80) + "…" : s}</span>;
}

export function TableBody({ widget, result }: { widget: WidgetSpec; result: DataResult }) {
  const wanted = widget.view.columns?.length ? widget.view.columns : result.columns.map((c) => c.name);
  const columns = result.columns.filter((c) => wanted.includes(c.name));
  const parent = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: result.rows.length, getScrollElement: () => parent.current, estimateSize: () => ROW, overscan: 10 });
  return (
    <div className="table-wrap nowheel nodrag" ref={parent} style={{ height: "100%", overflow: "auto" }}>
      <table className="data" style={{ tableLayout: "fixed" }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.name} className={c.type === "number" ? "num" : ""} title={c.unit ? `${c.name} (${c.unit})` : c.name}>
                {c.name}
                {c.unit ? <span className="muted"> · {c.unit}</span> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody style={{ position: "relative" }}>
          {virt.getVirtualItems().length ? (
            <tr style={{ height: virt.getVirtualItems()[0]?.start ?? 0 }} aria-hidden="true">
              <td colSpan={columns.length} style={{ padding: 0, border: 0 }} />
            </tr>
          ) : null}
          {virt.getVirtualItems().map((v) => {
            const row = result.rows[v.index];
            if (!row) return null;
            return (
              <tr key={v.index} style={{ height: ROW }}>
                {columns.map((c) => (
                  <td key={c.name} className={c.type === "number" ? "num" : "ellipsis"} style={{ maxWidth: 240 }}>
                    {cell(row[c.name], c.type, c.name)}
                  </td>
                ))}
              </tr>
            );
          })}
          <tr style={{ height: Math.max(0, virt.getTotalSize() - ((virt.getVirtualItems().at(-1)?.end ?? 0) || 0)) }} aria-hidden="true">
            <td colSpan={columns.length} style={{ padding: 0, border: 0 }} />
          </tr>
        </tbody>
      </table>
      <div className="tiny muted" style={{ padding: "4px 8px", position: "sticky", bottom: 0, background: "var(--glass-solid)" }}>
        {result.rows.length} fila(s){result.total != null && result.total > result.rows.length ? ` de ${result.total} (límite ${result.provenance.limit ?? result.rows.length})` : ""}
      </div>
    </div>
  );
}

export function TableWidget({ widget }: { widget: WidgetSpec }) {
  const { result, loading, error } = useDataRef(widget.dataRef);
  if (!widget.dataRef) return <Empty kind="warn" title="Tabla sin datos" detail="Esta tabla no tiene una referencia de datos." />;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (loading && !result) return <Loading />;
  if (!result || !result.rows.length) return <Empty kind="warn" title="Sin filas" detail={result?.provenance.note ?? "El registro no tiene filas para esta referencia."} />;
  return <DataFrame widget={widget} result={result}><TableBody widget={widget} result={result} /></DataFrame>;
}
