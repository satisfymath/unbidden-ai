// Budget, permissions and configuration: read from the mandate and the ledger; the kill switch is the one action.
import { useEffect, useRef, useState } from "react";
import { Power, X } from "lucide-react";
import { useStore } from "@/data/store";
import { fmtNum } from "@/widgets/common";

export function SettingsPopover() {
  const summary = useStore((s) => s.summary);
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const setSettingsOpen = useStore((s) => s.setSettingsOpen);
  const toast = useStore((s) => s.toast);
  const refreshSummary = useStore((s) => s.refreshSummary);
  const presentation = useStore((s) => s.presentation);
  const setConfig = useStore((s) => s.setConfig);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && !(e.target as HTMLElement).closest(".topbar .status") && setSettingsOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setSettingsOpen(false);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [setSettingsOpen]);
  if (!summary) return null;
  const route = summary.connection.route;
  const a = summary.connection.autonomy;
  const spent = (summary.activity.spent ?? {}) as { calls?: number; usd?: number; basis?: string };
  const cap = a.spend_cap_usd ?? null;
  const live = summary.workspace.mode === "live";
  const kill = async (op: "kill" | "resume") => {
    if (!api || !ws) return;
    if (op === "kill" && !window.confirm("Activar el kill switch: ningún job arranca y ningún modelo se llama hasta liberarlo. ¿Continuar?")) return;
    setBusy(true);
    try {
      const r = await api.action(ws, { operation: op, reason: op === "kill" ? "desde el espacio web" : null, idempotency_key: `${op}-${Date.now()}`, expected_revision: summary.workspace.head?.slice(0, 12) ?? null });
      toast(r.detail, r.effect === "done" ? "ok" : r.effect === "not_supported_here" ? "warn" : "info");
      await refreshSummary();
    } catch (e) {
      toast(String(e), "bad");
    } finally {
      setBusy(false);
    }
  };
  const fields = Object.entries(a.fields ?? {});
  return (
    <div className="popover" ref={ref} role="dialog" aria-label="presupuesto, permisos y configuración" style={{ top: 62, right: 0 }}>
      <div className="row" style={{ marginBottom: 8 }}>
        <b className="grow">{summary.workspace.name}</b>
        <button className="btn ghost icon" onClick={() => setSettingsOpen(false)} aria-label="cerrar">
          <X size={14} />
        </button>
      </div>
      <section>
        <h4>Dónde corre cada cosa</h4>
        <div className="col small" style={{ gap: 4 }}>
          <div className="row"><span className="muted" style={{ width: 110 }}>Servidor</span><span>este equipo (loopback)</span></div>
          <div className="row"><span className="muted" style={{ width: 110 }}>Modelo local</span><span className="mono ellipsis">{route.local.model ?? "—"} <span className="muted">· {route.local.provider} · {route.local.reachable ? "responde" : "no responde"}</span></span></div>
          <div className="row"><span className="muted" style={{ width: 110 }}>Modelo remoto</span><span className="mono ellipsis">{route.remote.model ?? "—"} <span className="muted">· {route.remote.provider} · {route.remote.key_present ? "clave cargada" : route.remote.credential_file_present ? "archivo .env presente, clave no cargada" : "sin credencial"}</span></span></div>
          <div className="row"><span className="muted" style={{ width: 110 }}>Perfil</span><span>{route.profile}{route.local_inference === "deny" ? " · sin inferencia local" : ""}</span></div>
          <div className="tiny muted">{route.note}</div>
        </div>
      </section>
      <section>
        <h4>Presupuesto</h4>
        <div className="row small">
          <span className="grow">Gastado en este workspace</span>
          <b>US$ {fmtNum(spent.usd ?? 0)}</b>
          <span className="muted">· {spent.calls ?? 0} llamadas</span>
        </div>
        {cap != null ? (
          <>
            <div style={{ height: 6, borderRadius: 4, background: "rgba(243,241,236,0.12)", marginTop: 6 }}>
              <div style={{ height: 6, borderRadius: 4, width: `${Math.min(100, ((spent.usd ?? 0) / Math.max(cap, 0.0001)) * 100)}%`, background: "var(--accent)" }} />
            </div>
            <div className="tiny muted" style={{ marginTop: 4 }}>tope mensual del mandato US$ {fmtNum(cap)} · {spent.basis ?? ""}</div>
          </>
        ) : null}
      </section>
      <section>
        <h4>Permisos (mandato · autonomía {a.level})</h4>
        <div className="col tiny" style={{ gap: 3 }}>
          {fields.map(([k, v]) => (
            <div key={k} className="row">
              <span className="muted grow mono">{k}</span>
              <span className={`chip ${v === "allow" ? "ok" : v === "require_approval" ? "warn" : "muted"}`} style={{ padding: "0 7px" }}>{v}</span>
            </div>
          ))}
          {!fields.length ? <span className="muted">{a.detail ?? "sin mandato"}</span> : null}
        </div>
      </section>
      <section>
        <h4>Control</h4>
        <div className="row" style={{ gap: 8 }}>
          {summary.connection.kill_switch ? (
            <button className="btn primary" disabled={busy || !live} onClick={() => void kill("resume")}><Power size={14} /> Liberar kill switch</button>
          ) : (
            <button className="btn danger" disabled={busy || !live} onClick={() => void kill("kill")}><Power size={14} /> Kill switch</button>
          )}
          {!live ? <span className="tiny muted">solo sobre un workspace vivo; aquí: {summary.workspace.mode}</span> : <span className="tiny muted">el mismo archivo que `unbidden kill`</span>}
        </div>
      </section>
      <section>
        <h4>Lienzo</h4>
        <label className="row small"><input type="checkbox" checked={presentation?.config.auto_add ?? true} onChange={(e) => setConfig({ auto_add: e.target.checked })} /> Proponer tarjetas nuevas cuando llegan eventos (nunca mueve las tuyas)</label>
        <label className="row small"><input type="checkbox" checked={presentation?.config.reduced_motion ?? false} onChange={(e) => setConfig({ reduced_motion: e.target.checked })} /> Reducir movimiento</label>
      </section>
    </div>
  );
}
