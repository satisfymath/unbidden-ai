"""What the slash commands do: the existing operations, each answered as feed entries. Nothing here runs a job or
calls a model; `start` and `stop` manage the daemon exactly as the CLI does."""

from __future__ import annotations

import getpass
from typing import Any

from unbidden.tui.feed import Entry
from unbidden.tui.text import LEVEL_NAMES, t


def _note(text: str, *, verb: str = "Noting", accent: bool = False, detail: str | None = None) -> Entry:
    return Entry(verb=verb, text=text, kind="note", accent=accent, detail=detail)  # type: ignore[arg-type]


def start(ws: Any, *, ui: bool = False, interval_s: float = 30.0) -> list[Entry]:
    from unbidden.daemon import service

    result = service.start(ws, interval_s=interval_s, extra_args=["--ui"] if ui else ())
    if result.get("started"):
        return [_note(t("cmd.start.started", pid=result["pid"], log=result["log"]))]
    if result.get("already"):
        return [_note(t("cmd.start.already", pid=result["already"].get("pid")))]
    lines = [_note(t("cmd.start.failed", exit=result.get("exit")))]
    lines.extend(_note(f"  {line}") for line in result.get("log_tail", [])[-8:])
    return lines


def stop(ws: Any, *, timeout_s: float = 60.0) -> list[Entry]:
    from unbidden.daemon import service

    result = service.stop(ws, timeout_s=timeout_s)
    if not result.get("stopped"):
        return [_note(result.get("reason") or t("cmd.stop.none"))]
    if result.get("forced"):
        return [_note(t("cmd.stop.forced", timeout=result.get("timeout_s", timeout_s),
                        jobs=result.get("jobs_left_running", 0)))]  # fmt: skip
    return [_note(t("cmd.stop.stopped", pid=result["pid"], waited=result.get("waited_s", 0.0)))]


def kill(ws: Any, reason: str) -> list[Entry]:
    switch = ws.killswitch()
    if switch.engaged:
        return [_note(t("cmd.kill.already"), accent=True)]
    switch.engage(reason or "engaged from the app")
    return [_note(t("cmd.kill.on"), verb="Deciding", accent=True)]


def resume(ws: Any) -> list[Entry]:
    switch = ws.killswitch()
    if not switch.engaged:
        return [_note(t("cmd.resume.already"))]
    switch.release()
    return [_note(t("cmd.resume.off"), verb="Deciding")]


def approve(ws: Any, opportunity_id: str, *, hours: float = 24.0, by: str | None = None) -> list[Entry]:
    from unbidden.operate.decisions import approve_by_id

    store = ws.store()
    try:
        result = approve_by_id(store, opportunity_id, by=by or getpass.getuser(), hours=hours)
    finally:
        store.close()
    if not result.get("ok", True) or result.get("error"):
        return [_note(result.get("error") or t("cmd.approve.none", id=opportunity_id))]
    return [_note(t("cmd.approve.ok", id=opportunity_id, hours=hours), verb="Asking")]


def reject(ws: Any, opportunity_id: str, reason: str, *, by: str | None = None) -> list[Entry]:
    from unbidden.operate.decisions import reject_by_id

    store = ws.store()
    try:
        result = reject_by_id(store, opportunity_id, by=by or getpass.getuser(), reason=reason)
    finally:
        store.close()
    if not result.get("ok", True) or result.get("error"):
        return [_note(result.get("error") or t("cmd.reject.none", id=opportunity_id))]
    return [_note(t("cmd.reject.ok", id=opportunity_id, reason=reason), verb="Asking")]


def why(store: Any, opportunity_id: str) -> list[Entry]:
    from unbidden.cli import why_data, why_lines
    from unbidden.contracts.opportunity import Opportunity

    opp = store.get("opportunities", opportunity_id, Opportunity)
    if opp is None:
        return [_note(t("cmd.why.none", id=opportunity_id))]
    data, attempts = why_data(store, opp)
    return [_note(line) for line in why_lines(opp, data, attempts)]


def inbox(store: Any, *, all_: bool = False) -> list[tuple[str, str, str, str]]:
    """Rows (id, evidence, status, title) sorted as `unbidden inbox` sorts them."""
    from unbidden.contracts.opportunity import Opportunity, OpportunityStatus

    statuses = [s for s in OpportunityStatus if all_ or s not in (OpportunityStatus.CLOSED,)]
    opps = [o for o in store.list("opportunities", Opportunity) if o.status in statuses]
    opps.sort(key=lambda o: (-o.evidence_level, -o.priority_score, o.created_at))
    return [
        (o.id, f"L{int(o.evidence_level)} {LEVEL_NAMES[int(o.evidence_level)]}", o.status.value, o.title) for o in opps
    ]


def spend(ledger: Any) -> list[Entry]:
    from unbidden.brain.spend import summarize

    status = ledger.status()
    cap = f"US${status.permitted_usd:.4f}" + ("" if status.verified else " (not verified)")
    out = [_note(t("cmd.spend.title")), _note(t("cmd.spend.line", spent=status.spent_usd,
                                                    available=status.available_usd, cap=cap))]  # fmt: skip
    for purpose, agg in sorted(summarize(ledger.rows(), "purpose").items(), key=lambda kv: -kv[1].get("usd", 0.0)):
        out.append(_note(t("cmd.spend.purpose", purpose=purpose, calls=int(agg.get("calls", 0)),
                           usd=agg.get("usd", 0.0))))  # fmt: skip
    return out


def doctor(ws: Any) -> list[Entry]:
    from unbidden.cli import doctor_checks

    checks, required, explained = doctor_checks(ws)
    out = [_note(t("cmd.doctor.title")), _note(explained)]
    for name, ok, detail in checks:
        mark = "ok" if ok else ("!!" if name in required else "--")
        tag = "" if ok else (" (required)" if name in required else " (optional)")
        out.append(_note(t("cmd.doctor.line", mark=mark, name=name, detail=detail, tag=tag),
                         accent=(not ok and name in required)))  # fmt: skip
    return out


def ui(ws: Any, *, open_: bool = False, planner: str = "auto") -> list[Entry]:
    from unbidden.cli import open_dashboard

    info = open_dashboard(ws, planner=planner, open_=open_)
    if not info["started"]:
        return [_note(t("cmd.ui.failed", log=info["log"]))] + [_note(f"  {line}") for line in info["log_tail"][-8:]]
    where = "served by the agent" if info.get("in_daemon") else f"pid {info.get('pid')}"
    key = "cmd.ui.reused" if info.get("reused") else "cmd.ui.open"
    return [_note(t(key, where=where, url=info["url"]))]


def activity(source: Any) -> list[Entry]:
    from unbidden.director.activity import render_text

    return [_note(t("cmd.activity.title"))] + [_note(line) for line in render_text(source.activity())]
