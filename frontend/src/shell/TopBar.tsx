import { useEffect, useRef, useState } from "react";
import { Activity, Beaker, ChevronDown, LayoutDashboard, Settings } from "lucide-react";
import { Wordmark } from "@/components/Logo";
import { useStore, type Tab } from "@/data/store";
import { SettingsPopover } from "./Settings";

const MODE_LABEL: Record<string, string> = {
  demo: "Demostración · datos ficticios",
  historical: "Histórico · corrida cerrada",
  live: "Vivo · lectura del workspace",
};

export function TopBar() {
  const summary = useStore((s) => s.summary);
  const sources = useStore((s) => s.sources);
  const ws = useStore((s) => s.ws);
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const stream = useStore((s) => s.stream);
  const settingsOpen = useStore((s) => s.settingsOpen);
  const setSettingsOpen = useStore((s) => s.setSettingsOpen);
  const selectWorkspace = useStore((s) => s.selectWorkspace);
  const newSince = useStore((s) => s.newSince);
  const [wsMenu, setWsMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!wsMenu) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setWsMenu(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [wsMenu]);

  const mode = summary?.workspace.mode ?? "demo";
  const autonomy = summary?.connection.autonomy.level ?? "—";
  const autonomyLabel = ({ supervised: "Supervisado", autonomous: "Autónomo", "observe-only": "Solo observa", unknown: "Sin mandato" } as Record<string, string>)[autonomy] ?? autonomy;
  const route = summary?.connection.route;
  const inferLabel = route ? (route.local_inference === "deny" ? `Meta API (${route.remote.model ?? "?"})` : `local ${route.local.model ?? ""}`.trim()) : "";
  const dot = summary?.connection.kill_switch ? "bad" : mode === "live" ? (stream === "live" ? "ok" : stream === "stale" || stream === "connecting" ? "warn" : "bad") : mode === "demo" ? "warn" : "muted";
  const tabs: [Tab, string, typeof Activity][] = [
    ["space", "Espacio", LayoutDashboard],
    ["experiments", "Experimentos", Beaker],
    ["activity", "Actividad", Activity],
  ];
  return (
    <div className="topbar glass" role="banner">
      <div className="brand" ref={ref} style={{ position: "relative" }}>
        <button className="row" style={{ gap: 10 }} onClick={() => setWsMenu((m) => !m)} aria-haspopup="menu" aria-expanded={wsMenu} title="Cambiar de workspace">
          <Wordmark project={summary?.workspace.name ?? "…"} />
          {sources.length > 1 ? <ChevronDown size={14} className="muted" /> : null}
        </button>
        {wsMenu && sources.length > 1 ? (
          <div className="menu" role="menu" style={{ top: 40, left: 0 }}>
            {sources.map((s) => (
              <button key={s.id} role="menuitem" onClick={() => { setWsMenu(false); void selectWorkspace(s.id); }} aria-current={s.id === ws}>
                <span className={`dot ${s.mode === "live" ? "ok" : s.mode === "demo" ? "warn" : "muted"}`} />
                {s.name}
                <span className="tiny muted" style={{ marginLeft: "auto" }}>{s.mode}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <nav className="tabs" role="tablist" aria-label="vistas">
        {tabs.map(([id, label, Icon]) => (
          <button key={id} role="tab" aria-selected={tab === id} className="tab" onClick={() => setTab(id)}>
            <Icon size={16} />
            <span className="label">{label}</span>
            {id === "activity" && newSince > 0 ? <span className="chip accent" style={{ padding: "0 6px" }}>{newSince}</span> : null}
          </button>
        ))}
      </nav>
      <div className="status">
        <button className="status-pill" onClick={() => setSettingsOpen(!settingsOpen)} aria-haspopup="dialog" aria-expanded={settingsOpen} title={`Servidor local · modelo: ${inferLabel} · autonomía: ${autonomyLabel}`}>
          <span className={`dot ${dot}`} />
          <span className="text">Local, {autonomyLabel}</span>
          {summary?.connection.kill_switch ? <span className="chip bad">kill switch</span> : null}
          <ChevronDown size={14} className="muted" />
        </button>
        <span className={`mode-label ${mode}`}>{MODE_LABEL[mode] ?? mode}</span>
        <button className="btn ghost icon" onClick={() => setSettingsOpen(!settingsOpen)} aria-label="presupuesto, permisos y configuración">
          <Settings size={16} />
        </button>
      </div>
      {settingsOpen ? <SettingsPopover /> : null}
    </div>
  );
}
