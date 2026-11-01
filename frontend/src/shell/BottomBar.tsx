// The dock: the save state, the conversation input, the add menu, zoom and fit, fullscreen.
import { useEffect, useRef, useState } from "react";
import { Expand, LayoutGrid, Map as MapIcon, Maximize2, Minus, Plus, Redo2, Send, Sparkles, Undo2 } from "lucide-react";
import { useReactFlow, useViewport } from "@xyflow/react";
import { Logo } from "@/components/Logo";
import { useStore } from "@/data/store";
import { REGISTRY } from "@/widgets/registry";
import { FIT } from "@/canvas/Canvas";
import type { WidgetType } from "@/contracts";

export function Dock() {
  const chatOpen = useStore((s) => s.chatOpen);
  const setChatOpen = useStore((s) => s.setChatOpen);
  const sendChat = useStore((s) => s.sendChat);
  const chatBusy = useStore((s) => s.chatBusy);
  const [text, setText] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (chatOpen) ref.current?.focus();
  }, [chatOpen]);
  const submit = () => {
    const t = text.trim();
    if (!t || chatBusy) return;
    setChatOpen(true);
    setText("");
    void sendChat(t);
  };
  return (
    <form className="dock glass" onSubmit={(e) => { e.preventDefault(); submit(); }} role="search" aria-label="habla con Unbidden">
      <Logo size={22} />
      <input ref={ref} value={text} onChange={(e) => setText(e.target.value)} onFocus={() => setChatOpen(true)} placeholder="Habla con Unbidden…" aria-label="mensaje para Unbidden" />
      <span className="kbd" aria-hidden="true">⌘ K</span>
      <button type="submit" className="btn primary icon round" style={{ width: 40, height: 40 }} aria-label="enviar" disabled={chatBusy || !text.trim()}>
        <Send size={16} />
      </button>
    </form>
  );
}

