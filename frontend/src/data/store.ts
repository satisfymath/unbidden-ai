// The application state: session, the chosen workspace, its summary, the canvas (with server-side undo/redo), the
// live stream, the conversation, the selection and the UI. Persistence goes through the server; the canvas is saved
// debounced with its base version, and a stale save reloads instead of overwriting.
import { create } from "zustand";
import {
  type ChatMessage,
  type Edge,
  type EngineEvent,
  type Presentation,
  type SourceBrief,
  type Summary,
  type Viewport,
  type WidgetSpec,
  type CanvasConfig,
  WidgetSpec as WidgetSchema,
} from "@/contracts";
import { Api, ApiError, readToken } from "./api";
import { readSse, subscribeEvents, type StreamStatus } from "./sse";
import { compose, placeNew } from "@/canvas/composer";
import { REGISTRY } from "@/widgets/registry";

export type Tab = "space" | "experiments" | "activity";
export type Toast = { id: number; text: string; kind?: "info" | "warn" | "bad" | "ok"; action?: { label: string; run: () => void } };

export type ChatProgress = { state: string; detail?: string } | null;

type State = {
  api: Api | null;
  token: string | null;
  sources: SourceBrief[];
  ws: string | null;
  summary: Summary | null;
  summaryError: string | null;
  presentation: Presentation | null;
  presentationError: string | null;
  saving: boolean;
  savedAt: number | null;
  dirty: boolean;
  selection: string[];
  tab: Tab;
  chatOpen: boolean;
  inspectorOpen: boolean;
  settingsOpen: boolean;
  addMenuOpen: boolean;
  messages: ChatMessage[];
  chatProgress: ChatProgress;
  chatBusy: boolean;
  events: EngineEvent[];
  lastSeq: number;
  stream: StreamStatus;
  streamDetail?: string;
  newSince: number;
  toasts: Toast[];
  focusWidget: string | null;
  mobile: boolean;
  reducedMotion: boolean;

  boot: () => Promise<void>;
  selectWorkspace: (id: string) => Promise<void>;
  refreshSummary: () => Promise<void>;
  loadPresentation: () => Promise<void>;
  setWidgets: (widgets: WidgetSpec[], reason?: string) => void;
  patchWidget: (id: string, patch: Partial<WidgetSpec>, reason?: string) => void;
  addWidget: (spec: Partial<WidgetSpec> & Pick<WidgetSpec, "type" | "title">, near?: string) => string;
  removeWidgets: (ids: string[]) => void;
  duplicateWidget: (id: string) => void;
  setEdges: (edges: Edge[], reason?: string) => void;
  setViewport: (viewport: Viewport) => void;
  setConfig: (config: Partial<CanvasConfig>) => void;
  save: (reason?: string) => Promise<void>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  autoLayout: () => void;
  composeNow: () => void;
  setSelection: (ids: string[]) => void;
  setTab: (tab: Tab) => void;
  setChatOpen: (open: boolean) => void;
  setInspectorOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
  setAddMenuOpen: (open: boolean) => void;
  sendChat: (text: string, planner?: "auto" | "rule" | "brain") => Promise<void>;
  cancelChat: () => Promise<void>;
  clearChat: () => Promise<void>;
  toast: (text: string, kind?: Toast["kind"], action?: Toast["action"]) => void;
  dismissToast: (id: number) => void;
  focus: (id: string | null) => void;
  markSeen: () => void;
};

let saveTimer: number | null = null;
let unsubscribe: (() => void) | null = null;
let toastSeq = 0;
let saveChain: Promise<void> = Promise.resolve();

