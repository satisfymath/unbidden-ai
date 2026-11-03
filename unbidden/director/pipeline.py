"""Where an opportunity is on the one road every proven change travels, so the app can say "3 of 7" and what comes
next. Read from the records only; nothing here decides."""

from __future__ import annotations

from typing import Any

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus

STAGES: tuple[str, ...] = ("found", "decided", "measured", "proven", "proposed", "merged", "deployed")
OF = len(STAGES)

# What each job type is doing to the opportunity it carries, and the stage it works toward.
JOB_STAGE: dict[str, tuple[str, str]] = {
    "observe.head": ("looking at the head", "found"),
    "observe.scan": ("scanning the code", "found"),
    "observe.checks": ("running the project's own checks", "found"),
    "world.refresh": ("mapping the running system", "found"),
    "connect.survey": ("checking the connections", "found"),
    "research.probe": ("probing for crashes", "found"),
    "research.investigate": ("investigating", "found"),
    "research.consistency": ("checking consistency", "found"),
    "director.sweep": ("deciding what to try", "decided"),
    "lab.experiment": ("measuring a candidate in the sandbox", "measured"),
    "proposal.prepare": ("preparing the branch", "proposed"),
    "github.publish": ("opening the pull request", "proposed"),
    "github.poll": ("following the pull request", "merged"),
    "ops.deploy": ("deploying", "deployed"),
    "ops.drill": ("proving the rollback", "deployed"),
    "observe.live": ("watching the deploy", "deployed"),
    "forge.build": ("building a capability", "found"),
    "goal.pursue": ("pursuing a goal", "found"),
}


def stage_of(opp: Opportunity | None, proposal: Proposal | None) -> tuple[int, str]:
    """(number from 1, name) of the stage the opportunity has reached."""
    if proposal is not None:
        if proposal.status is ProposalStatus.MERGED:
            deployed = bool(proposal.model_dump().get("deployed"))
            return (OF, STAGES[6]) if deployed else (6, STAGES[5])
        if proposal.status in (ProposalStatus.PR_OPENED, ProposalStatus.PUBLISHING, ProposalStatus.READY):
            return 5, STAGES[4]
    if opp is None:
        return 1, STAGES[0]
    if opp.status is OpportunityStatus.PROPOSED:
        return 5, STAGES[4]
    if int(opp.evidence_level) >= int(EvidenceLevel.FUNCTIONAL_VALIDATION):
        return 4, STAGES[3]
    if int(opp.evidence_level) >= int(EvidenceLevel.REPRODUCTION) or opp.details.get("attempts"):
        return 3, STAGES[2]
    if opp.details.get("decision") or opp.status is OpportunityStatus.EXPERIMENTING:
        return 2, STAGES[1]
    return 1, STAGES[0]


def stage_text(n: int, name: str) -> str:
    return f"{n}/{OF} {name}"


def job_stage(job_type: str) -> tuple[str, str]:
    """(what it is doing, the stage it works toward) for a job type; unknown types say their name."""
    return JOB_STAGE.get(job_type, (job_type, "found"))


def next_after(job_type: str) -> str | None:
    """The stage after the one a job works toward, as the road goes; None past the end."""
    _, toward = job_stage(job_type)
    index = STAGES.index(toward)
    return STAGES[index + 1] if index + 1 < OF else None


def describe(store: Any, opp: Opportunity) -> dict[str, Any]:
    """The stage of one opportunity, from its proposal when it has one."""
    proposal = store.get_by_key("proposals", opp.id, Proposal)
    n, name = stage_of(opp, proposal)
    return {"stage": n, "of": OF, "name": name, "text": stage_text(n, name)}
