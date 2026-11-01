import { useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Logo } from "@/components/Logo";
import { useStore } from "@/data/store";
import { Canvas } from "@/canvas/Canvas";
import { TopBar } from "@/shell/TopBar";
import { BottomBar } from "@/shell/BottomBar";
import { ChatPanel } from "@/shell/ChatPanel";
import { Inspector } from "@/shell/Inspector";
import { ActivityView, ExperimentsView } from "@/shell/Views";
import { MobileView } from "@/shell/Mobile";
import { REGISTRY } from "@/widgets/registry";
import "@/theme/global.css";
import "@/shell/shell.css";

function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast glass ${t.kind ?? "info"}`}>
          <Logo size={16} />
          <span>{t.text}</span>
          {t.action ? <button className="btn sm" onClick={() => { t.action?.run(); dismiss(t.id); }}>{t.action.label}</button> : null}
          <button className="btn ghost sm" onClick={() => dismiss(t.id)} aria-label="cerrar aviso">✕</button>
        </div>
      ))}
    </div>
  );
}

function Onboarding({ reason }: { reason: string }) {
  return (
    <div className="center-card glass">
      <Logo size={32} />
      {reason === "no-token" ? (
        <>
          <h2>Abre la URL que imprimió el servidor</h2>
          <p>El espacio se sirve solo en este equipo y cada sesión lleva un token. Arranca el servidor y abre el enlace con <code style={{ display: "inline", padding: "0 4px" }}>?s=…</code> que muestra:</p>
          <code>uv run python -m unbidden.web --demo</code>
          <p className="small muted">Para un workspace real: <code style={{ display: "inline", padding: "0 4px" }}>--workspace ~/ruta/al/repo</code> (lectura, sin migrar su estado). Para una corrida cerrada: <code style={{ display: "inline", padding: "0 4px" }}>--record docs/bench/…</code>.</p>
        </>
      ) : (
        <>
          <h2>No se pudo leer el workspace</h2>
          <p className="small">{reason}</p>
          <p className="small muted">El servidor sigue; recarga cuando el registro vuelva a estar legible. Nada se simula mientras tanto.</p>
        </>
      )}
    </div>
  );
}

function Shortcuts() {
  const setChatOpen = useStore((s) => s.setChatOpen);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  const setTab = useStore((s) => s.setTab);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inField = (e.target as HTMLElement)?.closest("input,textarea,select,[contenteditable]");
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setChatOpen(!useStore.getState().chatOpen);
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && !inField) {
        e.preventDefault();
        if (e.shiftKey) void redo();
        else void undo();
      } else if (!inField && !e.metaKey && !e.ctrlKey && e.key.toLowerCase() === "f" && !useStore.getState().chatOpen) {
        document.querySelector<HTMLButtonElement>('button[aria-label="encuadrar todo"]')?.click();
      } else if (!inField && e.key === "1") setTab("space");
      else if (!inField && e.key === "2") setTab("experiments");
      else if (!inField && e.key === "3") setTab("activity");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setChatOpen, undo, redo, setTab]);
  return null;
}

function AutoAdd() {
  // New entities arriving live are proposed as cards below what the user placed, never on top of it.
  const events = useStore((s) => s.events);
  const presentation = useStore((s) => s.presentation);
  const addWidget = useStore((s) => s.addWidget);
  const toast = useStore((s) => s.toast);
  const summary = useStore((s) => s.summary);
  useEffect(() => {
    const last = events[events.length - 1];
    if (!last || !presentation?.config.auto_add || summary?.workspace.mode !== "live") return;
    if (last.type !== "opportunity.opened" || !last.entity_id) return;
    const id = last.entity_id;
    if (presentation.widgets.some((w) => w.entity?.id === id)) return;
    const bottom = Math.max(0, ...presentation.widgets.map((w) => w.position.y + w.size.h));
    const wid = addWidget({ type: "finding", title: "Hallazgo nuevo", size: REGISTRY.finding.size, position: { x: 80, y: bottom + 60 }, entity: { kind: "opportunity", id }, created_by: "composer" });
    toast(`Nueva oportunidad: tarjeta añadida debajo del espacio`, "ok", { label: "Ver", run: () => useStore.getState().focus(wid) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length]);
  return null;
}

export default function App() {
  const boot = useStore((s) => s.boot);
  const summaryError = useStore((s) => s.summaryError);
  const summary = useStore((s) => s.summary);
  const tab = useStore((s) => s.tab);
  const mobile = useStore((s) => s.mobile);
  const reduced = useStore((s) => s.reducedMotion || (s.presentation?.config.reduced_motion ?? false));
  useEffect(() => {
    void boot();
  }, [boot]);
  useEffect(() => {
    document.documentElement.classList.toggle("reduced-motion", reduced);
  }, [reduced]);
  if (summaryError === "no-token" || (summaryError && !summary)) {
    return (
      <>
        <div className="app-bg" />
        <Onboarding reason={summaryError} />
      </>
    );
  }
  if (mobile) {
    return (
      <>
        <div className="app-bg" />
        <MobileView />
      </>
    );
  }
  return (
    <ReactFlowProvider>
      <div className="app-bg" />
      {tab === "space" ? <Canvas /> : null}
      <div className="shell">
        <TopBar />
        {tab === "experiments" ? <ExperimentsView /> : null}
        {tab === "activity" ? <ActivityView /> : null}
        {tab === "space" ? <Inspector /> : null}
        <ChatPanel />
        <BottomBar />
        <Toasts />
      </div>
      <Shortcuts />
      <AutoAdd />
    </ReactFlowProvider>
  );
}
