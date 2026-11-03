// Activity, resources, tests, metrics, needs, acceptance, screenshots, code, diff, note.
import { useEffect, useState } from "react";
import { Activity as ActivityIcon, Bot, Camera, GitBranch, Radio, ShieldAlert, Terminal } from "lucide-react";
import type { EngineEvent, WidgetSpec } from "@/contracts";
import { useStore } from "@/data/store";
import { useDataRef } from "./useData";
import { Empty, KeyValue, Loading, StatusChip, fmtNum, fmtTime } from "./common";

const EVENT_LABEL: Record<string, [string, string]> = {
  "opportunity.opened": ["info", "Oportunidad abierta"],
  "ask.opened": ["warn", "Pregunta para ti"],
  "ask.answered": ["ok", "Pregunta respondida"],
  "proposal.pushed": ["ok", "Rama subida"],
  "job.started": ["info", "Trabajo iniciado"],
  "job.finished": ["info", "Trabajo terminado"],
  "agent.note": ["info", "Nota del agente"],
  "decision.made": ["info", "Decisión tomada"],
  "experiment.started": ["accent", "Experimento iniciado"],
  "verdict.recorded": ["ok", "Veredicto registrado"],
  "verdict.revoked": ["warn", "Veredicto revocado"],
  "proposal.ready": ["ok", "Propuesta lista"],
  "proposal.published": ["ok", "Propuesta publicada"],
  "model.called": ["muted", "Llamada al modelo"],
  "model.fallback": ["warn", "Fallback de modelo"],
  "egress.allowed": ["muted", "Salida permitida"],
  "egress.blocked": ["bad", "Salida bloqueada"],
  "policy.denied": ["warn", "Política denegó"],
  "killswitch.changed": ["bad", "Kill switch"],
  "world.changed": ["info", "Mapa actualizado"],
  "anomaly.detected": ["bad", "Anomalía detectada"],
  "anomaly.resolved": ["ok", "Anomalía resuelta"],
  "deployment.observed": ["accent", "Despliegue observado"],
  "capability.needed": ["warn", "Capacidad necesaria"],
  "capability.built": ["ok", "Capacidad construida"],
  "connection.changed": ["info", "Conexión cambió"],
  "log.signal": ["muted", "Señal en logs"],
  "analyzer.ran": ["muted", "Analizador ejecutado"],
  "repo.head_moved": ["info", "HEAD movido"],
  "workspace.initialized": ["muted", "Workspace iniciado"],
};

export function eventLabel(type: string): [string, string] {
  return EVENT_LABEL[type] ?? ["muted", type];
}

function describe(e: EngineEvent): string {
  const p = e.payload;
  const s = (k: string) => (p[k] != null ? String(p[k]) : "");
  switch (e.type) {
    case "opportunity.opened":
      return s("title");
    case "decision.made":
      return `${s("chosen")} — ${s("reason")}`;
    case "verdict.recorded":
      return `${s("outcome") || (p.improved ? "mejoró" : "sin mejora")} · L${s("evidence_level")}`;
    case "model.called":
      return `${s("purpose")} · ${s("tier")} · ${s("model")} · ${s("tokens_in")}→${s("tokens_out")} tokens`;
    case "egress.allowed":
    case "egress.blocked":
      return `${s("purpose")} → ${s("destination")} (${s("bytes")} B)`;
    case "policy.denied":
      return `${s("rule")}: ${(Array.isArray(p.reasons) ? (p.reasons as string[]).join("; ") : s("why")) || s("purpose")}`;
    case "anomaly.detected":
    case "anomaly.resolved":
      return `${s("kind")} · ${s("why")}`;
    case "deployment.observed":
      return `#${s("index")} ${s("commit")} (${s("commit_status")})`;
    case "world.changed":
      return JSON.stringify(p.diff ?? {}).slice(0, 80);
    default:
      return Object.entries(p)
        .slice(0, 3)
        .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
        .join(" · ")
        .slice(0, 120);
  }
}

