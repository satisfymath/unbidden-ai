// Composes the initial canvas from what the summary says exists: by capability and evidence, never by a project's
// name. A capability without data yields no card, or one that says what is missing. Edges are traces between a
// finding, its experiment and its proposal, drawn only where the record links them.
import type { Edge, Summary, WidgetSpec } from "@/contracts";

type Activity = {
  proven?: { id: string; title: string; level: number; status: string; level_name?: string }[];
  experimenting?: { id: string; title: string; level: number; status: string }[];
  project_checks?: Record<string, unknown> | null;
  proposals?: Record<string, string[]>;
  connections?: unknown[];
  blocks?: { operation: string; kind: string; needs: string }[];
  needs_a_person?: unknown[];
  capabilities?: { awaiting_approval?: { need: string }[] };
  spent?: { calls: number; usd: number };
  goals?: unknown[];
  acceptances?: unknown[];
  integrations?: unknown[];
};

const W = 460;
const GAP = 40;

function widget(partial: Partial<WidgetSpec> & Pick<WidgetSpec, "id" | "type" | "title">): WidgetSpec {
  return {
    schema: 1,
    position: { x: 0, y: 0 },
    size: { w: W, h: 300 },
    pinned: false,
    z: 0,
    view: { kind: "table", options: {} },
    status: "ready",
    content: {},
    created_by: "composer",
    ...partial,
  } as WidgetSpec;
}

export function compose(summary: Summary): { widgets: WidgetSpec[]; edges: Edge[] } {
  const a = summary.activity as Activity;
  const caps = new Set(summary.capabilities);
  const widgets: WidgetSpec[] = [];
  const edges: Edge[] = [];
  const counts = summary.counts;
  const first = summary.highlights.find((h) => h.has_experiment) ?? summary.highlights[0] ?? a.proven?.[0] ?? a.experimenting?.[0] ?? null;
  const hasExperiment = (counts.experiments ?? 0) > 0 && (summary.highlights.find((h) => h.id === first?.id)?.has_experiment ?? false);

  widgets.push(widget({ id: "c_activity", type: "activity", title: "Unbidden ahora", size: { w: 400, h: 300 }, pinned: true }));
  if (caps.has("connections") || (a.connections?.length ?? 0) > 0) {
    widgets.push(widget({ id: "c_resources", type: "resources", title: "Recursos y conexiones", size: { w: 460, h: 280 }, dataRef: { dataset: "connections", params: {}, transform: { filter: [], limit: 100 } } }));
  }
  if (first) {
    widgets.push(
      widget({
        id: `c_finding_${first.id}`,
        type: "finding",
        title: first.level >= 4 ? "Hallazgo validado" : "Hallazgo en curso",
        size: { w: 480, h: 300 },
        entity: { kind: "opportunity", id: first.id },
      }),
    );
  }
  if (hasExperiment && first) {
    widgets.push(
      widget({
        id: `c_experiment_${first.id}`,
        type: "experiment",
        title: "Experimento",
        size: { w: 460, h: 320 },
        entity: { kind: "opportunity", id: first.id },
      }),
    );
    edges.push({ schema: 1, id: `t_${first.id}_exp`, source: `c_finding_${first.id}`, target: `c_experiment_${first.id}`, kind: "trace", label: "mide", evidence: [] });
    widgets.push(
      widget({
        id: `c_latency_${first.id}`,
        type: "chart",
        title: "Latencia antes y después",
        size: { w: 480, h: 320 },
        dataRef: { dataset: "experiment.samples", params: { opportunity_id: first.id }, transform: { filter: [], limit: 2000 } },
        view: { kind: "distribution", x: "ms", series: "arm", bins: 24, unit: "ms", options: {} },
        entity: { kind: "opportunity", id: first.id },
      }),
    );
    edges.push({ schema: 1, id: `t_${first.id}_lat`, source: `c_experiment_${first.id}`, target: `c_latency_${first.id}`, kind: "trace", label: "muestras", evidence: [] });
    widgets.push(
      widget({
        id: `c_tests_${first.id}`,
        type: "tests",
        title: "Tests en ambos lados",
        size: { w: 440, h: 260 },
        dataRef: { dataset: "experiment.tests", params: { opportunity_id: first.id }, transform: { filter: [], limit: 50 } },
        entity: { kind: "opportunity", id: first.id },
      }),
    );
    edges.push({ schema: 1, id: `t_${first.id}_tests`, source: `c_experiment_${first.id}`, target: `c_tests_${first.id}`, kind: "trace", label: "valida", evidence: [] });
  }
  if ((counts.proposals ?? 0) > 0 && first) {
    widgets.push(widget({ id: `c_proposal_${first.id}`, type: "proposal", title: "Cambio candidato", size: { w: 480, h: 320 }, entity: { kind: "opportunity", id: first.id } }));
    if (hasExperiment) {
      edges.push({ schema: 1, id: `t_${first.id}_prop`, source: `c_experiment_${first.id}`, target: `c_proposal_${first.id}`, kind: "trace", label: "propone", evidence: [] });
    }
  } else if (a.proposals && Object.keys(a.proposals).length) {
    const text = Object.entries(a.proposals).map(([status, titles]) => `${status}:\n` + titles.map((t) => `· ${t}`).join("\n")).join("\n\n");
    widgets.push(widget({ id: "c_proposals_summary", type: "note", title: "Propuestas (del registro)", size: { w: 460, h: 240 }, content: { text } }));
  }
  if ((counts.deployments ?? 0) > 0) {
    widgets.push(widget({ id: "c_deployments", type: "table", title: "Despliegues observados", size: { w: 520, h: 240 }, dataRef: { dataset: "deployments", params: {}, transform: { filter: [], limit: 100 } }, view: { kind: "table", columns: ["index", "commit", "commit_status", "initiated_by", "seen_at"], options: {} } }));
  }
  if (caps.has("world") && (counts.world ?? 0) > 0) {
    widgets.push(widget({ id: "c_map", type: "system_map", title: "Mapa del sistema", size: { w: 520, h: 360 }, dataRef: { dataset: "world.relations", params: {}, transform: { filter: [], limit: 500 } }, view: { kind: "map", options: {} } }));
  }
  if (caps.has("probes")) {
    widgets.push(
      widget({
        id: "c_probes",
        type: "chart",
        title: "Latencia de las sondas por despliegue",
        size: { w: 520, h: 300 },
        dataRef: { dataset: "probe.rounds", params: {}, transform: { filter: [], limit: 2000 } },
        view: { kind: "line", x: "ts", y: "p50_ms", series: "target", unit: "ms", options: {} },
      }),
    );
  }
  if (caps.has("checks") || a.project_checks) {
    widgets.push(widget({ id: "c_checks", type: "tests", title: "Checks del proyecto", size: { w: 420, h: 220 }, dataRef: { dataset: "checks", params: {}, transform: { filter: [], limit: 10 } }, view: { kind: "metrics", options: {} } }));
  }
  if (caps.has("needs") || (a.blocks?.length ?? 0) > 0 || (a.capabilities?.awaiting_approval?.length ?? 0) > 0) {
    widgets.push(widget({ id: "c_needs", type: "need", title: "Necesita una persona", size: { w: 440, h: 280 } }));
  }
  if ((counts.spend_calls ?? 0) > 0) {
    widgets.push(
      widget({
        id: "c_spend",
        type: "chart",
        title: "Gasto por propósito",
        size: { w: 440, h: 280 },
        dataRef: { dataset: "spend.calls", params: {}, transform: { filter: [], group_by: "purpose", aggregate: { field: "usd", fn: "sum" }, sort: { field: "sum_usd", dir: "desc" }, limit: 20 } },
        view: { kind: "bar", x: "purpose", y: "sum_usd", unit: "USD", options: {} },
      }),
    );
  }
  if (caps.has("acceptance") || (a.acceptances?.length ?? 0) > 0) {
    widgets.push(widget({ id: "c_acceptance", type: "acceptance", title: "Aceptación", size: { w: 440, h: 260 } }));
  }
  if (summary.workspace.mode === "historical" && summary.timeline_lines > 0) {
    widgets.push(widget({ id: "c_timeline", type: "activity", title: "Ciclos de la corrida", size: { w: 420, h: 320 }, view: { kind: "list", options: { timeline: true } } }));
  }
  if (widgets.length === 1) {
    widgets.push(
      widget({
        id: "c_empty",
        type: "note",
        title: "Todavía no hay registros",
        size: { w: 460, h: 200 },
        content: { text: "Este espacio no tiene oportunidades, experimentos ni mapa. Cuando el motor observe el repositorio (`unbidden scan`) aparecerán aquí." },
      }),
    );
  }
  return { widgets: gridLayout(widgets), edges };
}

