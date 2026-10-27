"""Logs as evidence (ported from the prototype's observer): a service's recent lines, read without writing, become
grouped, redacted, time-normalised windows, and a few explicit patterns over successive windows become signals.

Logs are data, never instructions: nothing in a line is executed or handed to a model as a command, and every stored
text is redacted first. A signal says what was measured (counts, windows, a deploy marker before the first
occurrence), never a cause: an error that appears after a deploy is a correlation until something reproduces it.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from unbidden.guardian.scanner import redact_text

MAX_LINE = 2000
MAX_LINES = 5000  # per window: what is beyond is counted as dropped, never silent
HISTORY_WINDOWS = 48
MIN_COUNT = 3  # errors in a window to be recurring
RECURRING_WINDOWS = 2
NOISE_WINDOWS, NOISE_SHARE = 12, 0.9  # an error in nearly every window for long is steady noise
MIN_REQUESTS, RATE_WINDOWS, RATE_FACTOR, RATE_FLOOR = 50, 6, 2.0, 0.02

ISO = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)(Z|[+-]\d{2}:?\d{2})?")
LEVELS = {
    "fatal": "critical", "critical": "critical", "error": "error", "err": "error", "warn": "warning",
    "warning": "warning", "info": "info", "debug": "debug", "trace": "debug",
}  # fmt: skip
LEVEL_WORD = re.compile(
    r"(?:^|[\s\[|:=\"'])(?P<level>FATAL|CRITICAL|ERROR|ERR|WARN(?:ING)?|INFO|DEBUG|TRACE)(?:[\s\]|:=\"'$]|$)", re.I
)
STATUS_HINT = re.compile(r"(?:status(?:_?code)?|HTTP/\d(?:\.\d)?\"?)\s*[:=]?\s*\"?(?P<status>[1-5]\d\d)", re.I)
EXCEPTION = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception|Fault|Panic))\b")
VARIABLE = [
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{12,64}\b", re.I), "<hex>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    (re.compile(r"\b\d+\.\d+\.\d+\.\d+\b"), "<ip>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|MB|KB|B)\b"), "<n>"),
    (re.compile(r"\b\d+\b"), "<n>"),
    (re.compile(r"/[\w./-]*\d[\w./-]*"), "<path>"),
]


@dataclass(frozen=True)
class Parsed:
    ts: datetime | None
    level: str  # critical | error | warning | info | debug | unknown
    status: int | None
    exception: str | None
    message: str  # redacted, bounded
    fingerprint: str  # of the normalised message
    normalized: str


def normalize(text: str) -> str:
    """The shape of a message: ids, timestamps, numbers, hashes and paths collapsed."""
    out = text
    for pattern, token in VARIABLE:
        out = pattern.sub(token, out)
    return " ".join(out.split())[:300]


def parse_timestamp(text: str) -> datetime | None:
    found = ISO.search(text)
    if not found:
        return None
    raw = found.group(1).replace(" ", "T").replace(",", ".")
    zone = (found.group(2) or "").replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(raw[:26] + zone)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def parse_line(text: str) -> Parsed:
    """One raw line, redacted before anything else and bounded; a JSON line gives its level, status and message."""
    text = redact_text(text)[:MAX_LINE]
    level, status, message = "unknown", None, text
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            doc = json.loads(stripped)
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            for key in ("level", "severity", "lvl", "loglevel"):
                if key in doc:
                    value = doc[key]
                    level = (
                        {60: "critical", 50: "error", 40: "warning", 30: "info"}.get(value, "debug")
                        if isinstance(value, int)
                        else LEVELS.get(str(value).lower(), "unknown")
                    )
                    break
            for key in ("status", "statusCode", "status_code"):
                value = doc.get(key)
                if isinstance(value, int) and 100 <= value <= 599:
                    status = value
                    break
            message = str(doc.get("msg") or doc.get("message") or doc.get("err") or stripped)
    if level == "unknown":
        found = LEVEL_WORD.search(text)
        if found:
            level = LEVELS.get(found.group("level").lower(), "unknown")
    if status is None:
        hinted = STATUS_HINT.search(text)
        if hinted:
            status = int(hinted.group("status"))
    exception = None
    found_exc = EXCEPTION.search(text)
    if found_exc:
        exception = found_exc.group(1)
        if level == "unknown":
            level = "error"
    if status is not None and status >= 500 and level in ("unknown", "info"):
        level = "error"
    normalized = normalize(message)
    return Parsed(
        ts=parse_timestamp(text),
        level=level,
        status=status,
        exception=exception,
        message=message[:500],
        fingerprint=hashlib.sha256(normalized.encode()).hexdigest()[:16],
        normalized=normalized,
    )


@dataclass
class Group:
    fingerprint: str
    level: str
    normalized: str
    count: int = 0
    first: str | None = None
    last: str | None = None
    sample: str = ""
    exception: str | None = None
    statuses: dict[str, int] = field(default_factory=dict[str, int])


def summarize_window(source: str, lines: Sequence[str], *, received: datetime) -> dict[str, Any]:
    """One group per message shape, counts per status class, the volume beyond the budget counted as dropped."""
    kept = list(lines)[:MAX_LINES]
    groups: dict[str, Group] = {}
    status_counts: dict[str, int] = {}
    stamps: list[datetime] = []
    for line in kept:
        parsed = parse_line(line)
        group = groups.setdefault(
            parsed.fingerprint,
            Group(parsed.fingerprint, parsed.level, parsed.normalized, sample=parsed.message[:200],
                  exception=parsed.exception),
        )  # fmt: skip
        group.count += 1
        if parsed.ts is not None:
            stamps.append(parsed.ts)
            iso = parsed.ts.isoformat()
            group.first = min(group.first or iso, iso)
            group.last = max(group.last or iso, iso)
        if parsed.status is not None:
            klass = f"{parsed.status // 100}xx"
            status_counts[klass] = status_counts.get(klass, 0) + 1
            group.statuses[klass] = group.statuses.get(klass, 0) + 1
    return {
        "source": source,
        "start": (min(stamps) if stamps else received).isoformat(),
        "end": (max(stamps) if stamps else received).isoformat(),
        "lines": len(kept),
        "dropped": max(0, len(lines) - len(kept)),
        "groups": {fp: g.__dict__ for fp, g in groups.items()},
        "status_counts": status_counts,
    }


@dataclass(frozen=True)
class Signal:
    kind: str  # recurring_error | error_after_deploy | error_rate_increase | noise
    fingerprint: str | None
    title: str
    summary: str
    details: dict[str, Any]


def _share_5xx(window: dict[str, Any]) -> tuple[int, int]:
    counts: dict[str, int] = window.get("status_counts") or {}
    return int(counts.get("5xx", 0)), sum(int(v) for v in counts.values())


def detect(
    windows: Sequence[dict[str, Any]], *, deploy_at: datetime | None = None, deploy: str | None = None
) -> list[Signal]:
    """The explicit patterns over one source's stored windows (newest last). Each says what it measured."""
    if not windows:
        return []
    current, history = windows[-1], list(windows[:-1])
    seen_in: dict[str, int] = {}
    for window in history:
        for fp in window.get("groups") or {}:
            seen_in[fp] = seen_in.get(fp, 0) + 1
    signals: list[Signal] = []
    for fp, group in (current.get("groups") or {}).items():
        level, count = str(group.get("level")), int(group.get("count") or 0)
        if level not in ("error", "critical"):
            continue
        seen, total = seen_in.get(fp, 0) + 1, len(history) + 1
        base = {
            "fingerprint": fp,
            "level": level,
            "count_in_window": count,
            "windows_seen": seen,
            "windows_total": total,
            "sample": group.get("sample"),
            "exception": group.get("exception"),
            "first": group.get("first"),
            "window": {"start": current.get("start"), "end": current.get("end")},
        }
        shape = str(group.get("normalized"))[:70]
        if total >= NOISE_WINDOWS and seen >= NOISE_WINDOWS and seen / total >= NOISE_SHARE:
            signals.append(
                Signal(
                    "noise",
                    fp,
                    f"steady noise: {shape}",
                    f"{level} in {seen} of {total} windows, unchanged; no intervention justified by this alone",
                    base,
                )
            )
            continue
        first = parse_timestamp(str(group.get("first") or ""))
        if deploy_at is not None and first is not None and first >= deploy_at:
            before = any(
                fp in (w.get("groups") or {}) and (parse_timestamp(str(w.get("end"))) or deploy_at) < deploy_at
                for w in history
            )
            if not before:
                signals.append(
                    Signal(
                        "error_after_deploy",
                        fp,
                        f"{group.get('exception') or level} appeared after deploy {deploy or ''}: {shape}",
                        f"first seen {first.isoformat()}, after the deploy at {deploy_at.isoformat()}; not in "
                        f"{len(history)} earlier window(s). A correlation with the deploy, not a cause.",
                        {**base, "deploy_at": deploy_at.isoformat(), "deploy": deploy},
                    )
                )
                continue
        if count >= MIN_COUNT or seen >= RECURRING_WINDOWS:
            intermittent = seen < total and seen >= 2 and total >= 3
            signals.append(
                Signal(
                    "recurring_error",
                    fp,
                    f"{group.get('exception') or level} recurs: {shape}",
                    f"{count} time(s) in the last window, seen in {seen} of {total} window(s)"
                    + ("; intermittent" if intermittent else ""),
                    {**base, "intermittent": intermittent},
                )
            )
    now_5xx, now_total = _share_5xx(current)
    if now_total >= MIN_REQUESTS and history:
        prev = [_share_5xx(w) for w in history[-RATE_WINDOWS:]]
        prev_5xx, prev_total = sum(p for p, _ in prev), sum(t for _, t in prev)
        prev_rate = prev_5xx / prev_total if prev_total else 0.0
        now_rate = now_5xx / now_total
        if now_5xx >= MIN_COUNT and now_rate >= max(RATE_FLOOR, prev_rate * RATE_FACTOR):
            signals.append(
                Signal(
                    "error_rate_increase",
                    None,
                    f"5xx share rose to {now_rate:.1%} ({now_5xx} of {now_total})",
                    f"previous {len(prev)} window(s): {prev_rate:.1%} ({prev_5xx} of {prev_total})",
                    {
                        "now": now_rate,
                        "before": prev_rate,
                        "window": {"start": current.get("start"), "end": current.get("end")},
                    },
                )
            )
    return signals