export function EventRow({ e, onClick }: { e: EngineEvent; onClick?: () => void }) {
  const [cls, label] = eventLabel(e.type);
  return (
    <button className="event-row nodrag" onClick={onClick} title={e.type}>
      <span className={`dot ${cls === "accent" ? "info" : cls}`} />
      <span className="col grow" style={{ gap: 1 }}>
        <span className="row">
          <span className="grow ellipsis small" style={{ color: "var(--ink)" }}>{label}</span>
          <span className="tiny muted">{fmtTime(e.ts)}</span>
        </span>
        <span className="tiny muted ellipsis">{describe(e)}</span>
      </span>
    </button>
  );
}

export function ActivityWidget({ widget }: { widget: WidgetSpec }) {
  const events = useStore((s) => s.events);
  const summary = useStore((s) => s.summary);
  const stream = useStore((s) => s.stream);
  const streamDetail = useStore((s) => s.streamDetail);
  const focus = useStore((s) => s.focus);
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const [timeline, setTimeline] = useState<{ ts: string | null; cycle: number; text: string; kind: string }[] | null>(null);
  const showTimeline = widget.view.options.timeline === true;
  useEffect(() => {
    if (!showTimeline || !api || !ws) return;
    api.timeline(ws, 0, 400).then((t) => setTimeline(t.items)).catch(() => setTimeline([]));
  }, [showTimeline, api, ws]);
  if (showTimeline) {
    if (!timeline) return <Loading />;
    if (!timeline.length) return <Empty title="Sin ciclos registrados" />;
    return (
      <div className="col scroll nowheel nodrag" style={{ height: "100%", padding: "0 6px 8px" }}>
        {timeline.map((t, i) =>
          t.kind === "cycle" ? (
            <div key={i} className="tiny muted" style={{ padding: "8px 8px 2px", letterSpacing: 0.5, textTransform: "uppercase" }}>{t.text}</div>
          ) : (
            <div key={i} className="row small" style={{ padding: "3px 8px", alignItems: "flex-start" }}>
              <span className="tiny muted mono" style={{ width: 54, flex: "none" }}>{t.ts ? fmtTime(t.ts) : ""}</span>
              <span className="ink2" style={{ lineHeight: 1.35 }}>{t.text.slice(0, 260)}</span>
            </div>
          ),
        )}
      </div>
    );
  }
  const mode = summary?.workspace.mode;
  const jobs = summary?.jobs ?? {};
  const running = jobs.running ?? 0;
  const queued = jobs.queued ?? 0;
  const recent = [...events].slice(-7).reverse();
  const live = mode === "live";
  const head = live
    ? running > 0
      ? `Trabajando: ${running} job(s) en curso, ${queued} en cola`
      : queued > 0
        ? `${queued} job(s) en cola; nada corriendo ahora`
        : "Sin trabajo en curso en este workspace"
    : mode === "historical"
      ? "Corrida cerrada: se reproduce el registro, no hay actividad actual"
      : "Demostración: eventos sintéticos, ninguna actividad real";
  const streamLabel: Record<string, [string, string]> = {
    live: ["ok", "en vivo"],
    connecting: ["muted", "conectando"],
    stale: ["warn", "desactualizado"],
    disconnected: ["bad", "desconectado"],
    closed: ["muted", "cerrado"],
  };
  const [scls, slabel] = streamLabel[stream] ?? ["muted", stream];
  return (
    <div className="col" style={{ height: "100%", padding: "2px 10px 8px", gap: 6 }}>
      <div className="row" style={{ gap: 8 }}>
        <span className={`activity-ring ${live && running > 0 ? "spin" : ""}`} aria-hidden="true" />
        <span className="small grow" style={{ fontWeight: 600 }}>{head}</span>
      </div>
      {summary?.workspace.notes.length ? (
        <div className="tiny muted" style={{ lineHeight: 1.35 }}>
          {summary.workspace.notes.slice(0, 3).map((n, i) => (
            <div key={i}>{n}</div>
          ))}
        </div>
      ) : null}
      <div className="col scroll nowheel grow" style={{ gap: 0 }}>
        {recent.length ? recent.map((e) => <EventRow key={e.seq ?? e.ts} e={e} onClick={() => e.correlation_id && focus(`c_finding_${e.correlation_id}`)} />) : <Empty title="Sin eventos recientes" />}
      </div>
      <div className="row tiny muted" style={{ borderTop: "1px solid var(--line)", paddingTop: 6 }}>
        <Radio size={12} />
        <span className={`chip ${scls}`} style={{ padding: "0 7px" }}>{slabel}</span>
        {streamDetail ? <span className="ellipsis">{streamDetail}</span> : null}
        <span className="grow" />
        <span>{summary ? `${summary.counts.events} eventos` : ""}</span>
      </div>
    </div>
  );
}

