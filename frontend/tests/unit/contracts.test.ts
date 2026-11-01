import { describe, expect, it } from "vitest";
import { DataRef, Presentation, WidgetSpec } from "@/contracts";

describe("widget specifications", () => {
  it("accepts a chart with a bounded data reference", () => {
    const w = WidgetSpec.parse({
      id: "w_1",
      type: "chart",
      title: "Latencia",
      position: { x: 0, y: 0 },
      size: { w: 400, h: 300 },
      dataRef: { dataset: "experiment.samples", params: { experiment_id: "exp_1" }, transform: { limit: 100 } },
      view: { kind: "distribution", x: "ms", series: "arm" },
    });
    expect(w.status).toBe("ready");
    expect(w.dataRef?.transform.limit).toBe(100);
  });
  it("rejects unknown types, scripts, oversized cards and foreign fields", () => {
    const base = { id: "w_1", title: "x", position: { x: 0, y: 0 }, size: { w: 400, h: 300 } };
    expect(() => WidgetSpec.parse({ ...base, type: "script" })).toThrow();
    expect(() => WidgetSpec.parse({ ...base, type: "note", size: { w: 99999, h: 10 } })).toThrow();
    expect(() => WidgetSpec.parse({ ...base, type: "note", html: "<b>x</b>" })).toThrow();
    expect(() => WidgetSpec.parse({ ...base, type: "note", id: "../../etc" })).toThrow();
  });
  it("accepts only the bounded transforms, never a query", () => {
    expect(() => DataRef.parse({ dataset: "experiment.samples", transform: { limit: 100000 } })).toThrow();
    expect(() => DataRef.parse({ dataset: "SELECT * FROM x" })).toThrow();
    expect(() => DataRef.parse({ dataset: "events", transform: { sql: "drop" } })).toThrow();
    expect(DataRef.parse({ dataset: "events", transform: { filter: [{ field: "type", op: "eq", value: "model.called" }] } }).transform.filter).toHaveLength(1);
  });
  it("parses a presentation and keeps edge kinds", () => {
    const p = Presentation.parse({ workspace: "demo", version: 3, widgets: [], edges: [{ id: "e", source: "a", target: "b", kind: "trace" }], viewport: {}, config: {} });
    expect(p.edges[0]?.kind).toBe("trace");
    expect(() => Presentation.parse({ workspace: "demo", version: 1, widgets: [], edges: [{ id: "e", source: "a", target: "b", kind: "guess" }], viewport: {}, config: {} })).toThrow();
  });
});