def read_container(name: str, since_s: int) -> list[str]:
    """The container's lines of the last `since_s` seconds, with docker's own timestamps; read-only."""
    out = subprocess.run(
        ["docker", "logs", "--timestamps", "--since", f"{since_s}s", name], capture_output=True, text=True, check=False
    )
    return (out.stdout + out.stderr).splitlines()


LOG_EVERY_S = 300
MAX_GROUPS = 60  # per stored window, the largest; the rest are counted in `lines`


class LogWatcher:
    """Every few minutes, each container of the project: its recent lines as a window, and the signals over its
    stored windows, recorded once each. Read-only; nothing here acts on what it finds."""

    def __init__(self, store: Any, world: Any, log: Any = print) -> None:
        self.store, self.world, self.log = store, world, log

    def _deploy(self) -> tuple[datetime | None, str | None]:
        from unbidden.contracts.world import Deployment
        from unbidden.operate.ledger import COLLECTION

        deployments = sorted(self.store.list(COLLECTION, Deployment), key=lambda d: d.index)
        if not deployments:
            return None, None
        last = deployments[-1]
        return last.seen_at, (last.commit or "?")[:12]

    def tick(self, now: datetime | None = None) -> list[Signal]:
        from unbidden.contracts.events import Event, EventType

        now = now or datetime.now(UTC)
        deploy_at, deploy = self._deploy()
        found: list[Signal] = []
        for container in self.world.of_kind("container"):
            source = str(container.attributes.get("service") or container.name)
            window = summarize_window(source, read_container(str(container.name), LOG_EVERY_S), received=now)
            if window["groups"]:
                ranked = sorted(window["groups"].items(), key=lambda kv: -int(kv[1]["count"]))
                window["groups"] = dict(ranked[:MAX_GROUPS])
            key = f"log_windows:{source}"
            windows: list[dict[str, Any]] = [*self.store.get_value(key, []), window][-HISTORY_WINDOWS:]
            self.store.set_value(key, windows)
            for signal in detect(windows, deploy_at=deploy_at, deploy=deploy):
                if signal.kind == "noise":
                    continue
                seen = f"log_signal:{source}:{signal.kind}:{signal.fingerprint}"
                if self.store.get_value(seen) == window["end"][:13]:  # once per source, kind and shape per hour
                    continue
                self.store.set_value(seen, window["end"][:13])
                self.store.append_event(
                    Event(
                        type=EventType.LOG_SIGNAL,
                        actor="observer",
                        entity_id=f"service:{source}",
                        payload={
                            "kind": signal.kind,
                            "title": signal.title,
                            "summary": signal.summary,
                            **signal.details,
                        },
                    )
                )
                self.log(f"logs of {source}: {signal.title}")
                found.append(signal)
        return found
