"""What the status bar shows, read in pieces at their own cadence. Pure reads over existing code; nothing here
imports Textual, and nothing here runs on the UI thread by necessity except `format_bar`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from unbidden.contracts.common import utc_now
from unbidden.tui.brand import MARK
from unbidden.tui.text import t


@dataclass
class Bar:
    workspace: str = ""
    agent_running: bool = False
    agent_pid: int | None = None
    agent_stale: bool = False
    jobs_running: int = 0
    jobs_queued: int = 0
    kill: bool = False
    mode: str = ""
    profile: str = ""
    local_reachable: bool | None = None  # None: not probed yet
    spend_available: float | None = None
    spend_verified: bool = False
    key_rejected: bool = False  # the last remote model call was refused for its key (MODEL_CALLED, "key rejected")
    dashboard_url: str | None = None
    last_seq: int = 0
    last_event_at: datetime | None = None
    stale: bool = False  # the record could not be read on the last tick
    transient: str = ""  # "thinking…", "press Ctrl+C again to quit"
    read_at: datetime = field(default_factory=utc_now)


def read_cheap(ws: Any, store: Any, bar: Bar) -> Bar:
    """Every second: the lock file, the kill switch file, two small counts and the last event's seq."""
    from unbidden.daemon import service

    status = service.status(ws)
    bar.agent_running = bool(status["running"])
    bar.agent_pid = status.get("pid")
    bar.agent_stale = bool(status.get("stale"))
    bar.jobs_running = int(status.get("jobs_running") or 0)
    bar.jobs_queued = int(status.get("jobs_queued") or 0)
    bar.kill = ws.killswitch().engaged
    try:
        seq = int(store.last_seq() or 0)
        if seq != bar.last_seq:
            bar.last_seq = seq
            events = store.events(after=max(0, seq - 1), limit=1)
            bar.last_event_at = events[-1].ts if events else bar.last_event_at
        bar.stale = False
    except Exception:
        bar.stale = True
    bar.read_at = utc_now()
    return bar


def read_mandate(ws: Any, bar: Bar) -> Bar:
    """On a mandate change and every 30 s: the mode and the model option."""
    from unbidden.guardian.mandate_edit import current_mode

    try:
        mandate = ws.mandate()
    except Exception:
        return bar
    bar.workspace = mandate.workspace
    bar.mode = current_mode(mandate.autonomy.model_dump(mode="json"))
    bar.profile = mandate.models.profile
    return bar


def read_spend(ledger: Any, bar: Bar) -> Bar:
    """Every 10 s and after a chat turn: the ledger's status (budget file plus one sum)."""
    status = ledger.status()
    bar.spend_available = float(status.available_usd)
    bar.spend_verified = bool(status.verified)
    return bar


def read_route(source: Any, bar: Bar) -> Bar:
    """Every 30 s, in a worker: whether the local model server answers (an HTTP probe with a 2 s timeout)."""
    try:
        bar.local_reachable = bool(source.route_info()["local"]["reachable"])
    except Exception:
        bar.local_reachable = False
    return bar


def read_dashboard(ws: Any, bar: Bar) -> Bar:
    """Every 15 s, in a worker: the dashboard's announcement, if its process answers."""
    from unbidden.web import announce

    info = announce.alive(announce.ui_path(ws.dir))
    bar.dashboard_url = info["url"] if info else None
    return bar


def key_rejected(events: Any) -> bool | None:
    """What the last remote model call in `events` says about the key: True when it was refused for the key, False
    when a remote call answered, None when none of these events is a remote model call."""
    from unbidden.contracts.events import EventType

    verdict: bool | None = None
    for event in events:
        if event.type is not EventType.MODEL_CALLED or event.payload.get("tier") == "local":
            continue
        verdict = event.payload.get("problem") == "key rejected"
    return verdict


def format_bar(bar: Bar, width: int, *, accent: str | None = None) -> str:
    """One line of rich markup; fields drop from the right when the width is short."""
    parts: list[str] = [f"[bold]{MARK} {bar.workspace or 'unbidden'}[/]"]
    if bar.kill:
        style = f"bold {accent}" if accent else "bold reverse"
        parts.append(f"[{style}]{t('bar.kill')}[/]")
    if bar.key_rejected:
        style = f"bold {accent}" if accent else "bold reverse"
        parts.append(f"[{style}]{t('bar.key.rejected')}[/]")
    if bar.agent_running:
        parts.append(t("bar.agent.running", pid=bar.agent_pid))
    elif bar.agent_stale:
        parts.append(t("bar.agent.stale"))
    else:
        parts.append(f"[dim]{t('bar.agent.stopped')}[/]")
    if bar.jobs_running or bar.jobs_queued:
        parts.append(t("bar.jobs", running=bar.jobs_running, queued=bar.jobs_queued))
    if bar.mode:
        parts.append(f"{bar.mode} · {bar.profile}")
    if bar.local_reachable is not None:
        parts.append(t("bar.local.ok") if bar.local_reachable else f"[dim]{t('bar.local.down')}[/]")
    if bar.spend_available is not None:
        parts.append(t("bar.spend", available=bar.spend_available) if bar.spend_verified
                     else f"[dim]{t('bar.spend.unverified')}[/]")  # fmt: skip
    if bar.dashboard_url:
        parts.append(f"[dim]{bar.dashboard_url}[/]")
    if bar.stale:
        parts.append("[dim]record unreadable[/]")
    elif bar.last_event_at is not None:
        seconds = max(0, int((bar.read_at - bar.last_event_at).total_seconds()))
        parts.append(f"[dim]{t('bar.age', seconds=seconds)}[/]")
    else:
        parts.append(f"[dim]{t('bar.age.none')}[/]")
    if bar.transient:
        parts.append(f"[bold]{bar.transient}[/]")
    out = " · ".join(parts)
    while _plain_len(out) > width and len(parts) > 2:
        parts.pop(-2 if bar.transient else -1)
        out = " · ".join(parts)
    return out


def _plain_len(markup: str) -> int:
    from rich.text import Text

    return Text.from_markup(markup).cell_len
