// Widgets anchored on an entity of the record: a finding, its experiment, its proposal, a minimal case, a query.
import { useEffect, useState } from "react";
import { Check, Circle, CircleDot } from "lucide-react";
import type { WidgetSpec } from "@/contracts";
import { useStore } from "@/data/store";
import { Empty, EvidenceList, KeyValue, LevelChip, Loading, StatusChip, fmtNum, fmtTime } from "./common";
import { DecideButtons } from "./Decide";

type Detail = {
  opportunity: Record<string, unknown>;
  events: { ts: string; type: string; payload: Record<string, unknown> }[];
  experiment: Record<string, unknown> | null;
  proposal: Record<string, unknown> | null;
};

const detailCache = new Map<string, { at: number; d: Detail }>();

export function useOpportunity(id: string | null | undefined) {
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const lastSeq = useStore((s) => s.lastSeq);
  const [loaded, setLoaded] = useState<{ key: string; detail: Detail | null; error: string | null } | null>(null);
  const key = ws && id ? `${ws}|${id}` : null;
  const fetchKey = key ? `${key}|${lastSeq}` : null;
  useEffect(() => {
    if (!api || !ws || !id || !key || !fetchKey) return;
    const cached = detailCache.get(key);
    if (cached && Date.now() - cached.at < 5000 && loaded?.key === fetchKey) return;
    let alive = true;
    api
      .opportunity(ws, id)
      .then((d) => {
        detailCache.set(key, { at: Date.now(), d: d as Detail });
        if (alive) setLoaded({ key: fetchKey, detail: d as Detail, error: null });
      })
      .catch((e: unknown) => alive && setLoaded({ key: fetchKey, detail: detailCache.get(key)?.d ?? null, error: e instanceof Error ? e.message : String(e) }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, ws, id, fetchKey]);
  const current = loaded && loaded.key === fetchKey ? loaded : null;
  const detail = current?.detail ?? (key ? (detailCache.get(key)?.d ?? null) : null);
  return { detail, error: current?.error ?? null };
}

function entityId(widget: WidgetSpec, kinds: string[]): string | null {
  return widget.entity && kinds.includes(widget.entity.kind) ? widget.entity.id : null;
}

export function FindingWidget({ widget }: { widget: WidgetSpec }) {
  const id = entityId(widget, ["opportunity"]);
  const { detail, error } = useOpportunity(id);
  if (!id) return <Empty kind="warn" title="Sin hallazgo" detail="Esta tarjeta no apunta a ninguna oportunidad." />;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (!detail) return <Loading />;
  const o = detail.opportunity;
  const details = (o.details ?? {}) as Record<string, unknown>;
  const decision = (details.decision ?? {}) as Record<string, unknown>;
  const blocked = (details.blocked ?? null) as { why?: string } | null;
  const evidence = (o.evidence ?? []) as { kind: string; locator: string; note?: string | null }[];
  return (
    <div className="col scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", gap: 8 }}>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <LevelChip level={Number(o.evidence_level)} />
        <StatusChip status={String(o.status)} />
        <span className="chip muted">{String(o.source)} · {String(o.category)}</span>
      </div>
      <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.35 }}>{String(o.title)}</div>
      <div className="small ink2" style={{ lineHeight: 1.45 }}>{String(o.summary)}</div>
      {decision.chosen ? (
        <div className="small" style={{ padding: "8px 10px", background: "rgba(243,241,236,0.08)", borderRadius: 10 }}>
          <span className="muted">Decisión</span> <b>{String(decision.chosen)}</b>
          <div className="muted" style={{ marginTop: 2 }}>{String(decision.reason ?? "")}</div>
        </div>
      ) : null}
      {blocked?.why ? (
        <div className="small" style={{ padding: "8px 10px", background: "var(--amber-soft)", borderRadius: 10, color: "var(--amber)" }}>
          <b>Bloqueado</b> <span style={{ color: "var(--ink-2)" }}>{blocked.why}</span>
        </div>
      ) : null}
      <EvidenceList items={evidence.slice(0, 5)} />
      {String(o.status) === "open" ? <DecideButtons opportunityId={String(o.id)} canApprove={Boolean(detail.proposal && String((detail.proposal as { status?: unknown }).status) === "ready")} /> : null}
    </div>
  );
}

