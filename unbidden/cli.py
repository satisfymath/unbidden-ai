"""`unbidden`: the command line. Every command that shows state also accepts --json."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.table import Table

from unbidden import __version__
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import EgressAttempt
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
        if opp.category == "performance":
            from unbidden.lab.perf import PerfLab

            perf = PerfLab(
                runtime.workspace.repo, runtime.brain, runtime.store, stack, images, progress=lambda m: status.update(m)
            )
            result = asyncio.run(perf.run(opp))
        else:
            lab = FixLab(
                runtime.workspace.repo,
                runtime.store,
                runtime.brain,
                stack,
                images,
                progress=lambda m: status.update(m),
                bridge=runtime.bridge(),
                bridge_first=args.bridge,
            )
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


def cmd_watch(args: argparse.Namespace) -> int:
    """Run in the foreground until interrupted (or one full cycle with --once)."""
    import asyncio

    from unbidden.daemon.loop import watch
    from unbidden.runtime import Runtime

    runtime = Runtime.open(Workspace.find())

    def log(message: str) -> None:
        console.print(f"[dim]{datetime.now():%H:%M:%S}[/] {message}")

    log(f"watching {runtime.workspace.repo} (ctrl-c to stop, `unbidden kill` to freeze)")
    try:
        asyncio.run(watch(runtime, log=log, interval_s=args.interval, once=args.once))
    except KeyboardInterrupt:
        log("stopped")
    return 0


def _proposal_for(store: Any, opportunity_id: str) -> Proposal | None:
    return store.get_by_key("proposals", opportunity_id, Proposal)


def _approve(store: Any, proposal: Proposal, hours: float) -> None:
    from datetime import timedelta

    from unbidden.daemon.cycle import job
    from unbidden.guardian.approvals import grant
    from unbidden.publish.github import CAPABILITY

    approval = grant(store, CAPABILITY, proposal.id, granted_by=getpass.getuser(), ttl=timedelta(hours=hours))
    store.append_event(
        Event(
            type=EventType.APPROVAL_GRANTED,
            actor=f"person:{approval.granted_by}",
            entity_id=approval.id,
            correlation_id=proposal.opportunity_id,
            payload={"capability": CAPABILITY, "proposal": proposal.id},
        )
    )
    store.enqueue(
        job(
            "github.publish",
            f"{proposal.id}:{approval.id}",
            {"id": proposal.id},
            correlation_id=proposal.opportunity_id,
        )
    )


def _reject(store: Any, opp: Opportunity, reason: str) -> None:
    opp.status = OpportunityStatus.DECLINED
    opp.details = {**opp.details, "rejected_because": reason}
    store.put("opportunities", opp)
    proposal = _proposal_for(store, opp.id)
    if proposal is not None and proposal.status is ProposalStatus.READY:
        proposal.status = ProposalStatus.REJECTED
        store.put("proposals", proposal)
    store.append_event(
        Event(
            type=EventType.APPROVAL_REJECTED,
            actor=f"person:{getpass.getuser()}",
            entity_id=opp.id,
            correlation_id=opp.id,
            payload={"reason": reason},
        )
    )


def cmd_approve(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    store = ws.store()
    proposal = _proposal_for(store, args.id)
    if proposal is None:
        err.print(f"no proposal for {args.id} yet")
        return 1
    _approve(store, proposal, args.hours)
    console.print(f"Approved: the pull request for {proposal.branch} opens on the next cycle (`unbidden watch`).")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    ws = Workspace.find()
    ws.require()
    store = ws.store()
    opp = store.get("opportunities", args.id, Opportunity)
    if opp is None:
        err.print(f"no opportunity {args.id}")
        return 1
    _reject(store, opp, args.reason)
    console.print(f"Rejected {opp.id}. It will not be proposed again.")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Go through every proposal waiting for a person: read its evidence, then approve, reject or skip."""
    from rich.markdown import Markdown

    ws = Workspace.find()
    ws.require()
    store = ws.store()
    waiting = store.list("proposals", Proposal, status=ProposalStatus.READY.value)
    if not waiting:
        console.print("Nothing is waiting for you.")
        return 0
    for proposal in waiting:
        opp = store.get("opportunities", proposal.opportunity_id, Opportunity)
        if opp is None or opp.status is OpportunityStatus.DECLINED:
            continue
        console.rule(f"[bold]{proposal.title}")
        console.print(Markdown(proposal.body_md))
        console.print(f"[dim]branch {proposal.branch} · commit {proposal.commit_sha[:12]}[/]")
        answer = console.input("[bold][a]pprove · [r]eject · [s]kip ? [/]").strip().lower()[:1]
        if answer == "a":
            _approve(store, proposal, args.hours)
            console.print("[green]approved[/]: it opens on the next cycle")
        elif answer == "r":
            reason = console.input("why (optional): ").strip() or "rejected by a person in review"
            _reject(store, opp, reason)
            console.print("[red]rejected[/]")
    return 0


