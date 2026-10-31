import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { NoteWidget, EventRow } from "@/widgets/MiscWidgets";
import type { WidgetSpec } from "@/contracts";

const evil = '<img src=x onerror="window.pwned=1"><script>window.pwned=2</script>{{7*7}}';

describe("record text is data, never markup", () => {
  it("renders a note's text literally", () => {
    const widget: WidgetSpec = { schema: 1, id: "w", type: "note", title: evil, position: { x: 0, y: 0 }, size: { w: 300, h: 200 }, pinned: false, z: 0, view: { kind: "text", options: {} }, status: "ready", content: { text: evil }, created_by: "chat" };
    const { container } = render(<NoteWidget widget={widget} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>");
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined();
  });
  it("renders an event's payload literally", () => {
    const { container } = render(<EventRow e={{ seq: 1, ts: "2026-10-31T10:00:00Z", type: "opportunity.opened", actor: "x", payload: { title: evil } }} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("onerror");
  });
});
