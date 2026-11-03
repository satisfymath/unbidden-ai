"""The feed: the engine's events narrated under the brand's verbs. Pure: an `Event` in, an `Entry` out; a
`Coalescer` folds runs of alike events into one line; `seed` builds what the feed shows on open."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.tui.text import LEVEL_NAMES, t

Verb = Literal["Discovering", "Investigating", "Experimenting", "Proving", "Deciding", "Asking", "Guarding", "Noting"]
Kind = Literal["event", "note", "person", "assistant", "stale", "heading"]
Tone = Literal["plain", "ask", "good", "warn", "bad"]

TEXT_LIMIT = 160
# Job types whose start and end the feed narrates; the routine ones (head, map, poll, sweep) show only when verbose.
TOLD_JOBS = frozenset({"lab.experiment", "research.probe", "research.investigate", "observe.checks", "observe.scan",
                       "proposal.prepare", "github.publish", "ops.deploy", "forge.build", "goal.pursue"})  # fmt: skip


@dataclass(frozen=True)
class Entry:
    verb: Verb
    text: str
    ts: datetime = field(default_factory=utc_now)
    seq: int | None = None
    ref: str | None = None  # the opportunity the line is about, for /why
    detail: str | None = None  # a second, dimmer line
    kind: Kind = "event"
    accent: bool = False  # the one colour: a question for the person, the kill switch
    tone: Tone = "plain"  # good: a pull request, a merge, a deploy; bad: blocked, refused, failed; warn: parked

    @property
    def shade(self) -> Tone:
        return self.tone if self.tone != "plain" else ("ask" if self.accent else "plain")


VERB_OF: dict[EventType, Verb] = {
    EventType.WORKSPACE_INITIALIZED: "Discovering",
    EventType.HEAD_MOVED: "Discovering",
    EventType.ANALYZER_RAN: "Discovering",
    EventType.OPPORTUNITY_OPENED: "Discovering",
    EventType.OPPORTUNITY_RESOLVED: "Discovering",
    EventType.WORLD_CHANGED: "Discovering",
    EventType.CONNECTION_CHANGED: "Discovering",
    EventType.DEPLOYMENT_OBSERVED: "Discovering",
    EventType.LOG_SIGNAL: "Discovering",
    EventType.CAPABILITY_NEEDED: "Asking",
    EventType.CAPABILITY_NEED_CHANGED: "Discovering",
    EventType.CAPABILITY_BUILT: "Discovering",
    EventType.CAPABILITY_APPROVED: "Asking",
    EventType.HYPOTHESIS_RECORDED: "Investigating",
    EventType.ANOMALY_DETECTED: "Investigating",
    EventType.ANOMALY_RESOLVED: "Investigating",
    EventType.MODEL_CALLED: "Investigating",
    EventType.MODEL_FALLBACK: "Investigating",
    EventType.EXPERIMENT_STARTED: "Experimenting",
    EventType.ACTION_EXECUTED: "Experimenting",
    EventType.VERDICT_RECORDED: "Proving",
    EventType.VERDICT_REVOKED: "Proving",
    EventType.PROPOSAL_READY: "Proving",
    EventType.PROPOSAL_PUBLISHED: "Proving",
    EventType.PROPOSAL_STALE: "Proving",
    EventType.OUTCOME_RECORDED: "Proving",
    EventType.OUTCOME_HELD: "Proving",
    EventType.OUTCOME_INVALIDATED: "Proving",
    EventType.IMPACT_JUDGED: "Proving",
    EventType.DEPLOYED: "Proving",
    EventType.MERGED: "Proving",
    EventType.DECISION_MADE: "Deciding",
    EventType.MANDATE_CHANGED: "Deciding",
    EventType.KILL_SWITCH: "Deciding",
    EventType.APPROVAL_GRANTED: "Asking",
    EventType.APPROVAL_REJECTED: "Asking",
    EventType.EGRESS_ALLOWED: "Guarding",
    EventType.EGRESS_BLOCKED: "Guarding",
    EventType.POLICY_DENIED: "Guarding",
    EventType.VALUES_MASKED: "Guarding",
    EventType.ASK_OPENED: "Asking",
    EventType.ASK_ANSWERED: "Asking",
    EventType.JOB_STARTED: "Noting",
    EventType.JOB_FINISHED: "Noting",
    EventType.NOTE: "Noting",
    EventType.BRANCH_PUSHED: "Proving",
}

QUIET: frozenset[EventType] = frozenset({EventType.EGRESS_ALLOWED})  # shown only when verbose


def _clip(text: str, limit: int = TEXT_LIMIT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _s(p: dict[str, Any], key: str, default: str = "?") -> str:
    value = p.get(key)
    return default if value in (None, "") else str(value)


def _short(rev: Any) -> str:
    return str(rev)[:12] if rev else "?"


def _measure(p: dict[str, Any]) -> str:
    before, after, pv = p.get("median_before_ms"), p.get("median_after_ms"), p.get("p_value")
    if before is None or after is None:
        return ""
    out = f": {float(before):.1f} → {float(after):.1f} ms"
    if pv is not None:
        out += f", p = {float(pv):.2g}"
    return out


def narrate(event: Event, *, asks_for_proposals: bool = False, verbose: bool = False) -> Entry | None:
    """One line for one event, or None for the ones the feed keeps quiet. Payloads are read defensively: the
    engine's own keys when present, the event's type when not."""
    et = event.type
    if et in QUIET and not verbose:
        return None
    p = event.payload or {}
    verb = VERB_OF.get(et, "Noting")
    ref = event.correlation_id or (event.entity_id if event.entity_id and event.entity_id.startswith("opp_") else None)
    accent = False
    tone: Tone = "plain"
    detail: str | None = None
    text: str
    match et:
        case EventType.ASK_OPENED:
            accent, tone = True, "ask"
            text = t("ev.ask.opened", title=_s(p, "title"), id=event.entity_id or "?")
            if p.get("cli"):
                detail = t("ev.ask.cli", cli=_s(p, "cli"))
        case EventType.ASK_ANSWERED:
            text = t("ev.ask.answered", answer=_s(p, "answer"), outcome=_s(p, "outcome", ""))
        case EventType.JOB_STARTED:
            kind = _s(p, "type")
            if kind not in TOLD_JOBS and not verbose:
                return None
            usual = p.get("usual_s")
            text = t("ev.job.started", doing=_s(p, "doing", kind), stage=_s(p, "stage"))
            text += " " + (t("ev.job.usual", seconds=int(float(usual))) if usual else t("ev.job.first"))
        case EventType.JOB_FINISHED:
            kind, outcome = _s(p, "type"), _s(p, "outcome", "ok")
            if outcome == "ok" and kind not in TOLD_JOBS and not verbose:
                return None
            nexts = ", ".join(str(x) for x in (p.get("next") or []))
            if outcome == "ok":
                text = t("ev.job.done", doing=_s(p, "doing", kind), seconds=int(float(p.get("seconds") or 0)))
                tone = "good" if kind in ("github.publish", "ops.deploy") else "plain"
            elif outcome == "parked":
                tone = "warn"
                text = t("ev.job.parked", doing=_s(p, "doing", kind))
            elif outcome == "stopped":
                text = t("ev.job.stopped", doing=_s(p, "doing", kind))
            else:
                tone = "bad"
                text = t("ev.job.failed", doing=_s(p, "doing", kind))
            if nexts:
                detail = t("ev.job.next", next=nexts)
        case EventType.NOTE:
            text = _s(p, "text")
            lowered = text.lower()
            if "ci green" in lowered or "improved" in lowered or lowered.startswith("merged"):
                tone = "good"
            elif "ci red" in lowered or "not merged" in lowered or "not published" in lowered:
                tone = "bad"
            elif "wait" in lowered or "no proven fix" in lowered or "not measured" in lowered:
                tone = "warn"
        case EventType.BRANCH_PUSHED:
            tone = "good"
            text = t("ev.pushed", branch=_s(p, "branch"), commit=_short(p.get("commit")))
        case EventType.WORKSPACE_INITIALIZED:
            text = t("ev.workspace", rev=_short(p.get("rev")), resources=_s(p, "resources", "0"),
                     relations=_s(p, "relations", "0"), blind=_s(p, "blind_spots", "0"))  # fmt: skip
        case EventType.WORLD_CHANGED:
            text = t("ev.world", rev=_short(p.get("rev")), diff=_s(p, "diff", "no summary"))
        case EventType.HEAD_MOVED:
            text = t("ev.head", frm=_short(p.get("from")), to=_short(p.get("to")))
        case EventType.ANALYZER_RAN:
            if p.get("error"):
                text = t("ev.analyzer.error", tool=_s(p, "tool", "an analyzer"), rev=_short(p.get("rev")),
                         error=_s(p, "error"))  # fmt: skip
            else:
                text = t("ev.analyzer", tool=_s(p, "tool", "an analyzer"), rev=_short(p.get("rev")),
                         findings=_s(p, "findings", _s(p, "problems", "0")),
                         completeness=_s(p, "completeness", "run"))  # fmt: skip
        case EventType.OPPORTUNITY_OPENED:
            if p.get("reopened"):
                text = t("ev.opp.reopened", reason=_s(p, "reason"))
            else:
                text = t("ev.opp.opened", title=_s(p, "title", event.entity_id or "an opportunity"))
        case EventType.OPPORTUNITY_RESOLVED:
            text = t("ev.opp.resolved", reason=_s(p, "reason"))
        case EventType.DECISION_MADE:
            text = t("ev.decision", chosen=_s(p, "chosen"), reason=_s(p, "reason"))
            candidates = p.get("candidates")
            if isinstance(candidates, list) and candidates:
                detail = "candidates: " + ", ".join(
                    f"{c.get('kind')} {c.get('utility')}" for c in candidates if isinstance(c, dict)
                )
        case EventType.EXPERIMENT_STARTED:
            files = p.get("files")
            text = t("ev.experiment", origin=_s(p, "origin", "next"),
                     files=len(files) if isinstance(files, list) else "?")  # fmt: skip
        case EventType.VERDICT_RECORDED:
            reval = p.get("revalidation")
            if isinstance(reval, dict):
                text = t("ev.verdict.revalidated", criteria=_s(reval, "criteria"), outcome=_s(reval, "outcome"))
            else:
                key = "ev.verdict.improved" if p.get("improved") else "ev.verdict.not"
                text = t(key, level=_s(p, "level"), measure=_measure(p))
                reasons = p.get("reasons")
                if isinstance(reasons, list) and reasons:
                    detail = "; ".join(str(r) for r in reasons[:3])
        case EventType.VERDICT_REVOKED:
            text = t("ev.verdict.revoked", reason=_s(p, "reason", _s(p, "why")))
        case EventType.PROPOSAL_READY:
            if asks_for_proposals and ref:
                verb, accent = "Asking", True
                text = t("ev.proposal.ask", id=ref)
            elif p.get("reconciled"):
                text = t("ev.proposal.ready", branch=_s(p, "reconciled"), commit=_s(p, "why"),
                         level=_s(p, "level", "?"))  # fmt: skip
            else:
                text = t("ev.proposal.ready", branch=_s(p, "branch"), commit=_short(p.get("commit")),
                         level=_s(p, "level"))  # fmt: skip
        case EventType.PROPOSAL_PUBLISHED:
            tone = "good"
            text = t("ev.proposal.published", url=_s(p, "url"))
            if p.get("number"):
                text = t("ev.proposal.published.n", number=_s(p, "number"), url=_s(p, "url"))
        case EventType.PROPOSAL_STALE:
            text = t("ev.proposal.stale", reason=_s(p, "reason"))
        case EventType.APPROVAL_GRANTED:
            text = t("ev.approval.granted", what=_s(p, "proposal", _s(p, "capability", "it")))
        case EventType.APPROVAL_REJECTED:
            text = t("ev.approval.rejected", reason=_s(p, "reason"))
        case EventType.EGRESS_ALLOWED:
            text = t("ev.egress.allowed", bytes=_s(p, "bytes", "?"), destination=_s(p, "destination"),
                     purpose=_s(p, "purpose"))  # fmt: skip
        case EventType.EGRESS_BLOCKED:
            reasons = p.get("reasons")
            why = "; ".join(map(str, reasons)) if isinstance(reasons, list) else _s(p, "reasons")
            text = t("ev.egress.blocked", bytes=_s(p, "bytes", "?"), destination=_s(p, "destination"),
                     purpose=_s(p, "purpose"), reasons=why)  # fmt: skip
        case EventType.POLICY_DENIED:
            reasons = p.get("reasons")
            fallback = _s(p, "why", _s(p, "reason", _s(p, "control")))
            why = "; ".join(map(str, reasons)) if isinstance(reasons, list) else fallback
            text = t("ev.policy", rule=_s(p, "rule"), why=why)
        case EventType.VALUES_MASKED:
            text = t("ev.masked", purpose=_s(p, "purpose"))
        case EventType.MODEL_CALLED:
            tokens = int(p.get("tokens_in") or 0) + int(p.get("tokens_out") or 0)
            if p.get("ok") is False:
                tone = "bad"
                text = t("ev.model.failed", purpose=_s(p, "purpose"), tier=_s(p, "tier"), model=_s(p, "model"),
                         problem=_s(p, "problem"))  # fmt: skip
            else:
                text = t("ev.model", purpose=_s(p, "purpose"), tier=_s(p, "tier"), model=_s(p, "model"),
                         tokens=tokens, usd=float(p.get("usd") or 0.0))  # fmt: skip
        case EventType.MODEL_FALLBACK:
            text = t("ev.model.fallback", purpose=_s(p, "purpose"), frm=_s(p, "from"), to=_s(p, "to"),
                     cause=_s(p, "cause", _s(p, "reason")))  # fmt: skip
        case EventType.KILL_SWITCH:
            engaged = bool(p.get("engaged", True))
            accent = engaged
            text = t("ev.kill", state="engaged" if engaged else "released")
        case EventType.MANDATE_CHANGED:
            what = ", ".join(f"{k}={v}" for k, v in p.items() if k not in ("by", "actor")) or "see the mandate"
            text = t("ev.mandate", what=what)
        case EventType.DEPLOYED:
            if "drill" in p:
                drill = p.get("drill")
                result = _s(drill, "result", _s(drill, "status", "recorded")) if isinstance(drill, dict) else "recorded"
                text = t("ev.deployed.drill", result=result)
            else:
                result = ("ok" if p.get("ok") else "failed") + (f": {p['reason']}" if p.get("reason") else "")
                key = "ev.deployed.rollback" if p.get("rollback") else "ev.deployed"
                tone = "good" if p.get("ok") and not p.get("rollback") else "bad"
                text = t(key, commit=_short(p.get("commit")), result=result)
        case EventType.MERGED:
            tone = "good"
            text = t("ev.merged", number=_s(p, "number"), sha=_short(p.get("sha")))
        case EventType.IMPACT_JUDGED:
            text = t("ev.impact", impact=_s(p, "impact"), baseline=_s(p, "baseline"))
        case EventType.OUTCOME_RECORDED:
            text = t("ev.outcome", deploy=_s(p, "deploy"), result=_s(p, "result", "recorded"))
        case EventType.OUTCOME_HELD:
            text = t("ev.outcome.held", checks=_s(p, "checks", "?"))
        case EventType.OUTCOME_INVALIDATED:
            text = t("ev.outcome.invalidated", why=_s(p, "why"))
        case EventType.CAPABILITY_BUILT:
            text = t("ev.capability.built", source=_s(p, "source", event.entity_id or "?"),
                     status=_s(p, "status", _s(p, "decision", "built")))  # fmt: skip
        case EventType.CAPABILITY_APPROVED:
            text = t("ev.capability.approved", source=_s(p, "source", event.entity_id or "?"))
        case EventType.CAPABILITY_NEEDED:
            accent = True
            text = t("ev.capability.needed", what=_s(p, "title", _s(p, "source", event.entity_id or "?")))
        case EventType.CAPABILITY_NEED_CHANGED:
            text = t("ev.capability.need", status=_s(p, "status"), note=_s(p, "note", _s(p, "source")))
        case EventType.CONNECTION_CHANGED:
            text = t("ev.connection", frm=_s(p, "from", "new"), to=_s(p, "to"), why=_s(p, "why"))
        case EventType.ACTION_EXECUTED:
            text = t("ev.action", operation=_s(p, "operation"), connection=_s(p, "connection"), status=_s(p, "status"))
        case EventType.HYPOTHESIS_RECORDED:
            text = t("ev.hypothesis", subject=_s(p, "subject"), statement=_s(p, "statement"))
        case EventType.DEPLOYMENT_OBSERVED:
            text = t("ev.deployment", commit=_short(p.get("commit")), status=_s(p, "commit_status", _s(p, "reason")))
        case EventType.ANOMALY_DETECTED:
            text = t("ev.anomaly", where=_s(p, "suspect", event.entity_id or "a service"),
                     statement=_s(p, "statement", _s(p, "summary", "see the record")))  # fmt: skip
        case EventType.ANOMALY_RESOLVED:
            text = t("ev.anomaly.resolved", where=_s(p, "suspect", event.entity_id or "a service"))
        case EventType.LOG_SIGNAL:
            text = t("ev.signal", title=_s(p, "title", _s(p, "kind")), summary=_s(p, "summary", ""))
        case _:
            text = t("ev.plain", type=str(et))
    if et in (EventType.EGRESS_BLOCKED, EventType.POLICY_DENIED) or (et is EventType.ANALYZER_RAN and p.get("error")):
        tone = "bad"
    return Entry(verb=verb, text=_clip(text), ts=event.ts, seq=event.seq, ref=ref,
                 detail=_clip(detail) if detail else None, accent=accent, tone=tone)  # fmt: skip


# --- folding runs of alike events -----------------------------------------------------------------------------------

_FOLDS: dict[EventType, str] = {
    EventType.MODEL_CALLED: "correlation_id",
    EventType.ANALYZER_RAN: "rev",
    EventType.LOG_SIGNAL: "entity_id",
    EventType.EGRESS_ALLOWED: "correlation_id",
    EventType.EGRESS_BLOCKED: "correlation_id",
    EventType.HEAD_MOVED: "",
}


def _fold_key(event: Event) -> tuple[str, str] | None:
    by = _FOLDS.get(event.type)
    if by is None:
        return None
    group = "egress" if event.type in (EventType.EGRESS_ALLOWED, EventType.EGRESS_BLOCKED) else str(event.type)
    if by == "":
        return (group, "")
    if by == "rev":
        return (group, str((event.payload or {}).get("rev")))
    return (group, str(getattr(event, by) or ""))


class Coalescer:
    """Consecutive events of one kind about one thing become one line: n model calls, k analyzers at a rev, n
    signals from a service, n payloads to a destination; of a run of head moves only the last is kept. Push
    events in order; take what `push` returns and `flush` at the end of a batch."""

    def __init__(self, *, asks_for_proposals: bool = False, verbose: bool = False) -> None:
        self.asks = asks_for_proposals
        self.verbose = verbose
        self._key: tuple[str, str] | None = None
        self._run: list[Event] = []

    def push(self, event: Event) -> list[Entry]:
        key = _fold_key(event)
        out: list[Entry] = []
        if key is None:
            out.extend(self.flush())
            entry = narrate(event, asks_for_proposals=self.asks, verbose=self.verbose)
            return out + ([entry] if entry else [])
        if key != self._key:
            out.extend(self.flush())
            self._key = key
        self._run.append(event)
        return out

    def flush(self) -> list[Entry]:
        run, self._run, self._key = self._run, [], None
        if not run:
            return []
        if len(run) == 1:
            entry = narrate(run[0], asks_for_proposals=self.asks, verbose=self.verbose)
            return [entry] if entry else []
        last = run[-1]
        p = last.payload or {}
        kind = last.type
        tone: Tone = "plain"
        if kind == EventType.MODEL_CALLED:
            rejected = [e for e in run if (e.payload or {}).get("problem") == "key rejected"]
            if len(rejected) == len(run):
                tone = "bad"
                text = t("ev.models.rejected", n=len(run))
            else:
                tokens = sum(
                    int((e.payload or {}).get("tokens_in") or 0) + int((e.payload or {}).get("tokens_out") or 0)
                    for e in run
                )
                usd = sum(float((e.payload or {}).get("usd") or 0.0) for e in run)
                text = t("ev.models.many", n=len(run), tokens=tokens, usd=usd)
        elif kind == EventType.ANALYZER_RAN:
            findings = sum(int((e.payload or {}).get("findings") or 0) for e in run)
            text = t("ev.analyzers.many", n=len(run), rev=_short(p.get("rev")), findings=findings)
        elif kind == EventType.LOG_SIGNAL:
            text = t("ev.signals.many", n=len(run), source=last.entity_id or "logs")
        elif kind in (EventType.EGRESS_ALLOWED, EventType.EGRESS_BLOCKED):
            if not self.verbose and all(e.type == EventType.EGRESS_ALLOWED for e in run):
                return []
            allowed = sum(1 for e in run if e.type == EventType.EGRESS_ALLOWED)
            text = t("ev.egress.many", n=len(run), destination=_s(p, "destination"), allowed=allowed,
                     blocked=len(run) - allowed)  # fmt: skip
        else:  # head moves: the last one
            entry = narrate(last, asks_for_proposals=self.asks, verbose=self.verbose)
            return [entry] if entry else []
        ref = last.correlation_id
        return [Entry(verb=VERB_OF[kind], text=_clip(text), ts=last.ts, seq=last.seq, ref=ref, tone=tone)]


# --- what the feed shows on open -------------------------------------------------------------------------------------


def _last_seq(store: Any) -> int:
    """The read-only store knows its last seq; an in-memory store (tests, the demo) is asked for its events."""
    if hasattr(store, "last_seq"):
        return int(store.last_seq() or 0)
    seqs = [e.seq or 0 for e in store.events(after=0, limit=100_000)]
    return max(seqs) if seqs else 0


def seed(
    store: Any, highlights: list[dict[str, Any]], *, last: int = 60, asks_for_proposals: bool = False
) -> list[Entry]:
    """A "where things stand" block from the highlights, then the last `last` events narrated. `store` is any
    object with `last_seq()` and `events(after=, limit=)` (the read-only store of a live source)."""
    now = utc_now()
    out: list[Entry] = [Entry(verb="Noting", text=t("open.stand"), ts=now, kind="heading")]
    if not highlights:
        out.append(Entry(verb="Noting", text=t("open.empty"), ts=now, kind="note"))
    for h in highlights:
        level = int(h.get("level") or 1)
        asks = asks_for_proposals and h.get("status") == "proposed"
        key = "open.highlight.ask" if asks else "open.highlight"
        text = t(key, id=h.get("id"), level=level, name=LEVEL_NAMES.get(level, ""), status=h.get("status"),
                 title=h.get("title"))  # fmt: skip
        out.append(Entry(verb="Asking" if asks else "Noting", text=_clip(text), ts=now, ref=str(h.get("id")),
                         kind="note", accent=asks))  # fmt: skip
    tail = _last_seq(store)
    events = list(store.events(after=max(0, tail - 4 * last), limit=4 * last)) if tail else []
    folder = Coalescer(asks_for_proposals=asks_for_proposals)
    entries: list[Entry] = []
    for e in events:
        entries.extend(folder.push(e))
    entries.extend(folder.flush())
    entries = entries[-last:]
    if entries:
        out.append(Entry(verb="Noting", text=t("open.events", n=len(entries)), ts=now, kind="heading"))
        out.extend(entries)
    return out
