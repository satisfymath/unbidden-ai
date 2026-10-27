"""Which model serves a call, decided from the profile, the task and what the request holds. Pure.

Secrets and production data never leave, whatever the profile. Private code leaves only renamed by the bridge,
unless a person allowed private code to frontier models in the `frontier` profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from unbidden.brain.tasks import TaskSpec
from unbidden.contracts.llm import ContentLabel, Tier

Profile = Literal["local", "local-first", "frontier"]
NEVER_REMOTE = (ContentLabel.SECRET, ContentLabel.PRODUCTION_DATA)


@dataclass(frozen=True)
class RouteDecision:
    tier: Tier
    fallback: Tier | None
    remote_allowed: bool
    reason: str


def may_leave(label: ContentLabel, profile: Profile, *, private_code_to_frontier: bool) -> bool:
    if profile == "local" or label in NEVER_REMOTE:
        return False
    if label is ContentLabel.PRIVATE_CODE:
        return profile == "frontier" and private_code_to_frontier
    return True  # instructions, synthetic, public code


def decide_route(
    profile: Profile,
    task: TaskSpec,
    label: ContentLabel,
    *,
    private_code_to_frontier: bool = False,
    remote_available: bool = True,
) -> RouteDecision:
    if task.local_only:
        return RouteDecision(Tier.LOCAL, None, False, "this task never leaves the machine")
    leave = may_leave(label, profile, private_code_to_frontier=private_code_to_frontier) and remote_available
    if not leave:
        why = (
            f"profile {profile}"
            if profile == "local"
            else "no remote model is configured"
            if not remote_available
            else f"{label.value} never leaves this machine"
            if label in NEVER_REMOTE
            else f"{label.value} leaves only renamed by the privacy bridge"
        )
        return RouteDecision(Tier.LOCAL, None, False, why)
    remote = Tier.CODE
    if profile == "frontier":
        fallback = Tier.LOCAL if task.escalate else None
        return RouteDecision(remote, fallback, True, f"profile frontier; {label.value} may leave")
    if task.weight == "heavy":
        fallback = Tier.LOCAL if task.escalate else None
        return RouteDecision(remote, fallback, True, f"heavy task and {label.value} may leave: frontier first")
    fallback = remote if task.escalate else None
    return RouteDecision(Tier.LOCAL, fallback, True, "light task: local first")
