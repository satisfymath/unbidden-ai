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
    # Set by `apply_mandate`: why no model may serve the call at all (the mandate denies local inference and the call
    # may not go remote), and a fallback the route would take but the mandate refuses (recorded, never taken).
    denied: str | None = None
    fallback_refused: Tier | None = None


def apply_mandate(decision: RouteDecision, *, local_inference: str, local_fallback: str) -> RouteDecision:
    """The mandate's two rules about the local model, applied to a route so that what is shown is what runs.

    `local_inference: deny`: a call the route sends local is denied, and a local fallback is refused.
    `local_fallback: deny`: a local fallback is refused. Both were applied only at call time before (stage 11:
    `unbidden route` and a lab's progress line named a local fallback the mandate would never take).
    """
    denied = decision.denied
    fallback, refused = decision.fallback, decision.fallback_refused
    if local_inference == "deny" and not decision.tier.remote:
        denied = f"the mandate denies local inference, and this call may not go remote: {decision.reason}"
    if fallback is Tier.LOCAL and (local_inference == "deny" or local_fallback == "deny"):
        fallback, refused = None, Tier.LOCAL
    return RouteDecision(decision.tier, fallback, decision.remote_allowed, decision.reason, denied, refused)


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
