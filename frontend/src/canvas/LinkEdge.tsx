// Relations between cards, drawn differently by kind: evidence (the world model, with refs), trace (finding →
// experiment → change → result) and annotation (the user's own). The kind travels with the edge; it is never guessed.
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type Edge, type EdgeProps } from "@xyflow/react";
import type { Edge as CanvasEdge } from "@/contracts";

export type LinkEdgeType = Edge<{ edge: CanvasEdge }, "link">;

const STROKE: Record<string, string> = { trace: "rgba(243,241,236,0.45)", evidence: "rgba(243,241,236,0.28)", annotation: "rgba(201,199,193,0.7)" };

export function LinkEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }: EdgeProps<LinkEdgeType>) {
  const kind = data?.edge.kind ?? "annotation";
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.35 });
  const stroke = STROKE[kind] ?? STROKE.annotation;
  const label = data?.edge.label;
  const title = data?.edge.note ?? (kind === "evidence" ? `${data?.edge.evidence.length ?? 0} referencia(s) de evidencia` : kind === "trace" ? "relación entre hallazgo, experimento, cambio y resultado" : "anotación tuya");
  return (
    <>
      {kind === "trace" ? <BaseEdge id={`${id}-glow`} path={path} style={{ stroke, strokeWidth: 6, opacity: 0.15 }} /> : null}
      <BaseEdge id={id} path={path} style={{ stroke, strokeWidth: selected ? 2.5 : 1.8, strokeDasharray: kind === "annotation" ? "6 5" : undefined, opacity: 0.95 }} />
      <circle cx={sourceX} cy={sourceY} r={4} fill="#0c0c0c" stroke={stroke} strokeWidth={2} />
      <circle cx={targetX} cy={targetY} r={4} fill="#0c0c0c" stroke={stroke} strokeWidth={2} />
      {label ? (
        <EdgeLabelRenderer>
          <div className={`edge-label ${kind}`} style={{ left: lx, top: ly }} title={title}>
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