export const useStore = create<State>((set, get) => ({
  api: null,
  token: null,
  sources: [],
  ws: null,
  summary: null,
  summaryError: null,
  presentation: null,
  presentationError: null,
  saving: false,
  savedAt: null,
  dirty: false,
  selection: [],
  tab: "space",
  chatOpen: false,
  inspectorOpen: false,
  settingsOpen: false,
  addMenuOpen: false,
  messages: [],
  chatProgress: null,
  chatBusy: false,
  events: [],
  lastSeq: 0,
  stream: "connecting",
  newSince: 0,
  toasts: [],
  focusWidget: null,
  mobile: typeof window !== "undefined" && window.innerWidth < 760,
  reducedMotion: typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,

  async boot() {
    const token = readToken();
    if (!token) {
      set({ summaryError: "no-token" });
      return;
    }
    const api = new Api(token);
    set({ api, token });
    try {
      const { sources } = await api.session();
      set({ sources });
      const wanted = localStorage.getItem("unbidden.ws");
      const first = sources.find((s) => s.id === wanted) ?? sources[0];
      if (first) await get().selectWorkspace(first.id);
    } catch (err) {
      set({ summaryError: err instanceof ApiError && err.status === 401 ? "no-token" : String(err) });
    }
  },

  async selectWorkspace(id) {
    unsubscribe?.();
    unsubscribe = null;
    localStorage.setItem("unbidden.ws", id);
    set({ ws: id, summary: null, presentation: null, selection: [], events: [], lastSeq: 0, messages: [], newSince: 0, stream: "connecting" });
    await get().refreshSummary();
    await get().loadPresentation();
    const api = get().api;
    const s = get().summary;
    if (!api || !s) return;
    try {
      const { messages } = await api.chat(id);
      set({ messages });
    } catch {
      /* the conversation is optional */
    }
    try {
      const after = Math.max(0, s.last_event_seq - 60);
      const { items, last_seq } = await api.events(id, after, 200);
      set({ events: items, lastSeq: last_seq });
    } catch {
      /* events are shown as they arrive */
    }
    unsubscribe = subscribeEvents({
      url: `/api/ws/${encodeURIComponent(id)}/events/stream`,
      headers: api.headers(),
      after: get().lastSeq,
      onEngine: (data, seq) => {
        const parsed = { ...data, seq } as EngineEvent;
        set((st) => ({ events: [...st.events.slice(-499), parsed], lastSeq: seq, newSince: st.newSince + 1 }));
        get().refreshSummary().catch(() => undefined);
      },
      onStatus: (status, detail) => set({ stream: status, streamDetail: detail }),
    });
  },

  async refreshSummary() {
    const { api, ws } = get();
    if (!api || !ws) return;
    try {
      const summary = await api.summary(ws);
      set({ summary, summaryError: null });
    } catch (err) {
      set({ summaryError: err instanceof Error ? err.message : String(err) });
    }
  },

  async loadPresentation() {
    const { api, ws, summary } = get();
    if (!api || !ws) return;
    try {
      let presentation = await api.presentation(ws);
      if (presentation.widgets.length === 0 && presentation.version === 0 && summary) {
        const composed = compose(summary);
        presentation = { ...presentation, widgets: composed.widgets, edges: composed.edges };
        set({ presentation, dirty: true });
        await get().save("composición inicial");
      } else {
        set({ presentation, presentationError: null, dirty: false });
      }
    } catch (err) {
      set({ presentationError: err instanceof Error ? err.message : String(err) });
    }
  },

  setWidgets(widgets, reason) {
    const p = get().presentation;
    if (!p) return;
    set({ presentation: { ...p, widgets }, dirty: true });
    scheduleSave(get, reason);
  },

  patchWidget(id, patch, reason) {
    const p = get().presentation;
    if (!p) return;
    const widgets = p.widgets.map((w) => (w.id === id ? WidgetSchema.parse({ ...w, ...patch }) : w));
    set({ presentation: { ...p, widgets }, dirty: true });
    scheduleSave(get, reason ?? "editar tarjeta");
  },

  addWidget(spec, near) {
    const p = get().presentation;
    const id = spec.id ?? `w_${Math.random().toString(36).slice(2, 12)}`;
    const widgets = p?.widgets ?? [];
    const anchor = near ?? get().selection[0] ?? null;
    const size = spec.size ?? REGISTRY[spec.type].size;
    const position = spec.position ?? placeNew(widgets, size, anchor);
    const widget = WidgetSchema.parse({ ...spec, id, position, size });
    get().setWidgets([...widgets, widget], `añadir ${widget.type}`);
    set({ focusWidget: id, selection: [id] });
    return id;
  },

  removeWidgets(ids) {
    const p = get().presentation;
    if (!p) return;
    const removed = p.widgets.filter((w) => ids.includes(w.id));
    const widgets = p.widgets.filter((w) => !ids.includes(w.id) || w.pinned);
    const edges = p.edges.filter((e) => !ids.includes(e.source) && !ids.includes(e.target));
    set({ presentation: { ...p, widgets, edges }, dirty: true, selection: [] });
    scheduleSave(get, `quitar ${removed.length} tarjeta(s)`);
    get().toast(`${removed.length} tarjeta(s) quitada(s) del lienzo; nada del motor cambió`, "info", {
      label: "Deshacer",
      run: () => void get().undo(),
    });
  },

  duplicateWidget(id) {
    const p = get().presentation;
    const w = p?.widgets.find((x) => x.id === id);
    if (!w) return;
    const { id: _id, position: _pos, ...rest } = w;
    get().addWidget({ ...rest, title: `${w.title} (copia)`, created_by: "user", pinned: false }, id);
  },

  setEdges(edges, reason) {
    const p = get().presentation;
    if (!p) return;
    set({ presentation: { ...p, edges }, dirty: true });
    scheduleSave(get, reason ?? "conexiones");
  },

  setViewport(viewport) {
    const p = get().presentation;
    if (!p) return;
    set({ presentation: { ...p, viewport } });
    scheduleSave(get, "viewport", 1500);
  },

  setConfig(config) {
    const p = get().presentation;
    if (!p) return;
    set({ presentation: { ...p, config: { ...p.config, ...config } }, dirty: true });
    scheduleSave(get, "configuración");
  },

  save(reason = "editar") {
    // Saves are serialised: each one reads the version the previous one left, so two edits never race to a 409.
    saveChain = saveChain.then(() => saveNow(reason)).catch(() => undefined);
    return saveChain;
  },

  async undo() {
    const { api, ws } = get();
    if (!api || !ws) return;
    if (saveTimer) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
      await get().save();
    }
    try {
      const p = await api.undo(ws);
      set({ presentation: p, dirty: false, selection: [] });
    } catch (err) {
      get().toast(err instanceof ApiError && err.status === 409 ? "Nada que deshacer" : String(err), "info");
    }
  },

  async redo() {
    const { api, ws } = get();
    if (!api || !ws) return;
    try {
      const p = await api.redo(ws);
      set({ presentation: p, dirty: false, selection: [] });
    } catch (err) {
      get().toast(err instanceof ApiError && err.status === 409 ? "Nada que rehacer" : String(err), "info");
    }
  },

  autoLayout() {
    const p = get().presentation;
    if (!p) return;
    const sorted = [...p.widgets].sort((a, b) => a.position.y - b.position.y || a.position.x - b.position.x);
    const gap = 40;
    const columns = 3;
    const colW = Math.max(...sorted.map((w) => w.size.w), 420) + gap;
    const ys = new Array(columns).fill(80) as number[];
    const widgets = sorted.map((w, i) => {
      const c = i % columns;
      const position = { x: 80 + c * colW, y: ys[c] ?? 80 };
      ys[c] = (ys[c] ?? 80) + w.size.h + gap;
      return { ...w, position };
    });
    get().setWidgets(widgets, "distribución automática");
  },

  composeNow() {
    const { summary, presentation } = get();
    if (!summary || !presentation) return;
    const composed = compose(summary);
    const existing = new Set(presentation.widgets.map((w) => w.id));
    const fresh = composed.widgets.filter((w) => !existing.has(w.id));
    if (!fresh.length) {
      get().toast("El espacio ya muestra todo lo que el registro permite", "info");
      return;
    }
    const bottom = Math.max(0, ...presentation.widgets.map((w) => w.position.y + w.size.h));
    const placed = fresh.map((w, i) => ({ ...w, position: { x: 80 + (i % 3) * 480, y: bottom + 60 + Math.floor(i / 3) * 360 } }));
    const ids = new Set([...existing, ...placed.map((w) => w.id)]);
    const edges = [...presentation.edges, ...composed.edges.filter((e) => ids.has(e.source) && ids.has(e.target) && !presentation.edges.some((x) => x.id === e.id))];
    set({ presentation: { ...presentation, widgets: [...presentation.widgets, ...placed], edges }, dirty: true });
    scheduleSave(get, "componer novedades");
    get().toast(`${placed.length} tarjeta(s) nueva(s) añadidas debajo de lo que ya tenías`, "ok", { label: "Ver", run: () => get().focus(placed[0]?.id ?? null) });
  },

  setSelection(ids) {
    set({ selection: ids, inspectorOpen: ids.length > 0 ? get().inspectorOpen : false });
  },
  setTab(tab) {
    set({ tab });
  },
  setChatOpen(open) {
    set({ chatOpen: open });
  },
  setInspectorOpen(open) {
    set({ inspectorOpen: open });
  },
  setSettingsOpen(open) {
    set({ settingsOpen: open });
  },
  setAddMenuOpen(open) {
    set({ addMenuOpen: open });
  },

  async sendChat(text, planner = "auto") {
    const { api, ws, selection } = get();
    if (!api || !ws || !text.trim()) return;
    if (saveTimer) {
      window.clearTimeout(saveTimer);
      saveTimer = null;
      await get().save();
    }
    set({ chatBusy: true, chatProgress: { state: "thinking" } });
    const controller = new AbortController();
    try {
      await readSse(
        `/api/ws/${encodeURIComponent(ws)}/chat`,
        { method: "POST", headers: api.headers({ "Content-Type": "application/json" }), body: JSON.stringify({ content: text, selected: selection, planner }) },
        (e) => {
          if (e.event === "message") {
            const msg = e.data as ChatMessage;
            set((st) => ({ messages: [...st.messages.filter((m) => m.id !== msg.id), msg] }));
          } else if (e.event === "state") {
            set({ chatProgress: { state: String((e.data as { state: string }).state) } });
          } else if (e.event === "tool_call") {
            const d = e.data as { name: string };
            set({ chatProgress: { state: "building", detail: d.name } });
          } else if (e.event === "tool_result") {
            const r = e.data as { ok: boolean; widget_id?: string | null; tool: string };
            if (r.ok && r.widget_id) set({ focusWidget: r.widget_id });
          } else if (e.event === "error") {
            get().toast(String((e.data as { detail: string }).detail), "bad");
          }
        },
        controller.signal,
      );
    } catch (err) {
      get().toast(`Chat: ${err instanceof Error ? err.message : String(err)}`, "bad");
    } finally {
      set({ chatBusy: false, chatProgress: null });
      await get().loadPresentation();
    }
  },

  async cancelChat() {
    const { api, ws } = get();
    if (!api || !ws) return;
    const r = await api.cancelChat(ws);
    get().toast(r.detail, r.cancelled ? "warn" : "info");
  },

  async clearChat() {
    const { api, ws } = get();
    if (!api || !ws) return;
    await api.clearChat(ws);
    set({ messages: [] });
    get().toast("Conversación borrada; la auditoría del motor no cambia", "info");
  },

  toast(text, kind = "info", action) {
    const id = ++toastSeq;
    set((st) => ({ toasts: [...st.toasts.slice(-3), { id, text, kind, action }] }));
    window.setTimeout(() => get().dismissToast(id), action ? 9000 : 5000);
  },
  dismissToast(id) {
    set((st) => ({ toasts: st.toasts.filter((t) => t.id !== id) }));
  },
  focus(id) {
    set({ focusWidget: id, ...(id ? { selection: [id], tab: "space" as Tab } : {}) });
  },
  markSeen() {
    set({ newSince: 0 });
  },
}));


