// A person's decision from a card: approve a proposal, reject an opportunity. Only on a live workspace; the server
// writes it through the same module and events the CLI uses and the agent carries it out on its next cycle.
import { useState } from "react";
import { Check, X } from "lucide-react";
import { useStore } from "@/data/store";

export function DecideButtons({ opportunityId, canApprove }: { opportunityId: string; canApprove: boolean }) {
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const summary = useStore((s) => s.summary);
  const toast = useStore((s) => s.toast);
  const refreshSummary = useStore((s) => s.refreshSummary);
  const [busy, setBusy] = useState(false);
  const live = summary?.workspace.mode === "live";
  if (!live) return <div className="tiny muted">decisiones solo sobre un workspace vivo; aquí: {summary?.workspace.mode ?? "—"}</div>;
  const decide = async (operation: "approve" | "reject") => {
    if (!api || !ws) return;
    let reason: string | null = null;
    if (operation === "reject") {
      reason = window.prompt("Motivo del rechazo (queda en la auditoría):", "");
      if (reason === null) return;
    } else if (!window.confirm("Aprobar: el agente abre el pull request en su siguiente ciclo, dentro del mandato. ¿Continuar?")) return;
    setBusy(true);
    try {
      const r = await api.action(ws, {
        operation,
        subject: opportunityId,
        reason: reason || null,
        idempotency_key: `${operation}-${opportunityId}-${Date.now()}`,
        expected_revision: summary?.workspace.head?.slice(0, 12) ?? null,
      });
      toast(r.detail, r.effect === "done" ? "ok" : r.effect === "refused" ? "bad" : "warn");
      await refreshSummary();
    } catch (e) {
      toast(String(e), "bad");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
      {canApprove ? (
        <button className="btn sm primary" disabled={busy} onClick={() => void decide("approve")} title="unbidden approve"><Check size={12} /> Aprobar PR</button>
      ) : null}
      <button className="btn sm" disabled={busy} onClick={() => void decide("reject")} title="unbidden reject"><X size={12} /> Rechazar</button>
      <span className="tiny muted">pasa por los permisos del mandato; el agente lo ejecuta en su ciclo</span>
    </div>
  );
}
