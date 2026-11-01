// On a phone the canvas is not shrunk: the cards are a list, with the chat and the inspector.
import { useState } from "react";
import { Logo } from "@/components/Logo";
import { useStore } from "@/data/store";
import { REGISTRY } from "@/widgets/registry";
import { ChatPanel } from "./ChatPanel";
import { Dock } from "./BottomBar";
import { Inspector } from "./Inspector";

export function MobileView() {
  const presentation = useStore((s) => s.presentation);
  const summary = useStore((s) => s.summary);
  const setSelection = useStore((s) => s.setSelection);
  const setInspectorOpen = useStore((s) => s.setInspectorOpen);
  const [filter, setFilter] = useState("");
  const widgets = (presentation?.widgets ?? []).filter((w) => !filter || w.type === filter);
  return (
    <div className="mobile">
      <div className="topbar glass" style={{ position: "fixed" }}>
        <Logo size={20} />
        <b style={{ letterSpacing: "0.18em", fontSize: 12 }}>UNBIDDEN</b>
        <span className="muted small ellipsis">/ {summary?.workspace.name}</span>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className="field" style={{ marginLeft: "auto", background: "rgba(146,184,222,0.08)", border: "1px solid var(--line)", borderRadius: 8, padding: "4px 6px", color: "var(--ink)" }} aria-label="filtrar tarjetas">
          <option value="">todas</option>
          {Object.entries(REGISTRY).map(([k, d]) => <option key={k} value={k}>{d.label}</option>)}
        </select>
      </div>
      <div className="cards">
        {widgets.map((w) => {
          const def = REGISTRY[w.type];
          const Body = def.component;
          return (
            <article key={w.id} className="card glass" onClick={() => { setSelection([w.id]); }}>
              <div className="widget-head">
                <def.icon size={15} style={{ color: "var(--accent)" }} />
                <span className="widget-title">{w.title}</span>
                <button className="btn sm" onClick={() => { setSelection([w.id]); setInspectorOpen(true); }}>Detalle</button>
              </div>
              <div className="widget-body"><Body widget={w} /></div>
            </article>
          );
        })}
      </div>
      <div className="bottombar" style={{ position: "fixed" }}>
        <Dock />
      </div>
      <div className="shell"><Inspector /><ChatPanel /></div>
    </div>
  );
}
