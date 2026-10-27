"""Run the trusted tools on a commit and turn their findings into opportunities."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from unbidden.contracts.common import EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.finding import AnalyzerReport, Finding
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.sandbox.provision import DependencyImage, link_dependencies, sandbox_spec
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.sandbox.tools import Tool
from unbidden.store import Store

ACTOR = "observer"
COLLECTION = "opportunities"


def run_tool(
    runner: SandboxRunner, repo: Path, rev: str, tool: Tool, image: DependencyImage, *, timeout_s: float = 600
) -> AnalyzerReport:
    work = snapshot(repo, rev)
    try:
        link_dependencies(work, image)
        argv = list(tool.argv)
        result = runner.run(sandbox_spec(image, argv, cwd=tool.cwd, timeout_s=timeout_s), work)
        return tool.report(result, argv)
    finally:
        discard(work)


def group_key(finding: Finding) -> str:
    """Findings are fixed together per file for types, and per rule and directory for lint and format.

    Small, coherent groups make reviewable pull requests and keep each experiment's candidate focused.
    """
    if finding.category == "types":
        return f"{finding.tool}:{finding.path}"
    directory = str(PurePosixPath(finding.path).parent)
    return f"{finding.tool}:{finding.rule}:{directory}"


@dataclass
class Sweep:
    opened: list[Opportunity]
    updated: list[Opportunity]
    resolved: list[Opportunity]


TITLE_MAX = 200


def _title(tool: str, findings: list[Finding]) -> str:
    first = findings[0]
    n = len(findings)
    plural = "s" if n > 1 else ""
    if first.category == "types":
        title = f"{n} {tool} error{plural} in {first.path}"
    else:
        title = f"{n} {tool} {first.rule} finding{plural} in {PurePosixPath(first.path).parent}/"
    # Deep monorepo paths exceed a title; the full paths are in the details.
    return title if len(title) <= TITLE_MAX else f"{title[: TITLE_MAX - 30]}...{title[-27:]}"


def record_report(store: Store, report: AnalyzerReport, rev: str) -> Sweep:
    """Open or refresh one opportunity per group. Only a complete report may resolve anything."""
    sha = hashlib.sha256(report.model_dump_json().encode()).hexdigest()
    store.append_event(
        Event(
            type=EventType.ANALYZER_RAN,
            actor=ACTOR,
            payload={
                "tool": report.tool,
                "rev": rev,
                "completeness": report.completeness.value,
                "findings": len(report.findings),
                "error": report.error,
                "sha256": sha,
            },
        )
    )
    groups: dict[str, list[Finding]] = defaultdict(list)
    for finding in report.findings:
        groups[group_key(finding)].append(finding)

    sweep = Sweep([], [], [])
    evidence = EvidenceRef(kind="analyzer_report", locator=f"{report.tool}@{rev}", sha256=sha)
    for key, findings in groups.items():
        details = {
            "tool": report.tool,
            "rev": rev,
            "fingerprints": sorted(f.fingerprint for f in findings),
            "findings": [f.model_dump(mode="json") for f in findings[:50]],
            "paths": sorted({f.path for f in findings}),
        }
        existing = store.get_by_key(COLLECTION, key, Opportunity)
        if existing is None:
            opp = Opportunity(
                source=report.tool,
                category=findings[0].category,
                title=_title(report.tool, findings),
                summary="; ".join(sorted({f"{f.rule}: {f.message}" for f in findings}))[:2000],
                dedup_key=key,
                evidence=[evidence],
                details=details,
            )
            store.put(COLLECTION, opp, key=key)
            store.append_event(
                Event(type=EventType.OPPORTUNITY_OPENED, actor=ACTOR, entity_id=opp.id, correlation_id=opp.id,
                      payload={"title": opp.title, "key": key})
            )  # fmt: skip
            sweep.opened.append(opp)
        else:
            existing.details = details
            existing.title = _title(report.tool, findings)
            existing.evidence = [*existing.evidence[-4:], evidence]
            existing.updated_at = utc_now()
            store.put(COLLECTION, existing)
            sweep.updated.append(existing)

    if not report.can_resolve:
        return sweep
    live = {OpportunityStatus.OPEN, OpportunityStatus.EXPERIMENTING, OpportunityStatus.PROPOSED}
    for opp in store.list(COLLECTION, Opportunity):
        if opp.source != report.tool or opp.dedup_key in groups or opp.status not in live:
            continue
        opp.status = OpportunityStatus.CLOSED
        opp.details = {**opp.details, "resolved_at_rev": rev}
        opp.evidence = [*opp.evidence, evidence]
        opp.updated_at = utc_now()
        store.put(COLLECTION, opp)
        store.append_event(
            Event(type=EventType.OPPORTUNITY_RESOLVED, actor=ACTOR, entity_id=opp.id, correlation_id=opp.id,
                  payload={"rev": rev, "reason": f"a complete {report.tool} report no longer shows it"})
        )  # fmt: skip
        sweep.resolved.append(opp)
    return sweep