/** Three columns, packed by height: a first arrangement the user then owns. */
export function gridLayout(widgets: WidgetSpec[], columns = 3, left = 80, top = 110): WidgetSpec[] {
  const ys = new Array(columns).fill(top) as number[];
  const colW = Math.max(...widgets.map((w) => w.size.w), W) + GAP;
  return widgets.map((w, i) => {
    const c = i % columns;
    const y = ys[c] ?? top;
    ys[c] = y + w.size.h + GAP;
    return { ...w, position: { x: left + c * colW, y } };
  });
}

/** A free place beside an anchor (right, below, left), else below everything. */
export function placeNew(widgets: WidgetSpec[], size: { w: number; h: number }, anchorId: string | null): { x: number; y: number } {
  const anchor = widgets.find((w) => w.id === anchorId) ?? widgets[widgets.length - 1];
  if (!anchor) return { x: 80, y: 110 };
  const overlaps = (x: number, y: number) =>
    widgets.some((w) => !(x + size.w + 24 <= w.position.x || w.position.x + w.size.w + 24 <= x || y + size.h + 24 <= w.position.y || w.position.y + w.size.h + 24 <= y));
  const candidates = [
    { x: anchor.position.x + anchor.size.w + GAP, y: anchor.position.y },
    { x: anchor.position.x, y: anchor.position.y + anchor.size.h + GAP },
    { x: anchor.position.x - size.w - GAP, y: anchor.position.y },
  ];
  for (const c of candidates) if (!overlaps(c.x, c.y)) return c;
  const bottom = Math.max(...widgets.map((w) => w.position.y + w.size.h));
  return { x: anchor.position.x, y: bottom + GAP };
}