function Step({ label, state }: { label: string; state: "done" | "active" | "todo" }) {
  const icon = state === "done" ? <Check size={12} /> : state === "active" ? <CircleDot size={12} /> : <Circle size={12} />;
  const color = state === "done" ? "var(--accent)" : state === "active" ? "var(--amber)" : "var(--muted-2)";
  return (
    <div className="col" style={{ alignItems: "center", gap: 4, flex: 1 }}>
      <span className="step-dot" style={{ borderColor: color, color }}>{icon}</span>
      <span className="tiny" style={{ color: state === "todo" ? "var(--muted)" : "var(--ink-2)" }}>{label}</span>
    </div>
  );
}

export function ExperimentWidget({ widget }: { widget: WidgetSpec }) {
  const id = entityId(widget, ["opportunity", "experiment"]);
  const { detail, error } = useOpportunity(widget.entity?.kind === "opportunity" ? id : null);
  if (!id) return <Empty kind="warn" title="Sin experimento" detail="Esta tarjeta no apunta a ninguna oportunidad ni experimento." />;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (!detail) return <Loading />;
  const exp = detail.experiment;
  const details = (detail.opportunity.details ?? {}) as Record<string, unknown>;
  const verdict = (details.verdict ?? null) as Record<string, unknown> | null;
  if (!exp) return <Empty kind="warn" title="Todavía sin experimento" detail="La oportunidad no ha sido medida; el motor lo hará cuando la decisión sea run_experiment (o `unbidden try <id>`)." />;
  const counts = (exp.counts ?? {}) as Record<string, number>;
  const cost = (exp.cost ?? {}) as Record<string, number>;
  const tests = String(verdict?.tests ?? "");
  const level = Number(verdict?.evidence_level ?? detail.opportunity.evidence_level ?? 1);
  const reproduced = level >= 2 ? "done" : "active";
  const compared = (counts.sessions ?? 0) + (counts.samples_before ?? 0) > 0 ? "done" : reproduced === "done" ? "active" : "todo";
  const validated = tests === "passed" || tests === "pre_existing" ? "done" : compared === "done" ? (verdict ? "active" : "todo") : "todo";
  const outcome = String(verdict?.outcome ?? (verdict ? (verdict.improved ? "improved" : "no_improvement") : "pendiente"));
  return (
    <div className="col scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", gap: 10 }}>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <span className={`chip ${outcome === "improved" ? "ok" : outcome.includes("inconclusive") || outcome === "pendiente" ? "warn" : "muted"}`}>{outcome}</span>
        {verdict ? <LevelChip level={level} /> : null}
        <span className="chip muted mono">{String(exp.id).slice(-8)}</span>
      </div>
      <div className="row" style={{ gap: 0, padding: "4px 0" }}>
        <Step label="Reproducir" state={reproduced} />
        <span className="step-line" />
        <Step label="Comparar" state={compared} />
        <span className="step-line" />
        <Step label="Validar" state={validated} />
      </div>
      <KeyValue
        items={[
          ["Sesiones", `${counts.sessions ?? 0} medidas · ${counts.control ?? 0} control · ${counts.confirmation ?? 0} confirmación`],
          ["Muestras", `${counts.samples_before ?? 0} antes · ${counts.samples_after ?? 0} después`],
          ["Tests", tests ? <StatusChip status={tests} /> : <span className="muted">no registrados</span>],
          ["Coste", `US$ ${fmtNum((cost.usd_remote ?? 0) + (cost.usd_local ?? 0))} · ${fmtNum(cost.tokens_in)} tokens`],
          ["Inicio", fmtTime(String(exp.started_at))],
        ]}
      />
      {verdict && Array.isArray(verdict.reasons) ? (
        <ul className="small ink2" style={{ margin: 0, paddingLeft: 16 }}>
          {(verdict.reasons as string[]).slice(0, 4).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : null}
      {verdict && Array.isArray(verdict.caveats) && (verdict.caveats as string[]).length ? (
        <div className="small" style={{ color: "var(--amber)" }}>⚠ {(verdict.caveats as string[]).join("; ")}</div>
      ) : null}
      {verdict?.scope ? <div className="tiny muted">Alcance: {String(verdict.scope)}</div> : null}
    </div>
  );
}

function fencedBlocks(md: string): { lang: string; code: string }[] {
  const out: { lang: string; code: string }[] = [];
  const re = /```(\w*)\n([\s\S]*?)```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(md))) out.push({ lang: m[1] ?? "", code: m[2] ?? "" });
  return out;
}