export function ResourcesWidget({ widget }: { widget: WidgetSpec }) {
  const { result, loading, error } = useDataRef(widget.dataRef ?? { dataset: "connections", params: {}, transform: { filter: [], limit: 100 } });
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (loading && !result) return <Loading />;
  if (!result?.rows.length) return <Empty kind="warn" title="Sin conexiones" detail={result?.provenance.note ?? "Nada fue inspeccionado todavía (unbidden connections)."} />;
  return (
    <div className="col scroll nowheel nodrag" style={{ height: "100%", padding: "0 6px 8px", gap: 2 }}>
      {result.rows.map((r, i) => {
        const read = Array.isArray(r.read) ? (r.read as string[]) : [];
        const write = Array.isArray(r.write) ? (r.write as string[]) : [];
        const state = String(r.state);
        const cls = state === "connected" ? "ok" : state === "degraded" || state.startsWith("needs") ? "warn" : state === "revoked" || state === "gone" ? "bad" : "muted";
        return (
          <div key={i} className="row" style={{ padding: "6px 8px", borderRadius: 10, alignItems: "flex-start" }}>
            <span className={`dot ${cls}`} style={{ marginTop: 6 }} />
            <span className="col grow" style={{ gap: 1 }}>
              <span className="row">
                <span className="mono small ellipsis grow" title={String(r.id)}>{String(r.id)}</span>
                <StatusChip status={state} />
              </span>
              <span className="tiny muted ellipsis">
                {String(r.kind)} · {String(r.environment)} · {read.length ? `lee ${read.slice(0, 3).join(", ")}` : "no lee nada"}
                {write.length ? ` · escribe ${write.join(", ")}` : ""}
              </span>
              {r.next_step ? <span className="tiny" style={{ color: "var(--amber)" }}>{String(r.next_step)}</span> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function TestsWidget({ widget }: { widget: WidgetSpec }) {
  const { result, loading, error } = useDataRef(widget.dataRef);
  if (!widget.dataRef) return <Empty kind="warn" title="Sin referencia de tests" />;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (loading && !result) return <Loading />;
  if (!result?.rows.length) return <Empty kind="warn" title="Sin tests registrados" detail={result?.provenance.note ?? "El registro no guarda rondas de tests."} />;
  if (widget.dataRef.dataset === "checks") {
    const c = result.rows[0] ?? {};
    return (
      <div className="col" style={{ padding: "4px 12px 10px", gap: 8 }}>
        <div className="row" style={{ gap: 8 }}>
          <StatusChip status={String(c.status)} />
          <span className="mono small muted">{String(c.rev)}</span>
          {c.partial ? <span className="chip warn">parte de la suite</span> : null}
        </div>
        <KeyValue items={[["Recogidos", fmtNum(c.collected)], ["Fallidos", fmtNum(c.failed)], ["Cuándo", fmtTime(String(c.at))], ...(c.why ? [["Por qué", String(c.why)] as [string, string]] : [])]} />
      </div>
    );
  }
  const arms = [...new Set(result.rows.map((r) => String(r.arm)))];
  const rounds = [...new Set(result.rows.map((r) => Number(r.round)))].sort((a, b) => a - b);
  const label = (a: string) => ({ before: "antes", after: "después" })[a] ?? a;
  return (
    <div className="col scroll nowheel nodrag" style={{ height: "100%", padding: "4px 12px 10px", gap: 8 }}>
      <table className="data">
        <thead>
          <tr>
            <th>lado</th>
            {rounds.map((r) => (
              <th key={r}>ronda {r}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {arms.map((a) => (
            <tr key={a}>
              <td>{label(a)}</td>
              {rounds.map((r) => {
                const row = result.rows.find((x) => String(x.arm) === a && Number(x.round) === r);
                if (!row) return <td key={r} className="muted">—</td>;
                const failed = Number(row.failed ?? 0);
                const status = String(row.status);
                const cls = status !== "ran" ? "bad" : failed > 0 ? "warn" : "ok";
                return (
                  <td key={r} title={Array.isArray(row.failed_tests) ? (row.failed_tests as string[]).join("\n") : ""}>
                    <span className="row" style={{ gap: 6 }}>
                      <span className={`dot ${cls}`} />
                      <span className="small">{status === "ran" ? `${fmtNum(row.collected)} · ${failed} fallo(s)` : status}</span>
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row tiny muted" style={{ gap: 10 }}>
        <span className="row" style={{ gap: 4 }}><span className="dot ok" /> pasó</span>
        <span className="row" style={{ gap: 4 }}><span className="dot warn" /> con fallos</span>
        <span className="row" style={{ gap: 4 }}><span className="dot bad" /> no corrió</span>
      </div>
    </div>
  );
}

export function MetricsWidget({ widget }: { widget: WidgetSpec }) {
  const { result, loading, error } = useDataRef(widget.dataRef);
  const content = widget.content as { items?: [string, string][] };
  if (!widget.dataRef && content.items) return <KeyValue items={content.items} />;
  if (!widget.dataRef) return <Empty kind="warn" title="Sin métricas" />;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (loading && !result) return <Loading />;
  if (!result?.rows.length) return <Empty kind="warn" title="Sin datos" detail={result?.provenance.note} />;
  const numeric = result.columns.filter((c) => c.type === "number");
  const tiles = numeric.slice(0, 6).map((c) => {
    const vals = result.rows.map((r) => r[c.name]).filter((v): v is number => typeof v === "number");
    const total = vals.reduce((a, b) => a + b, 0);
    return { name: c.name, unit: c.unit, value: vals.length ? (widget.view.options.agg === "mean" ? total / vals.length : total) : null, n: vals.length };
  });
  return (
    <div className="tiles nodrag" style={{ padding: "4px 12px 10px" }}>
      {tiles.map((t) => (
        <div key={t.name} className="tile">
          <div className="tiny muted ellipsis">{t.name}</div>
          <div className="tile-value">{fmtNum(t.value, t.unit)}</div>
          <div className="tiny muted">{t.n} fila(s)</div>
        </div>
      ))}
    </div>
  );
}

const stamp = () => Date.now(); // an idempotency key per click, made outside the render path

type AskSummary = {
  id: string;
  kind: string;
  title: string;
  why: string;
  options: { key: string; label: string; input: "none" | "secret" | "text" }[];
  default: string | null;
  cli: string | null;
};

// A question from the agent with its options as buttons; an option that takes a value asks for it first. Answering
// goes through the same module the app and `unbidden ask` use; the summary refreshes after.
function AskCard({ ask }: { ask: AskSummary }) {
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const toast = useStore((s) => s.toast);
  const refreshSummary = useStore((s) => s.refreshSummary);
  const [pending, setPending] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (option: string, v: string | null) => {
    if (!api || !ws) return;
    setBusy(true);
    try {
      const r = await api.action(ws, { operation: "answer", subject: ask.id, option, value: v, idempotency_key: `answer-${ask.id}-${option}-${stamp()}` });
      toast(r.detail, r.effect === "done" ? "ok" : "bad");
      setPending(null);
      setValue("");
      await refreshSummary();
    } catch (e) {
      toast(String(e), "bad");
    } finally {
      setBusy(false);
    }
  };
  const choose = (o: AskSummary["options"][number]) => {
    if (o.input === "none") void send(o.key, null);
    else setPending(o.key);
  };
  const needs = ask.options.find((o) => o.key === pending);
  return (
    <div className="need-item">
      <div className="row">
        <ShieldAlert size={14} color="var(--amber)" />
        <b className="small grow">{ask.title}</b>
        <span className="chip warn">{ask.kind}</span>
      </div>
      <div className="tiny ink2" style={{ lineHeight: 1.4 }}>{ask.why}</div>
      {needs ? (
        <div className="row" style={{ marginTop: 4, gap: 6 }}>
          <input className="input sm grow" type={needs.input === "secret" ? "password" : "text"} value={value} placeholder={needs.label} onChange={(e) => setValue(e.target.value)} />
          <button className="btn sm primary" disabled={busy || !value} onClick={() => void send(needs.key, value)}>Enviar</button>
          <button className="btn sm" disabled={busy} onClick={() => setPending(null)}>Cancelar</button>
        </div>
      ) : (
        <div className="row" style={{ marginTop: 4, gap: 6, flexWrap: "wrap" }}>
          {ask.options.map((o) => (
            <button key={o.key} className={`btn sm${o.key === ask.default ? " primary" : ""}`} disabled={busy} title={o.label} onClick={() => choose(o)}>
              {o.label.split(":")[0]}
            </button>
          ))}
        </div>
      )}
      {ask.cli ? <code className="tiny" style={{ color: "var(--ink-2)" }}>{ask.cli}</code> : null}
    </div>
  );
}

export function NeedWidget({ widget }: { widget: WidgetSpec }) {
  const summary = useStore((s) => s.summary);
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const toast = useStore((s) => s.toast);
  const [verdicts, setVerdicts] = useState<Record<string, string>>({});
  const a = (summary?.activity ?? {}) as {
    needs_a_person?: { connection?: string; proposal?: string; blocked?: string; state: string; what: string }[];
    blocks?: { operation: string; kind: string; needs: string; continues: string }[];
    capabilities?: { awaiting_approval?: { need: string; kind: string; source: string; capability: string }[] };
  };
  const people = a.needs_a_person ?? [];
  const blocks = a.blocks ?? [];
  const awaiting = a.capabilities?.awaiting_approval ?? [];
  const asks = (a as { asks?: AskSummary[] }).asks ?? [];
  const entityBlock = widget.entity?.kind === "block" ? widget.entity.id : null;
  if (!asks.length && !people.length && !blocks.length && !awaiting.length && !entityBlock) return <Empty title="Nada pendiente de una persona" detail="No hay preguntas, bloqueos, accesos ni aprobaciones esperando." />;
  const evaluate = async (capability: string) => {
    if (!api || !ws) return;
    try {
      const r = await api.action(ws, { operation: "evaluate", capability, reason: "consulta desde el espacio", idempotency_key: `eval-${capability}-${Date.now()}` });
      const v = r.verdict as { decision?: string; rule?: string; reasons?: string[] } | null;
      setVerdicts((s) => ({ ...s, [capability]: v ? `${v.decision} (${v.rule})` : r.detail }));
    } catch (e) {
      toast(String(e), "bad");
    }
  };
  return (
    <div className="col scroll nowheel nodrag" style={{ height: "100%", padding: "2px 10px 8px", gap: 6 }}>
      {asks.map((ask) => (
        <AskCard key={ask.id} ask={ask} />
      ))}
      {awaiting.map((n) => (
        <div key={n.need} className="need-item">
          <div className="row">
            <ShieldAlert size={14} color="var(--amber)" />
            <b className="small grow">Pendiente de aprobar: {n.kind}</b>
          </div>
          <div className="tiny muted">para {n.source}</div>
          <code className="tiny" style={{ color: "var(--ink-2)" }}>unbidden forge approve {n.capability}</code>
          <div className="row" style={{ marginTop: 4, gap: 6 }}>
            <button className="btn sm" onClick={() => void evaluate("capability.use")}>Ver política</button>
            {verdicts["capability.use"] ? <span className="tiny muted">{verdicts["capability.use"]}</span> : null}
          </div>
        </div>
      ))}
      {people.map((n, i) => (
        <div key={i} className="need-item">
          <div className="row">
            <ShieldAlert size={14} color="var(--amber)" />
            <b className="small grow ellipsis">{n.connection ?? n.proposal ?? n.blocked}</b>
            <StatusChip status={n.state} />
          </div>
          <div className="tiny ink2" style={{ lineHeight: 1.4 }}>{n.what}</div>
        </div>
      ))}
      {blocks.map((b, i) => (
        <div key={i} className="need-item">
          <div className="row">
            <ShieldAlert size={14} color="var(--amber)" />
            <b className="small grow ellipsis" title={b.operation}>{b.operation}</b>
            <span className="chip warn">{b.kind}</span>
          </div>
          <div className="tiny ink2" style={{ lineHeight: 1.4 }}>Necesita: {b.needs}</div>
          <div className="tiny muted">Luego continúa: {b.continues}</div>
        </div>
      ))}
      <div className="tiny muted" style={{ marginTop: 4 }}>Una aprobación de integración no autoriza escrituras sobre el servicio; cada acción se aprueba aparte.</div>
    </div>
  );
}

export function AcceptanceWidget() {
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const [items, setItems] = useState<Record<string, unknown>[] | null>(null);
  useEffect(() => {
    if (!api || !ws) return;
    api.collection(ws, "acceptances", 0, 50).then((r) => setItems(r.items)).catch(() => setItems([]));
  }, [api, ws]);
  if (!items) return <Loading />;
  if (!items.length) return <Empty title="Sin aceptaciones" detail="Ningún cambio ha sido juzgado por condiciones fijadas de antemano en este registro (las produce una meta sobre una página o una acción)." />;
  return (
    <div className="col scroll nowheel nodrag" style={{ height: "100%", padding: "2px 10px 8px", gap: 6 }}>
      {items.map((a, i) => {
        const outcomes = (a.outcomes ?? []) as { condition: string; status: string }[];
        return (
          <div key={i} className="need-item">
            <div className="row">
              <b className="small grow ellipsis">{String(a.subject)}</b>
              <StatusChip status={String(a.state)} />
            </div>
            <div className="tiny muted">el modelo dijo: {String(a.model_claim)} · {String(a.why)}</div>
            <div className="row tiny" style={{ gap: 6, flexWrap: "wrap" }}>
              {outcomes.map((o) => (
                <span key={o.condition} className={`chip ${o.status === "satisfied" ? "ok" : o.status === "failed" ? "bad" : "warn"}`}>{o.condition}</span>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ScreenshotsWidget({ widget }: { widget: WidgetSpec }) {
  const content = widget.content as { before?: string; after?: string };
  if (!content.before && !content.after)
    return (
      <Empty
        icon={<Camera size={18} />}
        title="Sin capturas en este registro"
        detail="Las capturas las produce una meta sobre lo que muestra una página (lab/ui) y se guardan en .unbidden/artifacts; este espacio no tiene ninguna."
      />
    );
  return <Empty title="Capturas" detail="Las rutas están en el registro; la vista previa de imágenes no se sirve desde el navegador." />;
}

export function CodeWidget({ widget }: { widget: WidgetSpec }) {
  const content = widget.content as { code?: string; path?: string };
  if (!content.code) return <Empty icon={<Terminal size={18} />} kind="warn" title="Sin código" detail="Esta tarjeta no trae contenido." />;
  const lines = content.code.replace(/\n$/, "").split("\n");
  return (
    <div className="col scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", gap: 6 }}>
      {content.path ? <div className="tiny mono muted">{content.path}</div> : null}
      <pre className="code">
        {lines.map((l, i) => (
          <span key={i} style={{ display: "block" }}>
            <span className="ln">{i + 1}</span>
            {l}
          </span>
        ))}
      </pre>
    </div>
  );
}

export function DiffWidget({ widget }: { widget: WidgetSpec }) {
  const content = widget.content as { diff?: string; path?: string };
  if (!content.diff) return <Empty icon={<GitBranch size={18} />} kind="warn" title="Sin diff" detail="El registro no guarda el parche de este cambio; la propuesta muestra lo que se publicó." />;
  return (
    <div className="col scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", gap: 6 }}>
      {content.path ? <div className="tiny mono muted">{content.path}</div> : null}
      <pre className="code">
        {content.diff.split("\n").map((l, i) => (
          <span key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : ""} style={{ display: "block" }}>
            {l}
          </span>
        ))}
      </pre>
    </div>
  );
}

export function NoteWidget({ widget }: { widget: WidgetSpec }) {
  const content = widget.content as { text?: string };
  return (
    <div className="scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
      {content.text ? <span className="ink2">{content.text}</span> : <span className="muted">Nota vacía. Edítala desde el inspector.</span>}
    </div>
  );
}

export const ICONS = { activity: ActivityIcon, bot: Bot };