async function saveNow(reason: string): Promise<void> {
  const get = useStore.getState;
  const set = useStore.setState;
  const { api, ws, presentation } = get();
  if (!api || !ws || !presentation) return;
  set({ saving: true });
  try {
      const saved = await api.savePresentation(ws, {
        base_version: presentation.version,
        widgets: presentation.widgets,
        edges: presentation.edges,
        viewport: presentation.viewport,
        config: presentation.config,
        reason,
      });
      // Keep local edits made while the request flew; adopt the server's version.
      const current = get().presentation ?? saved;
      set({ presentation: { ...current, version: saved.version, history: saved.history }, saving: false, savedAt: Date.now(), dirty: false, presentationError: null });
    } catch (err) {
      set({ saving: false });
      if (err instanceof ApiError && err.status === 409) {
        get().toast("El lienzo cambió en otra pestaña; recargado sin sobrescribir", "warn");
        await get().loadPresentation();
      } else if (err instanceof ApiError && err.status === 422) {
        get().toast(`Especificación rechazada: ${err.message}`, "bad");
        await get().loadPresentation();
      } else {
        set({ presentationError: err instanceof Error ? err.message : String(err) });
      }
    }
}

function scheduleSave(get: () => State, reason?: string, delay = 600) {
  if (saveTimer) window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    saveTimer = null;
    void get().save(reason);
  }, delay);
}

export function flushSave(): Promise<void> {
  if (saveTimer) {
    window.clearTimeout(saveTimer);
    saveTimer = null;
    return useStore.getState().save();
  }
  return Promise.resolve();
}
