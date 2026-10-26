"""A proposal is a local branch plus a pull-request body built only from recorded evidence."""

from __future__ import annotations

from pathlib import Path

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, Proposal, Verdict
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.publish.git_writer import branch_name, commit_files
from unbidden.store import Store

LEVELS = {
    3: "L3 · lab improvement: the tool's findings are gone in an offline sandbox; behavior was not checked by tests",
    4: "L4 · functional validation: the findings are gone and the test suite shows no regression",
}


AUTHORS = {
    "tool": "the tool's own fixer",
    "model": "a local model (Muse Glimmer), on this machine",
    "bridge": "Muse Spark from a synthetic version of the problem, adapted locally by Muse Glimmer",
}


def _tests_line(experiment: Experiment) -> str:
    if experiment.baseline_tests is None or experiment.candidate_tests is None:
        return "No test suite was run."
    rounds = experiment.candidate_tests.rounds

    def failing(rounds_: list[list[str]]) -> int:
        return sum(1 for r in rounds_ if r)

    return (
        f"Test suite, {rounds} rounds per side: base failed in {failing(experiment.baseline_tests.failed_per_round)}, "
        f"candidate failed in {failing(experiment.candidate_tests.failed_per_round)}."
    )


PERF_LEVELS = {
    3: "L3 · lab improvement: measured faster in an offline sandbox; the test suite was not run",
    4: "L4 · functional validation: measured faster in an offline sandbox, and the test suite shows no regression",
}


def build_perf_body(opp: Opportunity, experiment: Experiment, verdict: Verdict, origin: str) -> str:
    """A performance proposal leads with what was measured, how, and what it does not prove yet."""
    d = opp.details
    criteria = verdict.criteria
    lines = [
        f"**{opp.title}**",
        "",
        PERF_LEVELS.get(int(verdict.evidence_level), f"L{int(verdict.evidence_level)}"),
        "",
        "### What was found",
        f"- {opp.summary}",
        f"- How: the database schema was read live (read-only) and compared with the endpoints that read "
        f"`{d.get('table')}`; no one pointed at this table.",
        "",
        "### What was measured",
        *(f"- {reason}" for reason in verdict.reasons),
        f"- {len(experiment.samples_before_ms)} requests per side after a warm-up, each side in its own sandbox "
        f"with a fresh database, migrations applied by this repository's own CI setup steps.",
        f"- Criteria fixed before measuring: {criteria.get('test')}, alpha {criteria.get('alpha')}, median "
        f"improvement of at least {float(criteria.get('min_median_improvement', 0)):.0%}, {criteria.get('ci')}.",
        f"- {_tests_line(experiment)}",
        f"- Candidate written by: {AUTHORS.get(origin, origin)}. The workload (synthetic data and the request) "
        f"was written by the same local model and is kept with the experiment (sha256 "
        f"`{(experiment.workload_sha256 or '')[:12]}`).",
        "",
        "### Caveats",
        *(f"- {c}" for c in (verdict.caveats or ["none recorded"])),
        "",
        f"<sub>Proposed by Unbidden. Opportunity `{opp.id}`, experiment `{experiment.id}`. "
        "Nothing was merged or deployed; a person decides.</sub>",
    ]
    return "\n".join(lines) + "\n"


def proposal_title(opp: Opportunity, verdict: Verdict) -> str:
    if opp.category == "performance" and verdict.reasons:
        # "GET /x: median 13.0 ms → 4.1 ms (69% faster), ..." becomes the headline.
        headline = verdict.reasons[0].split(", one-sided")[0]
        return f"perf: index {opp.details.get('table')}.{opp.details.get('column')} · {headline}"[:120]
    return f"fix: {opp.title}"[:120]


def build_body(opp: Opportunity, experiment: Experiment, verdict: Verdict, origin: str) -> str:
    if experiment.samples_before_ms:
        return build_perf_body(opp, experiment, verdict, origin)
    findings = opp.details.get("findings", [])[:20]
    lines = [
        f"**{opp.title}**",
        "",
        LEVELS.get(int(verdict.evidence_level), f"L{int(verdict.evidence_level)}"),
        "",
        "### What was found",
        *(f"- `{f['path']}{':' + str(f['line']) if f.get('line') else ''}` {f['rule']}: {f['message']}"
          for f in findings),
        "",
        "### What was measured",
        f"- Base commit `{experiment.base_sha}`; every check the repository uses ran on both sides, offline.",
        f"- Targeted findings before: {len(opp.details.get('fingerprints', []))}; after: 0.",
        f"- Findings anywhere before: {len(experiment.findings_before)}; after: {len(experiment.findings_after)}.",
        f"- {_tests_line(experiment)}",
        f"- Candidate written by: {AUTHORS.get(origin, origin)}.",
        "",
        "### Caveats",
        *(f"- {c}" for c in (verdict.caveats or ["none recorded"])),
        "",
        f"<sub>Proposed by Unbidden. Opportunity `{opp.id}`, experiment `{experiment.id}`. "
        "Nothing was merged or deployed; a person decides.</sub>",
    ]  # fmt: skip
    return "\n".join(lines) + "\n"


def prepare(repo: Path, store: Store, opp: Opportunity, experiment: Experiment, verdict: Verdict) -> Proposal:
    if not verdict.improved:
        raise ValueError("only an improved verdict can become a proposal")
    candidate = opp.details["candidate"]
    files: dict[str, str] = candidate["files"]
    origin: str = candidate["origin"]
    title = proposal_title(opp, verdict)
    branch = branch_name(opp.title, opp.id)
    body = build_body(opp, experiment, verdict, origin)
    commit = commit_files(repo, experiment.base_sha, files, f"{title}\n\n{body}", branch)
    proposal = Proposal(
        opportunity_id=opp.id,
        experiment_id=experiment.id,
        branch=branch,
        base_sha=experiment.base_sha,
        commit_sha=commit,
        title=title,
        body_md=body,
        evidence_level=EvidenceLevel(verdict.evidence_level),
    )
    store.put("proposals", proposal, key=opp.id)
    opp.status = OpportunityStatus.PROPOSED
    opp.details = {**opp.details, "proposal_id": proposal.id}
    store.put("opportunities", opp)
    store.append_event(
        Event(type=EventType.PROPOSAL_READY, actor="lab", entity_id=proposal.id, correlation_id=opp.id,
              payload={"branch": branch, "commit": commit, "level": int(verdict.evidence_level)})
    )  # fmt: skip
    return proposal
