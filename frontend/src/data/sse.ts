// Server-sent events over fetch (EventSource cannot send the session header): a parser, and a subscription that
// resumes from the last id, deduplicates by id, and reports staleness honestly.

export type SseEvent = { event: string; id: string | null; data: unknown };

export function parseSse(chunk: string, carry: string): { events: SseEvent[]; carry: string } {
  const text = carry + chunk;
  const blocks = text.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: SseEvent[] = [];
  for (const block of blocks) {
    let event = "message";
    let id: string | null = null;
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("id:")) id = line.slice(3).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (data.length) {
      let parsed: unknown = data.join("\n");
      try {
        parsed = JSON.parse(data.join("\n"));
      } catch {
        /* keep the text */
      }
      events.push({ event, id, data: parsed });
    }
  }
  return { events, carry: rest };
}

export async function readSse(
  url: string,
  init: RequestInit,
  onEvent: (e: SseEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(url, { ...init, signal });
  if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let carry = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseSse(decoder.decode(value, { stream: true }), carry);
    carry = parsed.carry;
    for (const e of parsed.events) onEvent(e);
  }
}

export type StreamStatus = "connecting" | "live" | "stale" | "closed" | "disconnected";

/** A resilient subscription to /events/stream: reconnects with backoff from the last seq; never replays a seq twice. */
export function subscribeEvents(opts: {
  url: string;
  headers: Record<string, string>;
  after: number;
  onEngine: (data: Record<string, unknown>, seq: number) => void;
  onStatus: (status: StreamStatus, detail?: string) => void;
}): () => void {
  let last = opts.after;
  let stopped = false;
  let controller = new AbortController();
  let attempt = 0;

  const run = async () => {
    while (!stopped) {
      opts.onStatus(attempt === 0 ? "connecting" : "disconnected", attempt ? `reintento ${attempt}` : undefined);
      controller = new AbortController();
      try {
        await readSse(
          `${opts.url}?after=${last}`,
          { headers: { ...opts.headers, "Last-Event-ID": String(last) } },
          (e) => {
            if (e.event === "hello" || e.event === "recovered") {
              attempt = 0;
              opts.onStatus("live");
            } else if (e.event === "engine") {
              const seq = Number(e.id);
              if (Number.isFinite(seq) && seq > last) {
                last = seq;
                opts.onEngine(e.data as Record<string, unknown>, seq);
              }
            } else if (e.event === "stale") {
              opts.onStatus("stale", String((e.data as { reason?: string })?.reason ?? ""));
            } else if (e.event === "closed") {
              opts.onStatus("closed", String((e.data as { reason?: string })?.reason ?? ""));
              stopped = true;
            } else if (e.event === "heartbeat") {
              opts.onStatus("live");
            }
          },
          controller.signal,
        );
      } catch (err) {
        if (stopped) return;
        opts.onStatus("disconnected", err instanceof Error ? err.message : String(err));
      }
      if (stopped) return;
      attempt += 1;
      await new Promise((r) => setTimeout(r, Math.min(15000, 1000 * 2 ** Math.min(attempt, 4))));
    }
  };
  void run();
  return () => {
    stopped = true;
    controller.abort();
  };
}