export function ProposalWidget({ widget }: { widget: WidgetSpec }) {
  const id = entityId(widget, ["opportunity", "proposal"]);
  const { detail, error } = useOpportunity(id);
  if (!id) return <Empty kind="warn" title="Sin propuesta" />;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (!detail) return <Loading />;
  const p = detail.proposal;
  if (!p) return <Empty kind="warn" title="Todavía sin propuesta" detail="Nada alcanzó L4 para esta oportunidad; una propuesta se prepara solo con la validación de la suite del proyecto." />;
  const body = String(p.body_md ?? "");
  const blocks = fencedBlocks(body);
  const prose = body.replace(/```[\s\S]*?```/g, "").trim();
  return (
    <div className="col scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", gap: 8 }}>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <StatusChip status={String(p.status)} />
        <LevelChip level={Number(p.evidence_level)} />
        <span className="chip muted mono ellipsis" style={{ maxWidth: 220 }} title={String(p.branch)}>{String(p.branch)}</span>
      </div>
      <div style={{ fontWeight: 600, lineHeight: 1.35 }}>{String(p.title)}</div>
      {prose ? <pre className="small ink2" style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "var(--sans)" }}>{prose.slice(0, 1200)}</pre> : null}
      {blocks.map((b, i) => (
        <pre key={i} className="code nowheel" style={{ maxHeight: 160 }}>
          {b.code}
        </pre>
      ))}
      {p.pr ? <div className="small muted">PR: {String((p.pr as { url?: string }).url ?? "")}</div> : <div className="tiny muted">Sin PR aún: se abre con aprobación (`unbidden approve {String(p.opportunity_id)}`).</div>}
      {!p.pr && String(p.status) === "ready" ? <DecideButtons opportunityId={String(p.opportunity_id)} canApprove /> : null}
    </div>
  );
}

export function MinimalCaseWidget({ widget }: { widget: WidgetSpec }) {
  const id = entityId(widget, ["opportunity"]);
  const { detail, error } = useOpportunity(id);
  const content = widget.content as { code?: string; error?: string; trace?: string; language?: string };
  let mc: { code?: string; error?: string; trace?: string; language?: string } | null = content.code ? content : null;
  if (!mc && detail) mc = (((detail.opportunity.details ?? {}) as Record<string, unknown>).minimal_case as typeof mc) ?? null;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (id && !detail && !mc) return <Loading />;
  if (!mc?.code) return <Empty kind="warn" title="Sin caso mínimo" detail="Este registro no guarda un caso mínimo reproducible (lo producen las sondas de robustez)." />;
  const lines = mc.code.replace(/\n$/, "").split("\n");
  return (
    <div className="col scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", gap: 8 }}>
      <div className="tiny muted">Entrada reducida {mc.language ? `· ${mc.language}` : ""}</div>
      <pre className="code">
        {lines.map((l, i) => (
          <span key={i} style={{ display: "block" }}>
            <span className="ln">{i + 1}</span>
            {l}
          </span>
        ))}
      </pre>
      {mc.error ? (
        <div style={{ padding: "8px 10px", background: "var(--red-soft)", borderRadius: 10, border: "1px solid rgba(224,119,111,0.35)" }}>
          <div className="row" style={{ color: "var(--red)", fontWeight: 600 }}>
            <span className="dot bad" /> {mc.error.split(":")[0]}
          </div>
          <div className="small mono ink2" style={{ marginTop: 2 }}>{mc.error}</div>
        </div>
      ) : null}
      {mc.trace ? (
        <pre className="code small" style={{ borderLeft: "3px solid var(--red)" }}>
          {mc.trace}
        </pre>
      ) : null}
    </div>
  );
}

export function SqlWidget({ widget }: { widget: WidgetSpec }) {
  const id = entityId(widget, ["opportunity"]);
  const { detail, error } = useOpportunity(id);
  const content = widget.content as { query?: string; plan?: string };
  let sql: { query?: string; plan?: string } | null = content.query ? content : null;
  if (!sql && detail) sql = (((detail.opportunity.details ?? {}) as Record<string, unknown>).sql as typeof sql) ?? null;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (id && !detail && !sql) return <Loading />;
  if (!sql?.query) return <Empty kind="warn" title="Sin consulta observada" detail="Este registro no guarda la consulta ni su plan (los produce un hallazgo sobre una base de datos conectada)." />;
  return (
    <div className="col scroll nowheel" style={{ height: "100%", padding: "4px 12px 10px", gap: 8 }}>
      <div className="tiny muted">Consulta</div>
      <pre className="code">{sql.query}</pre>
      {sql.plan ? (
        <>
          <div className="tiny muted">Plan observado</div>
          <pre className="code">{sql.plan}</pre>
        </>
      ) : null}
    </div>
  );
}
