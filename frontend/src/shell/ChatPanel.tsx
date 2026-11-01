// The conversation over the dimmed canvas: history, progress states, context chips, cancel and clear.
import { useEffect, useRef } from "react";
import { Bot, Check, Loader2, Trash2, User, X, XCircle } from "lucide-react";
import { Logo } from "@/components/Logo";
import { useStore } from "@/data/store";
import { REGISTRY } from "@/widgets/registry";
import { fmtTime } from "@/widgets/common";

const STATE_LABEL: Record<string, string> = {
  thinking: "Pensando…",
  reading: "Consultando datos…",
  building: "Construyendo visualización…",
};

const INTENT_LABEL: Record<string, string> = { inform: "informar", analyze: "analizar", act: "acción (no desde el chat)" };

const SUGGESTIONS = [
  "Muéstrame la latencia antes y después de este experimento",
  "Añade una tabla con los tests que fallaron",
  "Grafica el gasto por corrida",
  "Explícame este bloqueo y añade sus dependencias al mapa",
  "Cambia ese gráfico a barras",
  "Deshaz la última tarjeta",
  "¿Por qué sólo una oportunidad llegó a probarse?",
];

export function ChatPanel() {
  const open = useStore((s) => s.chatOpen);
  const setOpen = useStore((s) => s.setChatOpen);
  const messages = useStore((s) => s.messages);
  const progress = useStore((s) => s.chatProgress);
  const busy = useStore((s) => s.chatBusy);
  const cancel = useStore((s) => s.cancelChat);
  const clear = useStore((s) => s.clearChat);
  const send = useStore((s) => s.sendChat);
  const selection = useStore((s) => s.selection);
  const presentation = useStore((s) => s.presentation);
  const focus = useStore((s) => s.focus);
  const summary = useStore((s) => s.summary);
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [messages, progress, open]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, setOpen]);
  if (!open) return null;
  const selected = (presentation?.widgets ?? []).filter((w) => selection.includes(w.id));
  const route = summary?.connection.route;
  const remoteNote = route?.remote.key_present ? `análisis por ${route.remote.model ?? "Meta API"} según el mandato` : "análisis: sin clave remota";
  const localNote = route?.local.reachable ? `modelo local ${route.local.model ?? ""}` : "sin modelo local";
  const plannerNote = `informar: registros y reglas · ${localNote} · ${remoteNote} · actuar: botones o CLI`;
  return (
    <>
      <div className="chat-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />
      <div className="chat-pos">
      <section className="chat-panel glass-2 glass" role="dialog" aria-label="conversación con Unbidden">
        <header>
          <Logo size={18} />
          <b className="grow">Unbidden</b>
          <span className="tiny muted ellipsis" style={{ maxWidth: 320 }} title={plannerNote}>{plannerNote}</span>
          <button className="btn ghost icon" onClick={() => void clear()} aria-label="borrar conversación" title="Borrar la conversación (no la auditoría)"><Trash2 size={14} /></button>
          <button className="btn ghost icon" onClick={() => setOpen(false)} aria-label="cerrar"><X size={16} /></button>
        </header>
        <div className="chat-log scroll" ref={log}>
          {!messages.length ? (
            <div className="col" style={{ gap: 8 }}>
              <div className="small muted">Pide un gráfico, una tabla o una explicación sobre lo que hay en el registro. Lo que falte, lo diré en lugar de inventarlo.</div>
              <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="btn sm" onClick={() => void send(s)}>{s}</button>
                ))}
              </div>
            </div>
          ) : null}
          {messages.map((m) => (
            <div key={m.id} className={`msg ${m.role}`}>
              <span className="avatar">{m.role === "user" ? <User size={14} /> : <Bot size={14} />}</span>
              <div className="col" style={{ gap: 4, minWidth: 0 }}>
                <div className={`bubble ${m.state === "error" ? "bad" : ""}`}>
                  {m.content}
                  {m.results.length ? (
                    <div className="tools">
                      {m.results.map((r, i) => (
                        <div key={i} className={`tool-line ${r.ok ? "" : "bad"}`}>
                          {r.ok ? <Check size={12} /> : <XCircle size={12} />}
                          <code>{r.tool}</code>
                          <span className="ellipsis">{r.summary}</span>
                          {r.widget_id ? <button className="btn sm" onClick={() => { setOpen(false); focus(r.widget_id!); }}>Ver widget ↗</button> : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
                <span className="tiny muted">
                  {fmtTime(m.created_at)}{m.planner ? ` · ${m.planner === "brain" ? `modelo ${m.model ?? ""}` : "reglas"}` : ""}{m.state === "cancelled" ? " · cancelado" : ""}
                  {m.route ? ` · ${INTENT_LABEL[m.route.intent]}${m.route.purpose ? ` · ${m.route.purpose}` : ""}${m.route.tier && m.route.intent === "analyze" && !m.route.blocked ? ` · ${m.route.tier === "local" ? "modelo local" : "Meta API"}` : ""}` : ""}
                </span>
                {m.route?.blocked ? (
                  <span className="tiny" style={{ color: "var(--amber)" }} title={m.route.blocked}>
                    sin modelo: {m.route.blocked.slice(0, 160)}{m.route.hint ? ` · lo permitiría: ${m.route.hint}` : ""}
                  </span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
        {busy ? (
          <div className="chat-progress" aria-live="polite">
            <Loader2 size={14} className="spin" />
            <span>{STATE_LABEL[progress?.state ?? "thinking"] ?? progress?.state}{progress?.detail ? ` (${progress.detail})` : ""}</span>
            <span className="grow" />
            <button className="btn sm" onClick={() => void cancel()}>Cancelar</button>
          </div>
        ) : null}
        <div className="context-chips">
          <span className="tiny muted">Contexto:</span>
          {selected.length ? (
            selected.map((w) => {
              const Icon = REGISTRY[w.type].icon;
              return (
                <span key={w.id} className="chip accent"><Icon size={11} /> {w.title}</span>
              );
            })
          ) : (
            <span className="tiny muted">ninguna tarjeta seleccionada (selecciona una en el lienzo para que el chat la use)</span>
          )}
        </div>
      </section>
      </div>
    </>
  );
}
