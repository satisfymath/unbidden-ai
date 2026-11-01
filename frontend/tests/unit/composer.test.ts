import { describe, expect, it } from "vitest";
import { compose, placeNew } from "@/canvas/composer";
import type { Summary } from "@/contracts";

function summary(capabilities: string[], activity: Record<string, unknown> = {}, mode: Summary["workspace"]["mode"] = "live"): Summary {
  const counts: Record<string, number> = { experiments: capabilities.includes("experiments") ? 1 : 0, proposals: capabilities.includes("proposals") ? 1 : 0, world: capabilities.includes("world") ? 1 : 0, deployments: 0, spend_calls: 0 };
  return {
    schema: 1,
    workspace: { id: "x", name: "whatever-name", repo: null, mode, head: null, schema_version: 2, notes: [] },
    connection: {
      route: { server: "local", profile: "local-first", local: { provider: "ollama", model: "m", base_url: null }, remote: { provider: "meta", model: "r", credential_file_present: false }, local_inference: "allow", note: "" },
      autonomy: { level: "supervised", fields: {} },
      kill_switch: null,
      streams: true,
    },
    activity: activity,
    counts,
    jobs: {},
    capabilities,
    highlights: (activity.proven as { id: string; title: string; level: number; status: string }[] | undefined)?.map((p) => ({ ...p, has_experiment: capabilities.includes("experiments") })) ?? [],
    timeline_lines: 0,
    observed_at: new Date().toISOString(),
    freshness: "current",
    last_event_seq: 0,
  };
}

describe("composer", () => {
  it("composes from capabilities and evidence, not from the project's name", () => {
    const empty = compose(summary([]));
    expect(empty.widgets.map((w) => w.type)).toEqual(["activity", "note"]);
    const rich = compose(summary(["experiments", "world", "probes", "proposals"], { proven: [{ id: "opp_1", title: "t", level: 4, status: "proposed" }] }));
    const types = rich.widgets.map((w) => w.type);
    expect(types).toContain("finding");
    expect(types).toContain("experiment");
    expect(types).toContain("chart");
    expect(types).toContain("system_map");
    expect(types).toContain("proposal");
    expect(types).not.toContain("screenshots");
    expect(rich.edges.every((e) => e.kind === "trace")).toBe(true);
    const ids = new Set(rich.widgets.map((w) => w.id));
    expect(rich.edges.every((e) => ids.has(e.source) && ids.has(e.target))).toBe(true);
  });
  it("lays cards out without overlap and places new ones beside the anchor", () => {
    const { widgets } = compose(summary(["experiments", "world", "probes", "checks"], { proven: [{ id: "opp_1", title: "t", level: 4, status: "proposed" }] }));
    for (const a of widgets) for (const b of widgets) {
      if (a === b) continue;
      const apart = a.position.x + a.size.w <= b.position.x || b.position.x + b.size.w <= a.position.x || a.position.y + a.size.h <= b.position.y || b.position.y + b.size.h <= a.position.y;
      expect(apart).toBe(true);
    }
    const anchor = widgets[0]!;
    const p = placeNew(widgets, { w: 300, h: 200 }, anchor.id);
    expect(p.x !== anchor.position.x || p.y !== anchor.position.y).toBe(true);
  });
});
