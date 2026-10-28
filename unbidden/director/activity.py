"""Activity and outcomes: what Unbidden found, decided and why, built, proposed, proved, spent and learned.

Read from the workspace's own state and the machine's spend ledger, never from what Unbidden printed. Pure reads:
building the report changes nothing. `render_html` writes a self-contained page (no script, no remote asset) a person
can open or attach; it holds titles and reasons, never code, logs or data rows.
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import datetime
from typing import Any

from unbidden.contracts.capability import CapabilityNeed, NeedStatus
from unbidden.contracts.common import EvidenceLevel, utc_now
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.director.learn import PRIOR_MEAN, beliefs
from unbidden.store import Store

LEVELS = {1: "suspicion", 2: "reproduced", 3: "lab", 4: "validated", 5: "operational", 6: "persistent"}
TOP = 8


def _reason(opp: Opportunity) -> str:
    return str((opp.details.get("decision") or {}).get("reason") or "no decision recorded")


def _brief(opp: Opportunity) -> dict[str, Any]:
    return {"id": opp.id, "title": opp.title, "level": int(opp.evidence_level), "status": opp.status.value}


def _rejudged(store: Store, opp: Opportunity) -> str | None:
    """A level recorded under older test rules, judged again with today's where the raw test data exists: None when
    it still holds (or cannot be re-judged), otherwise what today's rules say instead."""
    from unbidden.contracts.experiment import Experiment
    from unbidden.lab.evaluator import classify_tests, validates

    experiment_id = (opp.details.get("verdict") or {}).get("experiment_id") or opp.details.get("experiment_id")
    experiment = store.get("experiments", str(experiment_id), Experiment) if experiment_id else None
    if experiment is None or experiment.baseline_tests is None or experiment.candidate_tests is None:
        return None
    outcome, _ = classify_tests(experiment.baseline_tests, experiment.candidate_tests)
    return None if validates(outcome) else f"not L4 under today's test rules ({outcome.value})"


