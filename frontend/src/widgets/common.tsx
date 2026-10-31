// Pieces every widget shares: states, provenance, level chips, time formatting. Text from the record is rendered
// as text (React escapes it); nothing here injects HTML.
import type { ReactNode } from "react";
import type { Provenance } from "@/contracts";
import { AlertTriangle, Clock, Database, FlaskConical, Info } from "lucide-react";

export const LEVELS: Record<number, string> = { 1: "sospecha", 2: "reproducido", 3: "lab", 4: "validado", 5: "operativo", 6: "persistente" };

export function LevelChip({ level }: { level: number }) {
  const cls = level >= 4 ? "ok" : level >= 2 ? "info" : "muted";
  return (
    <span className={`chip ${cls}`} title={`Nivel de evidencia ${level}: ${LEVELS[level] ?? ""}`}>
      L{level} {LEVELS[level] ?? ""}
    </span>
  );
}

export function StatusChip({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    open: ["info", "abierta"],
    experimenting: ["info", "experimentando"],
    proposed: ["ok", "propuesta"],
    declined: ["muted", "descartada"],
    verified: ["ok", "verificada"],
    closed: ["muted", "cerrada"],
    ready: ["ok", "lista"],
    pr_opened: ["info", "PR abierto"],
    merged: ["ok", "fusionado"],
    stale: ["warn", "desactualizada"],
    rejected: ["bad", "rechazada"],
    connected: ["ok", "conectada"],
    degraded: ["warn", "degradada"],
    revoked: ["bad", "revocada"],
    discovered: ["muted", "descubierta"],
    needs_authorization: ["warn", "sin autorización"],
    needs_configuration: ["warn", "sin configurar"],
    needs_capability: ["warn", "sin integración"],
    gone: ["bad", "desaparecida"],
    awaiting_approval: ["warn", "pendiente de aprobar"],
    in_use: ["ok", "en uso"],
    blocked: ["warn", "bloqueada"],
    failed: ["bad", "falló"],
    passed: ["ok", "pasó"],
    infra_failed: ["bad", "infra falló"],
    not_collected: ["warn", "sin tests"],
    ran: ["ok", "ejecutada"],
    accepted: ["ok", "aceptado"],
    inconclusive: ["warn", "inconcluso"],
  };
  const [cls, label] = map[status] ?? ["muted", status];
  return <span className={`chip ${cls}`}>{label}</span>;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtNum(v: unknown, unit?: string | null): string {
  if (typeof v !== "number") return v == null ? "—" : String(v);
  const s = Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(v === Math.round(v) ? 0 : 2);
  return unit ? `${s} ${unit}` : s;
}

export function Empty({ kind = "info", title, detail, icon }: { kind?: "info" | "warn" | "bad"; title: string; detail?: string | null; icon?: ReactNode }) {
  return (
    <div className={`state ${kind}`} role="status">
      <span style={{ opacity: 0.8 }}>{icon ?? (kind === "info" ? <Info size={18} /> : <AlertTriangle size={18} />)}</span>
      <b>{title}</b>
      {detail ? <span style={{ maxWidth: 360 }}>{detail}</span> : null}
    </div>
  );
}

export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <div className="col" style={{ padding: 12, gap: 8 }} aria-busy="true" aria-label="cargando">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 14, width: `${85 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function ProvenanceLine({ provenance, extra }: { provenance: Provenance | null | undefined; extra?: ReactNode }) {
  if (!provenance) return null;
  const fresh: Record<string, [string, string]> = {
    current: ["ok", "actual"],
    historical: ["muted", "histórico"],
    demo: ["warn", "demostración"],
    stale: ["bad", "desactualizado"],
  };
  const [cls, label] = fresh[provenance.freshness] ?? ["muted", provenance.freshness];
  return (
    <div className="prov row tiny muted" title={provenance.note ?? undefined}>
      <span className={`chip ${cls}`} style={{ padding: "0 7px" }}>
        {label}
      </span>
      {provenance.scope ? (
        <span className="ellipsis" style={{ maxWidth: 160 }}>
          <Database size={11} style={{ verticalAlign: -1, marginRight: 3 }} />
          {provenance.scope}
        </span>
      ) : null}
      <span>
        <Clock size={11} style={{ verticalAlign: -1, marginRight: 3 }} />
        {fmtDate(provenance.observed_at)}
      </span>
      {provenance.completeness === "partial" ? <span className="chip warn" style={{ padding: "0 7px" }}>parcial · límite {provenance.limit}</span> : null}
      {provenance.completeness === "missing" ? <span className="chip bad" style={{ padding: "0 7px" }}>sin datos</span> : null}
      {extra}
    </div>
  );
}

/** A data widget's body plus the provenance of what it actually fetched (mode, scope, time, completeness). */
export function DataFrame({ widget, result, children }: { widget: { dataRef?: { dataset: string } | null }; result: { provenance: Provenance }; children: ReactNode }) {
  return (
    <div className="col" style={{ height: "100%", gap: 0 }}>
      <div className="grow" style={{ minHeight: 0, position: "relative" }}>{children}</div>
      <div className="widget-foot">
        <ProvenanceLine provenance={result.provenance} extra={widget.dataRef ? <span className="mono ellipsis" style={{ maxWidth: 150 }} title={widget.dataRef.dataset}>{widget.dataRef.dataset}</span> : null} />
      </div>
    </div>
  );
}

export function EvidenceList({ items }: { items: { kind: string; locator: string; note?: string | null }[] }) {
  if (!items.length) return <span className="muted small">sin referencias de evidencia</span>;
  return (
    <ul className="evidence">
      {items.map((e, i) => (
        <li key={i} className="row small" style={{ gap: 6, alignItems: "flex-start" }}>
          <FlaskConical size={12} style={{ marginTop: 3, color: "var(--accent)", flex: "none" }} />
          <span className="mono ellipsis" title={e.locator} style={{ color: "var(--ink-2)" }}>
            {e.kind}: {e.locator}
          </span>
          {e.note ? <span className="muted ellipsis" style={{ maxWidth: 160 }}>· {e.note}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k} className="kv-row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
