"""`unbidden`: the command line. Every command that shows state also accepts --json."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.table import Table

from unbidden import __version__
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.observe.scan import ScanDenied, scan
from unbidden.workspace import Workspace, WorkspaceError, head_sha

console = Console()
err = Console(stderr=True)

LEVEL_NAMES = {1: "suspicion", 2: "reproduced", 3: "lab", 4: "validated", 5: "operational", 6: "persistent"}


def _emit(args: argparse.Namespace, data: Any) -> bool:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))
        return True
    return False


def cmd_init(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    created = ws.init()
    store = ws.store()
    data = {"repo": str(ws.repo), "created": created, "mandate": str(ws.mandate_path)}
    if _emit(args, data):
        return 0
    if created:
        console.print(f"[bold]Unbidden is set up in[/] {ws.repo}")
        console.print(f"  mandate: {ws.mandate_path}  (review what it may do on its own)")
        console.print("  next:    unbidden scan")
    else:
        console.print(f"{ws.repo} already has a workspace.")
    store.close()
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    store = ws.store()
    rev = head_sha(ws.repo)
    with console.status("scanning") as status:
        result = scan(ws.repo, rev, store, ws.mandate(), progress=lambda m: status.update(m))
    data = {
        "rev": rev,
        "languages": result.stack.languages,
        "blind_spots": result.stack.blind_spots,
        "problems": result.problems,
        "reports": [
            {"tool": r.tool, "completeness": r.completeness.value, "findings": len(r.findings), "error": r.error}
            for r in result.reports
        ],
        "opened": sum(len(s.opened) for s in result.sweeps),
        "resolved": sum(len(s.resolved) for s in result.sweeps),
    }
    if _emit(args, data):
        return 0
    console.print(f"[bold]{ws.repo.name}[/] at {rev[:12]} · {', '.join(result.stack.languages) or 'no known stack'}")
    for report in result.reports:
        mark = "[green]complete[/]" if report.can_resolve else f"[yellow]{report.completeness.value}[/]"
        console.print(f"  {report.tool:8} {mark:>20}  {len(report.findings)} findings")
    for line in result.stack.blind_spots + result.problems:
        console.print(f"  [dim]blind spot:[/] {line}")
    console.print(f"opened {data['opened']} · resolved {data['resolved']} · see `unbidden inbox`")
    store.close()
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    store = ws.store()
    statuses = [s for s in OpportunityStatus if args.all or s not in (OpportunityStatus.CLOSED,)]
    opps = [o for o in store.list("opportunities", Opportunity) if o.status in statuses]
    opps.sort(key=lambda o: (-o.evidence_level, -o.priority_score, o.created_at))
    if _emit(args, [o.model_dump(mode="json", exclude={"details"}) for o in opps]):
        return 0
    table = Table(box=None, header_style="bold")
    for column in ("id", "evidence", "status", "title"):
        table.add_column(column)
    for o in opps:
        table.add_row(o.id, f"L{int(o.evidence_level)} {LEVEL_NAMES[int(o.evidence_level)]}", o.status.value, o.title)
    console.print(table if opps else "Nothing open.")
    store.close()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    store = ws.store()
    opp = store.get("opportunities", args.id, Opportunity)
    if opp is None:
        err.print(f"no opportunity {args.id}")
        return 1
    events = store.events(correlation_id=opp.id)
    if _emit(args, {"opportunity": opp.model_dump(mode="json"), "events": [e.model_dump(mode="json") for e in events]}):
        return 0
    console.print(f"[bold]{opp.title}[/]  ({opp.id})")
    console.print(f"status {opp.status.value} · evidence L{int(opp.evidence_level)} · source {opp.source}")
    console.print(opp.summary)
    for e in events:
        console.print(f"  [dim]{e.ts:%Y-%m-%d %H:%M:%S}[/] {e.type.value} {json.dumps(e.payload)[:160]}")
    store.close()
    return 0


def cmd_try(args: argparse.Namespace) -> int:
    """Run one experiment now, in the foreground."""
    import asyncio

    from unbidden.lab.fixlab import FixLab
    from unbidden.runtime import Runtime

    runtime = Runtime.open(Workspace.find())
    opp = runtime.store.get("opportunities", args.id, Opportunity)
    if opp is None:
        err.print(f"no opportunity {args.id}")
        return 1
    with console.status("preparing") as status:
        stack, images = runtime.stack_and_images(opp.details["rev"])
        lab = FixLab(runtime.workspace.repo, runtime.store, runtime.brain, stack, images,
                     progress=lambda m: status.update(m))  # fmt: skip
        result = asyncio.run(lab.run(opp))
    data = {
        "opportunity": opp.id,
        "improved": bool(result.verdict and result.verdict.improved),
        "verdict": result.verdict.model_dump(mode="json") if result.verdict else None,
        "origin": result.candidate.origin if result.candidate else None,
        "patch": result.candidate.patch if result.candidate else None,
        "notes": result.notes,
    }
    if _emit(args, data):
        return 0
    if result.verdict is not None and result.verdict.improved:
        console.print(
            f"[green]improved[/] · evidence L{int(result.verdict.evidence_level)} · {result.verdict.tests.value}"
        )
        console.print(result.candidate.patch if result.candidate else "")
    else:
        console.print("[yellow]no improvement proven[/]")
    for note in result.notes + (result.verdict.caveats if result.verdict else []):
        console.print(f"  [dim]{note}[/]")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    store = ws.store()
    opps = store.list("opportunities", Opportunity)
    counts: dict[str, int] = {}
    for o in opps:
        counts[o.status.value] = counts.get(o.status.value, 0) + 1
    data = {
        "repo": str(ws.repo),
        "head": head_sha(ws.repo),
        "kill_switch": ws.killswitch().engaged,
        "last_scan": store.get_value("last_scan"),
        "opportunities": counts,
    }
    if _emit(args, data):
        return 0
    console.print(f"[bold]{ws.repo.name}[/] head {data['head'][:12]}")
    if data["kill_switch"]:
        console.print("[red]kill switch engaged[/]: nothing runs until `unbidden resume`")
    console.print(f"opportunities: {counts or 'none yet'}")
    store.close()
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    ws.killswitch().engage(args.reason)
    console.print("Kill switch engaged. No job starts and no model is called until `unbidden resume`.")
    return 0


def cmd_resume(_: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    ws.killswitch().release()
    console.print("Kill switch released.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="unbidden", description="Intelligence that doesn't wait for instructions.")
    parser.add_argument("--version", action="version", version=f"unbidden {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, handler: Any, help_text: str, *, json_out: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(handler=handler)
        if json_out:
            p.add_argument("--json", action="store_true", help="machine-readable output")
        return p

    command("init", cmd_init, "set up unbidden in this repository")
    command("scan", cmd_scan, "run the repository's own checks in the sandbox and record opportunities")
    command("status", cmd_status, "what unbidden knows and is doing")
    inbox = command("inbox", cmd_inbox, "opportunities, most proven first")
    inbox.add_argument("--all", action="store_true", help="include closed ones")
    try_ = command("try", cmd_try, "run an experiment on one opportunity now")
    try_.add_argument("id")
    show = command("show", cmd_show, "one opportunity with its full history")
    show.add_argument("id")
    kill = command("kill", cmd_kill, "stop everything now", json_out=False)
    kill.add_argument("reason", nargs="?", default="engaged from the CLI")
    command("resume", cmd_resume, "release the kill switch", json_out=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (WorkspaceError, ScanDenied) as exc:
        err.print(f"[red]unbidden:[/] {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
