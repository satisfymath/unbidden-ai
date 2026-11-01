import { describe, expect, it } from "vitest";
import { parseSse } from "@/data/sse";

describe("sse parser", () => {
  it("parses events across chunk boundaries and keeps ids", () => {
    const a = parseSse('event: hello\ndata: {"last_seq": 3}\n\nevent: engine\nid: 4\ndata: {"se', "");
    expect(a.events).toEqual([{ event: "hello", id: null, data: { last_seq: 3 } }]);
    const b = parseSse('q": 4, "type": "x"}\n\n', a.carry);
    expect(b.events).toEqual([{ event: "engine", id: "4", data: { seq: 4, type: "x" } }]);
    expect(b.carry).toBe("");
  });
  it("keeps non-JSON data as text", () => {
    expect(parseSse("data: plain\n\n", "").events[0]?.data).toBe("plain");
  });
});