export function AddMenu() {
  const open = useStore((s) => s.addMenuOpen);
  const setOpen = useStore((s) => s.setAddMenuOpen);
  const addWidget = useStore((s) => s.addWidget);
  const selection = useStore((s) => s.selection);
  const presentation = useStore((s) => s.presentation);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && !(e.target as HTMLElement).closest(".add-button") && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [open, setOpen]);
  if (!open) return null;
  const selectedEntity = presentation?.widgets.find((w) => w.id === selection[0])?.entity ?? null;
  const add = (type: WidgetType) => {
    const def = REGISTRY[type];
    const base = { type, title: def.label, size: def.size, view: { kind: type === "chart" ? ("bar" as const) : type === "system_map" ? ("map" as const) : ("table" as const), options: {} } };
    const dataRef =
      type === "chart" || type === "table" ? { dataset: "opportunities", params: {}, transform: { filter: [], limit: 200 } }
      : type === "metrics" ? { dataset: "model_runs", params: {}, transform: { filter: [], limit: 500 } }
      : type === "tests" ? { dataset: "checks", params: {}, transform: { filter: [], limit: 10 } }
      : type === "resources" ? { dataset: "connections", params: {}, transform: { filter: [], limit: 100 } }
      : type === "system_map" ? { dataset: "world.relations", params: {}, transform: { filter: [], limit: 500 } }
      : undefined;
    const spec = {
      ...base,
      ...(type === "chart" ? { view: { kind: "bar" as const, x: "status", y: "level", options: {} }, dataRef: { dataset: "opportunities", params: {}, transform: { filter: [], group_by: "status", aggregate: { field: "id", fn: "count" as const }, limit: 50 } } } : {}),
      ...(dataRef && type !== "chart" ? { dataRef } : {}),
      ...(def.needsEntity && selectedEntity ? { entity: selectedEntity } : {}),
      ...(type === "chart" ? { view: { kind: "bar" as const, x: "status", y: "count", options: {} } } : {}),
      content: type === "note" ? { text: "" } : {},
      status: def.needsEntity && !selectedEntity ? ("empty" as const) : ("ready" as const),
    };
    addWidget(spec, selection[0]);
    setOpen(false);
  };
  return (
    <div className="popover add-menu" ref={ref} role="menu" aria-label="añadir tarjeta">
      {(Object.keys(REGISTRY) as WidgetType[]).map((type) => {
        const def = REGISTRY[type];
        const Icon = def.icon;
        return (
          <button key={type} className="add-item" role="menuitem" onClick={() => add(type)}>
            <Icon size={16} />
            <span>
              <b>{def.label}</b>
              <span>{def.describe}{def.needsEntity && !selectedEntity ? " · selecciona antes un hallazgo" : ""}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function BottomBar() {
  const presentation = useStore((s) => s.presentation);
  const saving = useStore((s) => s.saving);
  const dirty = useStore((s) => s.dirty);
  const presentationError = useStore((s) => s.presentationError);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  const autoLayout = useStore((s) => s.autoLayout);
  const setAddMenuOpen = useStore((s) => s.setAddMenuOpen);
  const addMenuOpen = useStore((s) => s.addMenuOpen);
  const tab = useStore((s) => s.tab);
  const rf = useReactFlow();
  const { zoom } = useViewport();
  const [full, setFull] = useState(!!document.fullscreenElement);
  const count = presentation?.widgets.length ?? 0;
  const saveLabel = presentationError ? "Error al guardar" : saving ? "Guardando…" : dirty ? "Sin guardar" : "Guardado";
  const canUndo = presentation?.history?.can_undo ?? false;
  const canRedo = presentation?.history?.can_redo ?? false;
  const toggleFull = async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
    setFull(!!document.fullscreenElement);
  };
  return (
    <div className="bottombar">
      <div className="bottom-left">
        <div className="saved-pill glass" title={presentationError ?? "El lienzo se guarda en el servidor local"}>
          <button className="btn ghost icon" onClick={() => void rf.fitView({ ...FIT, duration: 400 })} aria-label="encuadrar todo" title="Encuadrar todo (F)">
            <MapIcon size={16} />
          </button>
          <span>
            {count} widgets · <span style={{ color: presentationError ? "var(--red)" : dirty || saving ? "var(--amber)" : "var(--ink-2)" }}>{saveLabel}</span>
          </span>
          <button className="btn ghost icon" onClick={() => void undo()} disabled={!canUndo} aria-label="deshacer" title="Deshacer (⌘Z)"><Undo2 size={15} /></button>
          <button className="btn ghost icon" onClick={() => void redo()} disabled={!canRedo} aria-label="rehacer" title="Rehacer (⌘⇧Z)"><Redo2 size={15} /></button>
          <button className="btn ghost icon" onClick={autoLayout} aria-label="distribuir automáticamente" title="Distribuir automáticamente"><LayoutGrid size={15} /></button>
        </div>
      </div>
      {tab === "space" ? <Dock /> : null}
      {tab === "space" ? (
        <button className={`btn round big glass add-button ${addMenuOpen ? "primary" : ""}`} onClick={() => setAddMenuOpen(!addMenuOpen)} aria-label="añadir tarjeta" aria-haspopup="menu" aria-expanded={addMenuOpen} title="Añadir tarjeta">
          <Plus size={20} />
        </button>
      ) : null}
      <div className="bottom-right">
        <div className="zoom-pill glass">
          <button className="btn ghost icon" onClick={() => void rf.zoomOut({ duration: 200 })} aria-label="alejar"><Minus size={15} /></button>
          <span aria-live="polite">{Math.round(zoom * 100)}%</span>
          <button className="btn ghost icon" onClick={() => void rf.zoomIn({ duration: 200 })} aria-label="acercar"><Plus size={15} /></button>
        </div>
        <button className="btn round glass" onClick={() => void toggleFull()} aria-label={full ? "salir de pantalla completa" : "pantalla completa"}>
          {full ? <Maximize2 size={16} /> : <Expand size={16} />}
        </button>
      </div>
      <AddMenu />
      <span className="sr-only" aria-live="polite">
        <Sparkles size={1} />
      </span>
    </div>
  );
}
