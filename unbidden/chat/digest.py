"""The evidence an analysis may send to a model: a bounded digest written by this function from Unbidden's own
records (counts, levels, statuses, titles, ids, medians), never rows, log lines or event payloads.

The digest is labelled `record` (classified like the repository's code: public or private), and the classifier's
text patterns still raise it when something slipped through; this function removes what those patterns look for
(emails, IP addresses, log-looking lines) because none of it is needed to analyse, not to change the label a real
leak would deserve. Nothing here changes the classification of any data: a digest that still carries a secret or
production data is refused by the router like anything else.
"""

from __future__ import annotations

import json
from typing import Any

from unbidden.guardian.classify import _EMAIL, _IPV4, _LOG_LINE
from unbidden.guardian.scanner import redact_text

LIMIT = 12_000  # bytes, under the egress gate's default payload cap (20 000) with the prompt around it

# Keys of the activity record worth an analysis; the rest are either large or about the UI.
ACTIVITY_KEYS = (
    "discovered", "decided", "built", "proved", "declined", "waiting", "invalidated", "proposals", "needs",
    "blocks", "spend", "learned", "deploys", "connections", "world",
)  # fmt: skip


def _scrub(text: str) -> str:
    text = redact_text(text)
    text = _EMAIL.sub("<email>", text)
    text = _IPV4.sub("<ip>", text)
    return "\n".join(line for line in text.splitlines() if not _LOG_LINE.search(line))


def _compact(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def evidence_digest(
    summary: dict[str, Any],
    selected: list[dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    limit: int = LIMIT,
) -> str:
    """`summary` is the source's summary (activity, counts, jobs, highlights); `selected` the entities in context as
    small dicts (title, status, level, decision, verdict); `results` the tool results of this turn (summaries)."""
    ws = summary.get("workspace", {})
    lines = [
        f"workspace {ws.get('name')} ({ws.get('mode')} record); head {str(ws.get('head') or '')[:12]}; "
        f"observed {summary.get('observed_at')}; freshness {summary.get('freshness')}",
        f"counts: {_compact(summary.get('counts', {}), 600)}",
        f"jobs: {_compact(summary.get('jobs', {}), 400)}",
    ]
    for note in ws.get("notes", []) or []:
        lines.append(f"note: {str(note)[:200]}")
    activity = summary.get("activity", {}) or {}
    for key in ACTIVITY_KEYS:
        if key in activity:
            lines.append(f"{key}: {_compact(activity[key], 1500)}")
    for h in summary.get("highlights", []) or []:
        lines.append(f"highlight: {_compact(h, 300)}")
    for s in selected:
        lines.append(f"selected: {_compact(s, 800)}")
    for r in results:
        lines.append(f"read: {r.get('tool')!s}: {str(r.get('summary'))[:400]}")
    text = _scrub("\n".join(lines))
    if len(text.encode()) > limit:
        text = text.encode()[: limit - 1].decode(errors="ignore") + "…"
    return text