MODES: dict[str, dict[str, str]] = {
    # Unbidden prepares everything and asks before anything reaches GitHub.
    "supervised": {
        "open_pull_requests": "require_approval",
        "merge_pull_requests": "deny",
        "deploy": "deny",
        "rollback": "deny",
    },
    # Unbidden opens pull requests on its own for what reaches the mandate's evidence level; people merge.
    "autopilot": {"open_pull_requests": "allow", "merge_pull_requests": "deny", "deploy": "deny", "rollback": "deny"},
    # Unbidden also merges L4 work, deploys it with the team's steps, judges every deploy, and rolls back to the
    # last healthy version when one degrades or the system goes down. Requires a passed rollback drill.
    "autonomous": {
        "open_pull_requests": "allow",
        "merge_pull_requests": "allow",
        "deploy": "allow",
        "rollback": "allow",
    },
}


def _current_mode(autonomy: dict[str, Any]) -> str:
    return next((m for m, v in MODES.items() if all(autonomy.get(k, "deny") == x for k, x in v.items())), "custom")


def cmd_mode(args: argparse.Namespace) -> int:
    """Show or set how much unbidden may do on its own."""
    import yaml

    ws = Workspace.find()
    ws.require()
    raw = yaml.safe_load(ws.mandate_path.read_text())
    autonomy = raw["mandate"].setdefault("autonomy", {})
    current = _current_mode(autonomy)
    if args.mode is None:
        if _emit(args, {"mode": current, "autonomy": autonomy}):
            return 0
        console.print(f"mode: [bold]{current}[/]")
        for key, value in autonomy.items():
            console.print(f"  {key:24} {value}")
        return 0
    store = ws.store()
    if args.mode == "autonomous":
        operations = raw["mandate"].get("operations") or {}
        drill = store.get_value("rollback_drill") or {}
        if not operations.get("deploy_steps"):
            err.print("autonomous needs the team's deploy steps in the mandate (operations.deploy_steps)")
            return 2
        if not drill.get("passed"):
            err.print("autonomous needs a passed rollback drill first: run `unbidden drill`")
            return 2
    autonomy.update(MODES[args.mode])
    ws.mandate_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    ws.mandate()  # validate what was written
    store.append_event(
        Event(
            type=EventType.MANDATE_CHANGED,
            actor=f"person:{getpass.getuser()}",
            payload={"from": current, "to": args.mode, "autonomy": MODES[args.mode]},
        )
    )
    console.print(f"mode: [bold]{args.mode}[/] (was {current})")
    return 0


