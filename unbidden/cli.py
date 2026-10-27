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
        if opp.source == "robustness":
            from unbidden.lab.robust import RobustLab

            robust = RobustLab(
                runtime.workspace.repo,
                runtime.store,
                runtime.brain,
                stack,
                images["python"],
                progress=lambda m: status.update(m),
            )
            result = asyncio.run(robust.run(opp))
        elif opp.category == "performance":
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
        "use_new_capabilities": "require_approval",
    },
    # Unbidden opens pull requests on its own for what reaches the mandate's evidence level; people merge.
    "autopilot": {
        "open_pull_requests": "allow",
        "merge_pull_requests": "deny",
        "deploy": "deny",
        "rollback": "deny",
        "use_new_capabilities": "allow",
    },
    # Unbidden also merges L4 work, deploys it with the team's steps, judges every deploy, and rolls back to the
    # last healthy version when one degrades or the system goes down. Requires a passed rollback drill.
    "autonomous": {
        "open_pull_requests": "allow",
        "merge_pull_requests": "allow",
        "deploy": "allow",
        "rollback": "allow",
        "use_new_capabilities": "allow",
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


def cmd_forge(args: argparse.Namespace) -> int:
    """Build, list or approve capabilities Unbidden made for itself."""
    import asyncio

    from unbidden.forge.adapter import LogAdapter
    from unbidden.forge.build import Forge, compose_logs
    from unbidden.runtime import Runtime

    runtime = Runtime.open(Workspace.find())
    store = runtime.store
    if args.action == "approve":
        adapter = store.get("capabilities", args.target, LogAdapter)
        if adapter is None or adapter.status != "validated":
            err.print("only a validated capability can be approved")
            return 1
        adapter.status, adapter.approved_by = "approved", f"person:{getpass.getuser()}"
        store.put("capabilities", adapter)
        store.append_event(
            Event(
                type=EventType.CAPABILITY_APPROVED,
                actor=adapter.approved_by,
                entity_id=adapter.id,
                payload={"source": adapter.source, "version": adapter.version},
            )
        )
        console.print(f"approved {adapter.id} ({adapter.source} v{adapter.version})")
        return 0
    if args.action == "build":
        service = args.target or "backend"
        lines = compose_logs(runtime.workspace.repo, service)
        with console.status(f"forging a log adapter for {service} from {len(lines)} lines"):
            forge = Forge(runtime.brain, store, remote=runtime.bridge() is not None)
            result = asyncio.run(forge.build_log_adapter(f"compose:{service}", lines))
        for note in result.notes:
            console.print(f"  [dim]{note}[/]")
        if result.adapter is None:
            err.print("no adapter was built")
            return 1
        a = result.adapter
        console.print(f"{a.id} {a.source} v{a.version}: [bold]{a.status}[/] · {a.quality}")
        console.print(f"  pattern: {a.pattern}", markup=False)
        return 0
    adapters = store.list("capabilities", LogAdapter)
    if _emit(args, [a.model_dump(mode="json") for a in adapters]):
        return 0
    for a in adapters:
        console.print(f"{a.id}  {a.source} v{a.version}  {a.status:10} coverage {a.quality.get('coverage')}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """Real traffic of a service, read with the capability Forge built for its log format."""
    from unbidden.forge.build import compose_logs
    from unbidden.forge.logs import summarize, usable

    ws = Workspace.find()
    ws.require()
    store = ws.store()
    source = f"compose:{args.service}"
    adapter = usable(store, ws.mandate(), source)
    if adapter is None:
        err.print(f"no usable capability reads {source}; run `unbidden forge build {args.service}`")
        return 1
    traffic = summarize(adapter, compose_logs(ws.repo, args.service, tail=args.tail))
    data = {
        "adapter": adapter.id,
        "lines": traffic.lines,
        "parsed": traffic.parsed,
        "routes": {r: dict(c) for r, c in traffic.by_route.items()},
    }
    if _emit(args, data):
        return 0
    console.print(f"{source} via {adapter.id} v{adapter.version}: {traffic.parsed}/{traffic.lines} lines parsed")
    for route, counts in sorted(traffic.by_route.items(), key=lambda kv: -sum(kv[1].values()))[:20]:
        console.print(f"  {route:44} {dict(counts)}")
    return 0


def cmd_investigate(args: argparse.Namespace) -> int:
    """Explain a failure between a healthy and a failed version, read-only, with the local model."""
    import asyncio

    from unbidden.research.investigate import Investigation
    from unbidden.runtime import Runtime

    runtime = Runtime.open(Workspace.find())
    incident = args.incident or f"version {args.bad[:12]} failed where {args.good[:12]} worked"
    investigation = Investigation(
        runtime.workspace.repo,
        runtime.brain,
        runtime.store,
        runtime.workspace.mandate(),
        args.good,
        args.bad,
        incident,
        f"{args.good[:12]}..{args.bad[:12]}",
        log=lambda m: console.print(f"[dim]{m}[/]"),
    )
    hypothesis = asyncio.run(investigation.run())
    if hypothesis is None:
        err.print("no hypothesis reached")
        return 1
    if _emit(args, hypothesis.model_dump(mode="json")):
        return 0
    console.print(
        f"[bold]hypothesis[/] ({hypothesis.mechanism}, confidence {hypothesis.confidence:.2f}, "
        f"claimed {hypothesis.confidence_claimed:.2f}, L{int(hypothesis.evidence_level)})"
    )
    console.print(hypothesis.statement)
    for item in hypothesis.evidence:
        console.print(f"  - {item}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Look for crashes in a package with property-based tests the local model writes, run offline."""
    import asyncio

    from unbidden.research.robustness import RobustnessProbe, parse_crashes
    from unbidden.runtime import Runtime

    runtime = Runtime.open(Workspace.find())
    rev = head_sha(runtime.workspace.repo)
    _, images = runtime.stack_and_images(rev)
    if "python" not in images:
        err.print("robustness probes need a Python package")
        return 2
    probe = RobustnessProbe(runtime.workspace.repo, runtime.store, runtime.brain, images["python"])
    with console.status(f"writing property tests for {args.package}"):
        tests = asyncio.run(probe.write_tests(rev, args.package, args.count))
    artifacts = runtime.workspace.dir / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / f"robustness-{rev[:12]}.answer.md").write_text(probe.last_answer)
    if tests is None:
        err.print("the local model wrote no usable tests (its answer is kept in .unbidden/artifacts)")
        return 1
    artifacts = runtime.workspace.dir / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / f"robustness-{rev[:12]}.py").write_text(tests)
    with console.status("running them offline"):
        output = probe.run_tests(rev, tests)
    (artifacts / f"robustness-{rev[:12]}.log").write_text(output)
    crashes = parse_crashes(output, args.package)
    opened = probe.record(rev, args.package, tests, crashes)
    summary = next((ln for ln in reversed(output.splitlines()) if " passed" in ln or " failed" in ln), "no summary")
    console.print(f"{summary.strip()} · {len(crashes)} crash(es) inside {args.package} · {len(opened)} new")
    for crash in crashes:
        console.print(f"  [red]{crash.exception}[/] at {crash.frame}: {crash.message[:120]}")
        console.print(f"    example: {crash.example[:200]}", markup=False)
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Show or set which models may serve this workspace. Secrets and production data stay local in every profile."""
    import yaml

    ws = Workspace.find()
    ws.require()
    raw = yaml.safe_load(ws.mandate_path.read_text())
    models = raw["mandate"].setdefault("models", {"profile": "local-first", "private_code_to_frontier": "deny"})
    if args.profile is None and args.private_code is None:
        if _emit(args, models):
            return 0
        console.print(
            f"profile: [bold]{models.get('profile', 'local-first')}[/] · private code to frontier models: "
            f"{models.get('private_code_to_frontier', 'deny')} · secrets and production data: always local"
        )
        return 0
    before = dict(models)
    if args.profile is not None:
        models["profile"] = args.profile
    if args.private_code is not None:
        models["private_code_to_frontier"] = args.private_code
    ws.mandate_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    ws.mandate()
    ws.store().append_event(
        Event(
            type=EventType.MANDATE_CHANGED,
            actor=f"person:{getpass.getuser()}",
            payload={"models": {"from": before, "to": models}},
        )
    )
    console.print(f"models: {models}")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    """Which model would serve each kind of task here, and why. Dry: no model is called."""
    from unbidden.brain.route_policy import decide_route
    from unbidden.brain.tasks import TASKS, TYPICAL_SOURCES
    from unbidden.contracts.llm import Message, Source
    from unbidden.guardian.classify import classify
    from unbidden.runtime import Runtime

    runtime = Runtime.open(Workspace.find())
    models = runtime.workspace.mandate().models
    rows = []
    for purpose, spec in TASKS.items():
        sources: tuple[Source, ...] = TYPICAL_SOURCES.get(purpose, ("repo",))
        for source in sources:
            label = classify(
                [Message(role="user", content="", source=source)], repo_public=runtime.brain.repo_public
            ).label  # type: ignore[arg-type]
            d = decide_route(
                models.profile,
                spec,
                label,
                private_code_to_frontier=models.private_code_to_frontier == "allow",
                remote_available=runtime.bridge() is not None or models.profile != "local",
            )
            rows.append(
                {
                    "task": purpose,
                    "weight": spec.weight,
                    "content": label.value,
                    "first": d.tier.value,
                    "fallback": d.fallback.value if d.fallback else "-",
                    "why": d.reason,
                }
            )
    if _emit(args, {"profile": models.profile, "repo_public": runtime.brain.repo_public, "routes": rows}):
        return 0
    console.print(
        f"profile [bold]{models.profile}[/] · repository {'public' if runtime.brain.repo_public else 'private'}"
        f" · secrets and production data always local"
    )
    table = Table(box=None, header_style="bold")
    for column in ("task", "weight", "content", "first", "fallback", "why"):
        table.add_column(column)
    for row in rows:
        table.add_row(*(str(row[k]) for k in ("task", "weight", "content", "first", "fallback", "why")))
    console.print(table)
    return 0


def cmd_egress(args: argparse.Namespace) -> int:
    """Everything that left this machine, or tried to: destination, purpose, size, and the exact payload."""
    ws = Workspace.find()
    ws.require()
    attempts = sorted(ws.store().list("egress", EgressAttempt), key=lambda a: a.created_at)
    if _emit(args, [a.model_dump(mode="json") for a in attempts]):
        return 0
    for a in attempts[-args.last :]:
        mark = {"allowed_sent": "[green]sent[/]", "blocked": "[red]blocked[/]"}.get(a.status, a.status)
        console.print(
            f"{a.created_at:%m-%d %H:%M} {mark:22} {a.destination:16} {a.purpose:26} "
            f"{a.verdict.payload_bytes:>7} B  {'; '.join(a.verdict.reasons)[:80]}"
        )
        if args.payload and a.status != "blocked":
            console.print(a.payload, markup=False, highlight=False)
    if not attempts:
        console.print("Nothing has left this machine.")
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
    models = command("models", cmd_models, "show or set the model profile: local, local-first or frontier")
    models.add_argument("profile", nargs="?", choices=["local", "local-first", "frontier"])
    models.add_argument("--private-code", choices=["allow", "deny"], help="private code to frontier models")
    command("route", cmd_route, "which model serves each task here, and why (dry)")
    egress = command("egress", cmd_egress, "everything that left this machine, with the exact payloads")
    egress.add_argument("--payload", action="store_true")
    egress.add_argument("--last", type=int, default=30)
    probe = command("probe", cmd_probe, "look for crashes with property-based tests, run offline", json_out=False)
    probe.add_argument("package")
    probe.add_argument("--count", type=int, default=8, help="how many functions to probe")
    inv = command("investigate", cmd_investigate, "explain a failure between two versions, read-only")
    inv.add_argument("good")
    inv.add_argument("bad")
    inv.add_argument("--incident", help="what was observed, in words")
    forge = command("forge", cmd_forge, "capabilities unbidden built for itself: list, build or approve")
    forge.add_argument("action", nargs="?", choices=["list", "build", "approve"], default="list")
    forge.add_argument("target", nargs="?", help="service to build for, or capability id to approve")
    logs = command("logs", cmd_logs, "real traffic of a service, read with a capability forge built")
    logs.add_argument("service", nargs="?", default="backend")
    logs.add_argument("--tail", type=int, default=2000)
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
