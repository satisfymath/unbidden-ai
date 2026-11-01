// One widget on the canvas: a glass frame with a drag handle, a title, a status chip, a menu, the registry's body
// and a provenance line. Content is React-rendered text: titles and record text can never run as HTML.
import { memo, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Handle, NodeResizer, Position, type NodeProps, type Node as FlowNode } from "@xyflow/react";
import { Copy, GripVertical, Info, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from "lucide-react";
import type { WidgetSpec } from "@/contracts";
import { useStore } from "@/data/store";
import { REGISTRY } from "@/widgets/registry";
import { ProvenanceLine } from "@/widgets/common";

export type WidgetNodeType = FlowNode<{ spec: WidgetSpec }, "widget">;

const SIDES: [Position, string][] = [[Position.Top, "t"], [Position.Right, "r"], [Position.Bottom, "b"], [Position.Left, "l"]];

const STATUS: Record<string, [string, string] | null> = {
  ready: null,
  loading: ["muted", "cargando"],
  empty: ["warn", "sin datos"],
  blocked: ["bad", "bloqueado"],
  revoked: ["bad", "revocado"],
  inconclusive: ["warn", "inconcluso"],
  stale: ["warn", "desactualizado"],
  error: ["bad", "error"],
};

function WidgetNodeInner({ id, data, selected }: NodeProps<WidgetNodeType>) {
  const spec = data.spec;
  const def = REGISTRY[spec.type];
  const patchWidget = useStore((s) => s.patchWidget);
  const removeWidgets = useStore((s) => s.removeWidgets);
  const duplicateWidget = useStore((s) => s.duplicateWidget);
  const setInspectorOpen = useStore((s) => s.setInspectorOpen);
  const setSelection = useStore((s) => s.setSelection);
  const reducedMotion = useStore((s) => s.reducedMotion || (s.presentation?.config.reduced_motion ?? false));
  const [menu, setMenu] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(spec.title);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as globalThis.Node)) setMenu(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);

  const commitTitle = () => {
    setEditing(false);
    const t = draft.trim().slice(0, 160);
    if (t && t !== spec.title) patchWidget(id, { title: t }, "renombrar tarjeta");
    else setDraft(spec.title);
  };
  const onTitleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") commitTitle();
    if (e.key === "Escape") {
      setDraft(spec.title);
      setEditing(false);
    }
  };
  const status = STATUS[spec.status] ?? null;
  const Icon = def?.icon;
  const Body = def?.component;
  const inspect = () => {
    setSelection([id]);
    setInspectorOpen(true);
    setMenu(false);
  };
  return (
    <div className={`widget status-${spec.status} ${!reducedMotion ? "rise" : ""}`} role="group" aria-label={`${def?.label ?? spec.type}: ${spec.title}`}>
      <NodeResizer isVisible={!!selected} minWidth={160} minHeight={80} maxWidth={2400} maxHeight={2000} onResizeEnd={(_, p) => patchWidget(id, { size: { w: p.width, h: p.height }, position: { x: p.x, y: p.y } }, "redimensionar")} />
      {SIDES.map(([pos, key]) => (
        <Handle key={`t-${key}`} id={`t-${key}`} type="target" position={pos} isConnectableStart={false} />
      ))}
      {SIDES.map(([pos, key]) => (
        <Handle key={`s-${key}`} id={`s-${key}`} type="source" position={pos} />
      ))}
      <div className="widget-head widget-handle" onDoubleClick={() => setEditing(true)}>
        <span className="widget-grip" aria-hidden="true">
          <GripVertical size={14} />
        </span>
        <span className="widget-icon" aria-hidden="true">
          {Icon ? <Icon size={15} /> : null}
        </span>
        <span className="widget-title" title={spec.title}>
          {editing ? (
            <input className="nodrag" autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commitTitle} onKeyDown={onTitleKey} aria-label="título de la tarjeta" maxLength={160} />
          ) : (
            spec.title
          )}
        </span>
        {status ? <span className={`chip ${status[0]}`}>{status[1]}</span> : null}
        {spec.pinned ? <Pin size={12} className="muted" aria-label="fijada" /> : null}
        <button className="btn ghost icon nodrag" style={{ padding: 3 }} aria-label="menú de la tarjeta" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
          <MoreHorizontal size={16} />
        </button>
        {menu ? (
          <div className="menu nodrag nowheel" ref={menuRef} role="menu" style={{ top: 36, right: 8 }}>
            <button role="menuitem" onClick={inspect}>
              <Info size={14} /> Inspeccionar
            </button>
            <button role="menuitem" onClick={() => { setMenu(false); setEditing(true); }}>
              <Pencil size={14} /> Renombrar
            </button>
            <button role="menuitem" onClick={() => { setMenu(false); duplicateWidget(id); }}>
              <Copy size={14} /> Duplicar
            </button>
            <button role="menuitem" onClick={() => { setMenu(false); patchWidget(id, { pinned: !spec.pinned }, spec.pinned ? "desfijar" : "fijar"); }}>
              {spec.pinned ? <PinOff size={14} /> : <Pin size={14} />} {spec.pinned ? "Desfijar" : "Fijar"}
            </button>
            <hr />
            <button role="menuitem" className="danger" disabled={spec.pinned} title={spec.pinned ? "Desfija la tarjeta para quitarla" : "Quitar del lienzo; nada del motor cambia"} onClick={() => { setMenu(false); removeWidgets([id]); }}>
              <Trash2 size={14} /> Quitar del lienzo
            </button>
          </div>
        ) : null}
      </div>
      <div className="widget-body">{Body ? <Body widget={spec} /> : <div className="state bad"><b>Tipo desconocido</b>{spec.type}</div>}</div>
      {spec.provenance && !spec.dataRef ? (
        <div className="widget-foot">
          <ProvenanceLine provenance={spec.provenance} />
        </div>
      ) : null}
    </div>
  );
}

export const WidgetNode = memo(WidgetNodeInner);

export function PlaceholderNode({ data }: NodeProps<WidgetNodeType>) {
  return <div className="widget-placeholder" aria-label={data.spec.title} />;
}
