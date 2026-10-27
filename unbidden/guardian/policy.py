"""Deny-by-default policy engine over the mandate."""

from __future__ import annotations

from dataclasses import dataclass

from unbidden.contracts.guardian import ActionRequest, Autonomy, Decision, Mandate, PolicyVerdict

GITHUB_HOSTS = ("github.com", "api.github.com")


@dataclass(frozen=True, slots=True)
class CapabilityRule:
    autonomy_field: str
    network: str | None = None  # which allowlist governs its destinations, if it may use the network


CAPABILITIES: dict[str, CapabilityRule] = {
    "repo.read": CapabilityRule("observe"),
    "analyzer.run": CapabilityRule("observe"),
    "runtime.read": CapabilityRule("observe"),  # docker ps/inspect, read-only SQL, HTTP GET to published ports
    "sandbox.run": CapabilityRule("run_experiments"),
    "model.local": CapabilityRule("run_experiments"),
    "sandbox.provision": CapabilityRule("provision_dependencies", network="package_registries"),
    "model.remote.synthetic": CapabilityRule("delegate_synthetic", network="remote_models"),
    "model.remote.screenshot": CapabilityRule("delegate_synthetic", network="remote_models"),
    # Read-only: the status of the team's own checks on a commit of the mandate's repository.
    "github.read": CapabilityRule("observe", network="github"),
    "github.push_branch": CapabilityRule("open_pull_requests", network="github"),
    "github.open_pull_request": CapabilityRule("open_pull_requests", network="github"),
    "github.merge_pull_request": CapabilityRule("merge_pull_requests", network="github"),
    "capability.use": CapabilityRule("use_new_capabilities"),  # turn on an adapter Forge built and validated
    "deploy.run": CapabilityRule("deploy"),
    "deploy.rollback": CapabilityRule("rollback"),
}


def _allowlist(mandate: Mandate, network: str) -> list[str]:
    match network:
        case "package_registries":
            return mandate.egress.package_registries
        case "remote_models":
            return mandate.egress.remote_models.destinations
        case "github":
            return list(GITHUB_HOSTS) if mandate.egress.github.repository else []
        case _:
            return []


class PolicyEngine:
    def __init__(self, mandate: Mandate) -> None:
        self.mandate = mandate

    def evaluate(self, request: ActionRequest, *, approved: bool = False) -> PolicyVerdict:
        rule = CAPABILITIES.get(request.capability)
        if rule is None:
            return PolicyVerdict(
                decision=Decision.DENY,
                rule="deny_by_default",
                reasons=[f"capability {request.capability!r} is not known to the mandate"],
            )
        if request.destructive:
            return PolicyVerdict(
                decision=Decision.DENY, rule="destructive_operations", reasons=["destructive operations are denied"]
            )
        if request.destinations:
            if rule.network is None:
                return PolicyVerdict(
                    decision=Decision.DENY,
                    rule="no_network",
                    reasons=[f"{request.capability} may not use the network"],
                )
            allowed = _allowlist(self.mandate, rule.network)
            outside = [d for d in request.destinations if d not in allowed]
            if outside:
                return PolicyVerdict(
                    decision=Decision.DENY,
                    rule=f"egress.{rule.network}",
                    reasons=[f"destination {d} is not in the mandate's allowlist" for d in outside],
                )
        autonomy: Autonomy = getattr(self.mandate.autonomy, rule.autonomy_field)
        if autonomy is Autonomy.DENY:
            return PolicyVerdict(
                decision=Decision.DENY,
                rule=f"autonomy.{rule.autonomy_field}",
                reasons=[f"the mandate denies {rule.autonomy_field}"],
            )
        if autonomy is Autonomy.REQUIRE_APPROVAL and not approved:
            return PolicyVerdict(
                decision=Decision.REQUIRE_APPROVAL,
                rule=f"autonomy.{rule.autonomy_field}",
                reasons=[f"{rule.autonomy_field} needs a person's approval"],
            )
        return PolicyVerdict(decision=Decision.ALLOW, rule=f"autonomy.{rule.autonomy_field}", reasons=[request.purpose])
