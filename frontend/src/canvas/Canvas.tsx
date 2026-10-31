// The infinite canvas: pan, zoom, fit, minimap; drag by the header, resize by the corner; single and multiple
// selection; edges drawn between handles become annotations; positions, sizes and the viewport persist.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  MiniMap,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type NodeChange,
  type OnSelectionChangeParams,
  type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./canvas.css";
import { useStore } from "@/data/store";
import { WidgetNode, PlaceholderNode, type WidgetNodeType } from "./WidgetNode";
import { LinkEdge, type LinkEdgeType } from "./LinkEdge";

const nodeTypes = { widget: WidgetNode, placeholder: PlaceholderNode };
// Fit leaves room for the floating bars, so no card starts under them.
export const FIT = { padding: { top: "92px", bottom: "96px", left: "36px", right: "36px" }, maxZoom: 1 } as const;
const edgeTypes = { link: LinkEdge };

function Inner() {
  const presentation = useStore((s) => s.presentation);
  const selection = useStore((s) => s.selection);
  const setSelection = useStore((s) => s.setSelection);
  const setWidgets = useStore((s) => s.setWidgets);
  const setEdges = useStore((s) => s.setEdges);
  const setViewport = useStore((s) => s.setViewport);
  const removeWidgets = useStore((s) => s.removeWidgets);
  const focusWidget = useStore((s) => s.focusWidget);
  const focus = useStore((s) => s.focus);
  const toast = useStore((s) => s.toast);
  const chatOpen = useStore((s) => s.chatOpen);
  const reducedMotion = useStore((s) => s.reducedMotion || (s.presentation?.config.reduced_motion ?? false));
  const rf = useReactFlow<WidgetNodeType, LinkEdgeType>();
  const [nodes, setNodes] = useState<WidgetNodeType[]>([]);
  const dragging = useRef(false);
  const fitted = useRef(false);

  const widgets = presentation?.widgets;
  useEffect(() => {
    if (!widgets || dragging.current) return;
    setNodes((prev) => {
      const prevById = new Map(prev.map((n) => [n.id, n]));
      return widgets.map((w) => {
        const p = prevById.get(w.id);
        return {
          id: w.id,
          type: "widget" as const,
          position: w.position,
          width: w.size.w,
          height: w.size.h,
          data: { spec: w },
          dragHandle: ".widget-handle",
          zIndex: w.z + (selection.includes(w.id) ? 1000 : 0),
          selected: selection.includes(w.id),
          ...(p && p.dragging ? { position: p.position } : {}),
        };
      });
    });
  }, [widgets, selection]);

  const edges = useMemo<LinkEdgeType[]>(() => {
    const byId = new Map((presentation?.widgets ?? []).map((w) => [w.id, w]));
    return (presentation?.edges ?? []).map((e) => {
      const a = byId.get(e.source);
      const b = byId.get(e.target);
      let sh = "s-r";
      let th = "t-l";
      if (a && b) {
        const dx = b.position.x + b.size.w / 2 - (a.position.x + a.size.w / 2);
        const dy = b.position.y + b.size.h / 2 - (a.position.y + a.size.h / 2);
        if (Math.abs(dx) * 0.8 > Math.abs(dy)) {
          sh = dx > 0 ? "s-r" : "s-l";
          th = dx > 0 ? "t-l" : "t-r";
        } else {
          sh = dy > 0 ? "s-b" : "s-t";
          th = dy > 0 ? "t-t" : "t-b";
        }
      }
      return { id: e.id, source: e.source, target: e.target, sourceHandle: sh, targetHandle: th, type: "link" as const, data: { edge: e }, focusable: true };
    });
  }, [presentation?.edges, presentation?.widgets]);

  useEffect(() => {
    if (!presentation || fitted.current || !nodes.length) return;
    fitted.current = true;
    const v = presentation.viewport;
    if (v.x === 0 && v.y === 0 && v.zoom === 1) {
      window.setTimeout(() => void rf.fitView({ ...FIT, duration: reducedMotion ? 0 : 400 }), 50);
    } else {
      void rf.setViewport(v);
    }
  }, [presentation, nodes.length, rf, reducedMotion]);

  useEffect(() => {
    if (!focusWidget) return;
    const t = window.setTimeout(() => {
      void rf.fitView({ nodes: [{ id: focusWidget }], padding: { top: "140px", bottom: "140px", left: "200px", right: "200px" }, maxZoom: 1, duration: reducedMotion ? 0 : 500 });
      focus(null);
    }, 80);
    return () => window.clearTimeout(t);
  }, [focusWidget, rf, focus, reducedMotion]);

  const onNodesChange = useCallback((changes: NodeChange<WidgetNodeType>[]) => {
    if (changes.some((c) => c.type === "position" && c.dragging)) dragging.current = true;
    setNodes((ns) => applyNodeChanges(changes, ns));
  }, []);

  const commitPositions = useCallback(() => {
    dragging.current = false;
    const current = useStore.getState().presentation;
    if (!current) return;
    const byId = new Map(rf.getNodes().map((n) => [n.id, n.position]));
    const moved = current.widgets.map((w) => {
      const p = byId.get(w.id);
      return p && (p.x !== w.position.x || p.y !== w.position.y) ? { ...w, position: { x: Math.round(p.x), y: Math.round(p.y) } } : w;
    });
    if (moved.some((w, i) => w !== current.widgets[i])) setWidgets(moved, "mover tarjeta");
  }, [rf, setWidgets]);

  const onSelectionChange = useCallback(
    ({ nodes: sel }: OnSelectionChangeParams<WidgetNodeType, LinkEdgeType>) => {
      const ids = sel.map((n) => n.id);
      const cur = useStore.getState().selection;
      if (ids.length !== cur.length || ids.some((i) => !cur.includes(i))) setSelection(ids);
    },
    [setSelection],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target || c.source === c.target) return;
      const label = window.prompt("Etiqueta de la anotación (tuya; no cambia el modelo del mundo):", "relacionado");
      if (label === null) return;
      const current = useStore.getState().presentation;
      if (!current) return;
      setEdges([...current.edges, { schema: 1, id: `e_${Math.random().toString(36).slice(2, 10)}`, source: c.source, target: c.target, kind: "annotation", label: label.slice(0, 80) || null, evidence: [], note: "dibujada por el usuario" }], "anotación");
      toast("Anotación añadida (no modifica el modelo del mundo)", "info");
    },
    [setEdges, toast],
  );

  const onMoveEnd = useCallback((_: unknown, v: Viewport) => setViewport({ x: v.x, y: v.y, zoom: v.zoom }), [setViewport]);

  const onEdgeDelete = useCallback(
    (removed: LinkEdgeType[]) => {
      const current = useStore.getState().presentation;
      if (!current) return;
      const ids = new Set(removed.filter((e) => e.data?.edge.kind !== "evidence").map((e) => e.id));
      if (!ids.size) {
        toast("Las relaciones con evidencia vienen del modelo del mundo; no se borran desde el lienzo", "warn");
        return;
      }
      setEdges(current.edges.filter((e) => !ids.has(e.id)), "quitar conexión");
    },
    [setEdges, toast],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const sel = useStore.getState().selection;
      if ((e.key === "Delete" || e.key === "Backspace") && sel.length && !(e.target as HTMLElement).closest("input,textarea")) {
        e.preventDefault();
        removeWidgets(sel);
      }
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key) && sel.length && !(e.target as HTMLElement).closest("input,textarea")) {
        e.preventDefault();
        const d = e.shiftKey ? 40 : 10;
        const dx = e.key === "ArrowLeft" ? -d : e.key === "ArrowRight" ? d : 0;
        const dy = e.key === "ArrowUp" ? -d : e.key === "ArrowDown" ? d : 0;
        const current = useStore.getState().presentation;
        if (!current) return;
        setWidgets(current.widgets.map((w) => (sel.includes(w.id) ? { ...w, position: { x: w.position.x + dx, y: w.position.y + dy } } : w)), "mover con teclado");
      }
    },
    [removeWidgets, setWidgets],
  );

  return (
    <div className={`canvas-root ${chatOpen ? "dimmed" : ""}`} onKeyDown={onKeyDown} aria-hidden={chatOpen}>
      <ReactFlow<WidgetNodeType, LinkEdgeType>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={commitPositions}
        onSelectionDragStop={commitPositions}
        onSelectionChange={onSelectionChange}
        onConnect={onConnect}
        onEdgesDelete={onEdgeDelete}
        onMoveEnd={onMoveEnd}
        onlyRenderVisibleElements
        minZoom={0.1}
        maxZoom={2.5}
        panOnScroll
        zoomOnScroll={false}
        zoomOnPinch
        zoomOnDoubleClick={false}
        selectionOnDrag={false}
        selectionKeyCode="Shift"
        multiSelectionKeyCode={["Meta", "Control"]}
        deleteKeyCode={null}
        nodesFocusable
        edgesFocusable
        elevateNodesOnSelect
        nodeDragThreshold={3}
        proOptions={{ hideAttribution: true }}
        defaultViewport={presentation?.viewport}
      >
        <MiniMap pannable zoomable position="bottom-right" style={{ marginBottom: 76, marginRight: 16, width: 180, height: 110 }} nodeColor={(n) => (n.selected ? "#3fd8c7" : "rgba(146,184,222,0.4)")} />
      </ReactFlow>
    </div>
  );
}

export function Canvas() {
  return <Inner />;
}

export function useCanvasControls() {
  const rf = useReactFlow();
  return {
    zoomIn: () => void rf.zoomIn({ duration: 200 }),
    zoomOut: () => void rf.zoomOut({ duration: 200 }),
    fit: () => void rf.fitView({ ...FIT, duration: 400 }),
    zoom: rf.getZoom(),
  };
}