def build(store: Store, workspace: str, spend_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    opps = store.list("opportunities", Opportunity)
    by_status = Counter(o.status.value for o in opps)
    declined = [o for o in opps if o.status is OpportunityStatus.DECLINED]
    waiting = [
        o
        for o in opps
        if o.status is OpportunityStatus.OPEN and (o.details.get("decision") or {}).get("chosen") == "wait"
    ]
    proven = sorted(
        (o for o in opps if o.evidence_level >= EvidenceLevel.FUNCTIONAL_VALIDATION),
        key=lambda o: (-o.evidence_level, o.created_at),
    )
    invalidated = [o for o in opps if (o.details.get("outcome") or {}).get("invalidated")]
    proposals = store.list("proposals", Proposal)
    needs = store.list("needs", CapabilityNeed)
    rows = [r for r in spend_rows or [] if r.get("workspace") == workspace]
    learned = {
        f"{source} · {category} · {language}": {
            "successes": b.successes,
            "failures": b.failures,
            "p": round(b.mean, 2),
            "prior": PRIOR_MEAN,
        }
        for (source, category, language), b in sorted(beliefs(store).items())
        if b.successes or b.failures
    }
    return {
        "workspace": workspace,
        "at": utc_now().isoformat(),
        "discovered": {"total": len(opps), "by_status": dict(by_status)},
        "experimenting": [_brief(o) for o in opps if o.status is OpportunityStatus.EXPERIMENTING],
        "declined_because": Counter(_reason(o) for o in declined).most_common(TOP),
        "waiting_because": Counter(_reason(o) for o in waiting).most_common(TOP),
        "proven": [
            {
                **_brief(o),
                "level_name": LEVELS[int(o.evidence_level)],
                "outcome": (o.details.get("outcome") or {}).get("result"),
                "held_checks": len(o.details.get("rechecks", [])),
                "current_rules": _rejudged(store, o),
            }
            for o in proven[:TOP]
        ],
        "invalidated": [
            {**_brief(o), "why": (o.details.get("outcome") or {}).get("invalidated", {}).get("why")}
            for o in invalidated
        ],
        "proposals": {
            status.value: [p.title for p in proposals if p.status is status]
            for status in ProposalStatus
            if any(p.status is status for p in proposals)
        },
        "capabilities": {
            "needs": Counter(n.status.value for n in needs),
            "awaiting_approval": [
                {"need": n.id, "kind": n.kind, "source": n.source, "capability": n.capability_id}
                for n in needs
                if n.status is NeedStatus.AWAITING_APPROVAL
            ],
            "in_use": [{"kind": n.kind, "source": n.source} for n in needs if n.status is NeedStatus.IN_USE],
        },
        "spent": {
            "calls": len(rows),
            "usd": round(sum(float(r.get("charged") or 0.0) for r in rows), 4),  # the ledger's own charge
            "basis": "list price x reported tokens; the provider's dashboard is the bill",
        },
        "learned": learned,
    }


def render_text(data: dict[str, Any]) -> list[str]:
    d = data["discovered"]
    lines = [f"[bold]{data['workspace']}[/] · {d['total']} opportunities · " + ", ".join(
        f"{n} {s}" for s, n in sorted(d["by_status"].items())
    )]  # fmt: skip
    if data["proven"]:
        lines.append("[bold]proven[/]")
        for p in data["proven"]:
            held = f", held {p['held_checks']}x" if p["held_checks"] else ""
            outcome = f", live: {p['outcome']}" if p["outcome"] else ""
            lines.append(f"  L{p['level']} {p['level_name']}{outcome}{held} · {p['title']}")
            if p["current_rules"]:
                lines.append(f"     [yellow]recorded under older rules: {p['current_rules']}[/]")
    for o in data["invalidated"]:
        lines.append(f"  [red]invalidated[/] {o['title']}: {o['why']}")
    for title, key in (("declined, because", "declined_because"), ("waiting, because", "waiting_because")):
        if data[key]:
            lines.append(f"[bold]{title}[/]")
            lines += [f"  {n:>4} · {reason[:140]}" for reason, n in data[key]]
    for status, titles in data["proposals"].items():
        lines.append(f"[bold]proposals {status}[/]: " + "; ".join(t[:60] for t in titles[:3]))
    caps = data["capabilities"]
    if caps["needs"]:
        lines.append("[bold]capabilities[/] " + ", ".join(f"{n} {s}" for s, n in caps["needs"].items()))
        for a in caps["awaiting_approval"]:
            lines.append(
                f"  awaiting approval: {a['kind']} for {a['source']} (unbidden forge approve {a['capability']})"
            )
    if data["learned"]:
        lines.append("[bold]learned[/] (chance an experiment succeeds; prior 0.6)")
        lines += [f"  {k}: {v['p']} ({v['successes']} won, {v['failures']} lost)" for k, v in data["learned"].items()]
    s = data["spent"]
    lines.append(f"[bold]spent[/] US${s['usd']:.4f} in {s['calls']} remote call(s) · {s['basis']}")
    return lines


CSS = """
:root{--bg:#fbfbf9;--fg:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;--ok:#1f7a4d;--bad:#b3261e;--chip:#f0efe9}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--line:#2f2e2b;--ok:#5cc28f;
--bad:#f2867d;--chip:#232220}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:880px;margin:0 auto;padding:32px 16px}h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;
margin:28px 0 8px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}p.meta{color:var(--muted);margin:0}
table{width:100%;border-collapse:collapse}td{padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}
td.n{text-align:right;white-space:nowrap;color:var(--muted);width:1%}.chip{display:inline-block;padding:0 8px;
border-radius:10px;background:var(--chip);font-size:13px;margin-right:6px}.ok{color:var(--ok)}.bad{color:var(--bad)}
"""


def _proven_line(p: dict[str, Any]) -> str:
    line = p["title"]
    if p["outcome"]:
        line += f" — live: {p['outcome']}"
    if p["held_checks"]:
        line += f", held {p['held_checks']}x"
    if p["current_rules"]:
        line += f" — recorded under older rules: {p['current_rules']}"
    return line


def render_html(data: dict[str, Any]) -> str:
    e = html.escape

    def rows(items: list[tuple[str, str]]) -> str:
        return "<table>" + "".join(f"<tr><td class=n>{e(a)}</td><td>{e(b)}</td></tr>" for a, b in items) + "</table>"

    d = data["discovered"]
    parts = [
        f"<h1>{e(data['workspace'])}</h1>",
        f"<p class=meta>Activity and outcomes · {e(datetime.fromisoformat(data['at']).strftime('%Y-%m-%d %H:%M'))} UTC"
        f" · {d['total']} opportunities</p>",
        "<p>" + "".join(f"<span class=chip>{n} {e(s)}</span>" for s, n in sorted(d["by_status"].items())) + "</p>",
    ]
    if data["proven"]:
        parts.append("<h2>Proven</h2>")
        parts.append(rows([(f"L{p['level']} {p['level_name']}", _proven_line(p)) for p in data["proven"]]))
    if data["invalidated"]:
        parts.append("<h2 class=bad>Invalidated</h2>")
        parts.append(rows([("L4", f"{o['title']}: {o['why']}") for o in data["invalidated"]]))
    for title, key in (("Declined, and why", "declined_because"), ("Waiting, and why", "waiting_because")):
        if data[key]:
            parts.append(f"<h2>{title}</h2>")
            parts.append(rows([(str(n), reason) for reason, n in data[key]]))
    if data["proposals"]:
        parts.append("<h2>Proposals</h2>")
        parts.append(rows([(s, "; ".join(t)) for s, t in data["proposals"].items()]))
    caps = data["capabilities"]
    if caps["needs"]:
        parts.append("<h2>Capabilities built</h2>")
        items = [(str(n), s) for s, n in caps["needs"].items()]
        items += [("awaiting", f"{a['kind']} for {a['source']}") for a in caps["awaiting_approval"]]
        items += [("in use", f"{a['kind']} for {a['source']}") for a in caps["in_use"]]
        parts.append(rows(items))
    if data["learned"]:
        parts.append("<h2>Learned</h2>")
        parts.append(rows([
            (f"{v['p']:.2f}", f"{k} — {v['successes']} won, {v['failures']} lost (prior {v['prior']})")
            for k, v in data["learned"].items()
        ]))  # fmt: skip
    s = data["spent"]
    parts.append("<h2>Spent</h2>")
    parts.append(f"<p>US${s['usd']:.4f} in {s['calls']} remote call(s). <span class=meta>{e(s['basis'])}</span></p>")
    title = f"Unbidden activity · {e(data['workspace'])}"
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport "
        f"content='width=device-width,initial-scale=1'><title>{title}</title><style>{CSS}</style></head>"
        f"<body><main>{''.join(parts)}</main></body></html>\n"
    )