def cmd_drill(args: argparse.Namespace) -> int:
    """Prove rollback works: deploy the previous version with the team's steps, check health, deploy back."""
    import subprocess

    from unbidden.contracts.world import WorldModel
    from unbidden.operate.deploy import drill

    ws = Workspace.find()
    ws.require()
    store = ws.store()
    world = store.get("world", "world", WorldModel)
    health = next(
        (e for e in (world.of_kind("endpoint") if world else []) if e.name.startswith("GET ") and "health" in e.name),
        None,
    )
    if health is None:
        err.print("no live health endpoint is known; run `unbidden map` while the system runs")
        return 2
    url = f"http://127.0.0.1:{health.attributes['port']}{health.name.split(' ', 1)[1]}"
    previous = (
        args.previous
        or subprocess.run(
            ["git", "-C", str(ws.repo), "rev-parse", "HEAD~1"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    with console.status(f"drill: {previous[:12]} and back, watching {url}"):
        record = drill(ws.repo, store, ws.mandate(), previous, url)
    if _emit(args, record):
        return 0
    mark = "[green]passed[/]" if record["passed"] else "[red]failed[/]"
    console.print(f"rollback drill {mark}: back {record['back']}, forth {record['forth']}")
    return 0 if record["passed"] else 1


def cmd_hold(args: argparse.Namespace) -> int:
    from unbidden.operate.holds import active, release

    ws = Workspace.find()
    ws.require()
    store = ws.store()
    if args.action == "release":
        hold = release(store, args.id, f"person:{getpass.getuser()}", args.reason)
        console.print(f"released {hold.id}")
        return 0
    holds = active(store)
    if _emit(args, [h.model_dump(mode="json") for h in holds]):
        return 0
    console.print("\n".join(f"{h.id}  {h.created_at:%Y-%m-%d %H:%M}  {h.reason}" for h in holds) or "No holds.")
    return 0


def cmd_deploys(args: argparse.Namespace) -> int:
    """Every deploy unbidden has seen, with its verdict."""
    from unbidden.observe.live import DeployVerdict

    ws = Workspace.find()
    ws.require()
    store = ws.store()
    verdicts = store.list("deploy_verdicts", DeployVerdict)
    if _emit(args, [v.model_dump(mode="json") for v in verdicts]):
        return 0
    for v in verdicts:
        console.print(
            f"[bold]{v.id.split(':')[0]}[/] {v.id.split(':', 1)[1][:12]} (after {v.previous[:12]}): {v.impact.value}"
        )
        for e in v.endpoints:
            console.print(f"    {e['target']:36} {e['impact']:22} {'; '.join(e['reasons'])}")
    if not verdicts:
        console.print("No deploy judged yet.")
    return 0


def cmd_why(args: argparse.Namespace) -> int:
    """Every decision, verdict and outbound payload behind one opportunity."""
    ws = Workspace.find()
    ws.require()
    store = ws.store()
    opp = store.get("opportunities", args.id, Opportunity)
    if opp is None:
        err.print(f"no opportunity {args.id}")
        return 1
    events = store.events(correlation_id=opp.id)
    egress_ids = [e.entity_id for e in events if e.type in (EventType.EGRESS_ALLOWED, EventType.EGRESS_BLOCKED)]
    attempts = [a for a in (store.get("egress", i, EgressAttempt) for i in egress_ids if i) if a is not None]
    data = {
        "opportunity": opp.model_dump(mode="json", exclude={"details"}),
        "decision": opp.details.get("decision"),
        "verdict": opp.details.get("verdict"),
        "egress": [a.model_dump(mode="json") for a in attempts],
        "events": [e.model_dump(mode="json") for e in events],
    }
    if _emit(args, data):
        return 0
    console.print(f"[bold]{opp.title}[/] · L{int(opp.evidence_level)} · {opp.status.value}")
    if data["decision"]:
        console.print(f"decision: {data['decision']['chosen']} because {data['decision']['reason']}")
    verdict = data["verdict"]
    if verdict:
        console.print(f"verdict: {'improved' if verdict['improved'] else 'not improved'} · tests {verdict['tests']}")
        for reason in verdict["reasons"] + verdict["caveats"]:
            console.print(f"  - {reason}")
    for attempt in attempts:
        state = "[green]sent[/]" if attempt.status == "allowed_sent" else f"[red]{attempt.status}[/]"
        console.print(
            f"egress to {attempt.destination} ({attempt.purpose}): {state}, {attempt.verdict.payload_bytes} bytes"
        )
        for reason in attempt.verdict.reasons:
            console.print(f"  blocked: {reason}")
        if args.payload:
            console.print(attempt.payload, markup=False, highlight=False)
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """Discover the system (repository, running containers, live API, database) and show the World Model."""
    import asyncio

    from unbidden.contracts.world import WorldModel
    from unbidden.runtime import Runtime
    from unbidden.world.discover import discover

    runtime = Runtime.open(Workspace.find())
    repo = runtime.workspace.repo
    if args.cached:
        world = runtime.store.get("world", "world", WorldModel)
        if world is None:
            err.print("no map yet; run `unbidden map`")
            return 1
    else:
        with console.status("mapping the system"):
            brain = None if args.no_model else runtime.brain
            world = asyncio.run(discover(repo, head_sha(repo), runtime.store, runtime.workspace.mandate(), brain))
    if _emit(args, world.model_dump(mode="json")):
        return 0
    mark = {"observed": "[green]observed[/]", "inferred": "[yellow]inferred[/]"}

    def status(r: Any) -> str:
        return mark.get(r.status.value) or r.status.value

    console.print(
        f"[bold]{repo.name}[/] at {world.rev[:12]} · {len(world.resources)} resources, {len(world.relations)} relations"
    )
    containers = {r.attributes.get("service"): r for r in world.of_kind("container")}
    console.print("\n[bold]Services[/]")
    for svc in world.of_kind("service") + world.of_kind("database"):
        live = containers.get(svc.name)
        state = f"{live.attributes.get('state')} {live.attributes.get('ports') or ''}" if live else "not running"
        deps = [r.dst.split(":", 1)[1] for r in world.relations if r.src == svc.id and r.predicate == "depends_on"]
        console.print(
            f"  {svc.name:12} {svc.attributes.get('image') or 'built here':28} {state:24} "
            f"{'→ ' + ', '.join(deps) if deps else ''}"
        )
    tables = world.of_kind("table")
    if tables:
        console.print("\n[bold]Tables[/]")
        for table in tables:
            rows = table.attributes.get("rows_estimate")
            indexes = len(table.attributes.get("indexes", []))
            detail = (
                f"~{rows} rows, {indexes} indexes" if rows is not None else f"model {table.attributes.get('model')}"
            )
            console.print(f"  {table.name:16} {status(table):30} {detail}")
    endpoints = world.of_kind("endpoint")
    if endpoints:
        console.print("\n[bold]Endpoints[/]")
        for endpoint in endpoints:
            touches = [
                f"{r.predicate} {r.dst.split(':', 1)[1]}"
                for r in world.relations
                if r.src == endpoint.id and r.predicate in ("reads", "writes")
            ]
            console.print(f"  {endpoint.name:44} {status(endpoint):30} {', '.join(touches)}")
    if world.blind_spots:
        console.print("\n[bold]What I cannot see[/]")
        for spot in world.blind_spots:
            console.print(f"  - {spot.what}: {spot.why}")
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
    map_ = command("map", cmd_map, "discover the system and show what is known, how, and what cannot be seen")
    map_.add_argument("--cached", action="store_true", help="show the last map without discovering again")
    map_.add_argument("--no-model", action="store_true", help="skip relations inferred by the local model")
    command("status", cmd_status, "what unbidden knows and is doing")
    inbox = command("inbox", cmd_inbox, "opportunities, most proven first")
    inbox.add_argument("--all", action="store_true", help="include closed ones")
    try_ = command("try", cmd_try, "run an experiment on one opportunity now")
    try_.add_argument("id")
    try_.add_argument("--bridge", action="store_true", help="go straight to Muse Spark through the privacy bridge")
    watch = command("watch", cmd_watch, "keep working in the background of this terminal", json_out=False)
    watch.add_argument("--interval", type=float, default=30, help="seconds between looks at HEAD")
    watch.add_argument("--once", action="store_true", help="run one full cycle and exit")
    approve = command("approve", cmd_approve, "allow the pull request of a proven opportunity", json_out=False)
    approve.add_argument("id")
    approve.add_argument("--hours", type=float, default=24, help="how long the approval stays valid")
    review = command("review", cmd_review, "read each waiting proposal and approve, reject or skip it", json_out=False)
    review.add_argument("--hours", type=float, default=24, help="how long each approval stays valid")
    mode = command("mode", cmd_mode, "show or set autonomy: supervised, autopilot or autonomous")
    mode.add_argument("mode", nargs="?", choices=sorted(MODES), help="the mode to switch to")
    drill_ = command("drill", cmd_drill, "prove rollback works before autonomy relies on it")
    drill_.add_argument("previous", nargs="?", help="the version to roll back to (default HEAD~1)")
    hold = command("hold", cmd_hold, "list holds, or release one (people only)")
    hold.add_argument("action", nargs="?", choices=["list", "release"], default="list")
    hold.add_argument("id", nargs="?")
    hold.add_argument("reason", nargs="?", default="released by a person")
    command("deploys", cmd_deploys, "every deploy seen and its verdict")
    reject = command("reject", cmd_reject, "decline an opportunity for good", json_out=False)
    reject.add_argument("id")
    reject.add_argument("reason", nargs="?", default="rejected by a person")
    why = command("why", cmd_why, "decisions, verdicts and every outbound payload behind an opportunity")
    why.add_argument("id")
    why.add_argument("--payload", action="store_true", help="print each outbound payload byte for byte")
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
