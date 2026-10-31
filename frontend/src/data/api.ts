// The API client: one session token, same-origin, every answer parsed by its schema.
import { z } from "zod";
import {
  ActionResponse,
  ChatMessage,
  DataRef,
  DataResult,
  EngineEvent,
  Presentation,
  SourceBrief,
  Summary,
} from "@/contracts";

const TOKEN_KEY = "unbidden.session";

export function readToken(): string | null {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("s");
  if (fromUrl) {
    sessionStorage.setItem(TOKEN_KEY, fromUrl);
    url.searchParams.delete("s");
    window.history.replaceState({}, "", url.pathname + url.search + url.hash);
    return fromUrl;
  }
  return sessionStorage.getItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class Api {
  constructor(private token: string) {}

  headers(extra: Record<string, string> = {}): Record<string, string> {
    return { Authorization: `Bearer ${this.token}`, ...extra };
  }

  private async call<T>(schema: z.ZodType<T>, path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(path, {
      ...init,
      headers: this.headers({ ...(init.body ? { "Content-Type": "application/json" } : {}), ...(init.headers as Record<string, string>) }),
    });
    const text = await res.text();
    let body: unknown;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    if (!res.ok) {
      const detail = (body as { error?: string } | null)?.error ?? res.statusText;
      throw new ApiError(res.status, detail);
    }
    return schema.parse(body);
  }

  session() {
    return this.call(z.object({ ok: z.boolean(), sources: z.array(SourceBrief) }), "/api/session");
  }
  summary(ws: string) {
    return this.call(Summary, `/api/ws/${enc(ws)}/summary`);
  }
  mandate(ws: string) {
    return this.call(z.object({ mandate: z.record(z.string(), z.unknown()), route: z.unknown(), autonomy: z.unknown() }), `/api/ws/${enc(ws)}/mandate`);
  }
  datasets() {
    return this.call(
      z.object({
        datasets: z.array(
          z.object({
            id: z.string(),
            title: z.string(),
            fields: z.array(z.object({ name: z.string(), type: z.string(), unit: z.string().nullable().optional() })),
            params: z.array(z.string()),
            unit: z.string().nullable().optional(),
            scope: z.string(),
          }),
        ),
      }),
      "/api/datasets",
    );
  }
  data(ws: string, ref: DataRef, signal?: AbortSignal) {
    return this.call(DataResult, `/api/ws/${enc(ws)}/data`, { method: "POST", body: JSON.stringify(ref), signal });
  }
  opportunities(ws: string, offset = 0, limit = 50) {
    return this.call(
      z.object({ items: z.array(z.record(z.string(), z.unknown())), total: z.number() }),
      `/api/ws/${enc(ws)}/opportunities?offset=${offset}&limit=${limit}`,
    );
  }
  opportunity(ws: string, id: string) {
    return this.call(
      z.object({
        opportunity: z.record(z.string(), z.unknown()),
        events: z.array(EngineEvent),
        experiment: z.record(z.string(), z.unknown()).nullable(),
        proposal: z.record(z.string(), z.unknown()).nullable(),
      }),
      `/api/ws/${enc(ws)}/opportunities/${enc(id)}`,
    );
  }
  collection(ws: string, name: string, offset = 0, limit = 50) {
    return this.call(
      z.object({ items: z.array(z.record(z.string(), z.unknown())), total: z.number() }),
      `/api/ws/${enc(ws)}/collection/${enc(name)}?offset=${offset}&limit=${limit}`,
    );
  }
  world(ws: string) {
    return this.call(
      z.object({
        world: z
          .object({
            rev: z.string(),
            resources: z.array(z.record(z.string(), z.unknown())),
            relations: z.array(z.record(z.string(), z.unknown())),
            blind_spots: z.array(z.object({ what: z.string(), why: z.string() })),
          })
          .nullable(),
      }),
      `/api/ws/${enc(ws)}/world`,
    );
  }
  timeline(ws: string, offset = 0, limit = 200) {
    return this.call(
      z.object({ items: z.array(z.object({ ts: z.string().nullable(), cycle: z.number(), text: z.string(), kind: z.string() })), total: z.number() }),
      `/api/ws/${enc(ws)}/timeline?offset=${offset}&limit=${limit}`,
    );
  }
  events(ws: string, after = 0, limit = 200) {
    return this.call(z.object({ items: z.array(EngineEvent), last_seq: z.number() }), `/api/ws/${enc(ws)}/events?after=${after}&limit=${limit}`);
  }
  presentation(ws: string) {
    return this.call(Presentation, `/api/ws/${enc(ws)}/presentation`);
  }
  savePresentation(ws: string, body: unknown) {
    return this.call(Presentation, `/api/ws/${enc(ws)}/presentation`, { method: "PUT", body: JSON.stringify(body) });
  }
  undo(ws: string) {
    return this.call(Presentation, `/api/ws/${enc(ws)}/presentation/undo`, { method: "POST" });
  }
  redo(ws: string) {
    return this.call(Presentation, `/api/ws/${enc(ws)}/presentation/redo`, { method: "POST" });
  }
  chat(ws: string) {
    return this.call(z.object({ messages: z.array(ChatMessage) }), `/api/ws/${enc(ws)}/chat`);
  }
  clearChat(ws: string) {
    return this.call(z.object({ deleted: z.number() }), `/api/ws/${enc(ws)}/chat`, { method: "DELETE" });
  }
  cancelChat(ws: string) {
    return this.call(z.object({ cancelled: z.boolean(), detail: z.string() }), `/api/ws/${enc(ws)}/chat/cancel`, { method: "POST" });
  }
  action(ws: string, body: unknown) {
    return this.call(ActionResponse, `/api/ws/${enc(ws)}/actions`, { method: "POST", body: JSON.stringify(body) });
  }
}

export const enc = (s: string) => encodeURIComponent(s);
