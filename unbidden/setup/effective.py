"""What a mandate lets Unbidden do, in a person's words, decided by the same PolicyEngine the engine uses."""

from __future__ import annotations

from typing import TypedDict

from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.guardian.policy import PolicyEngine

# (what it means, the capability the engine asks the policy about)
ROWS: tuple[tuple[str, str], ...] = (
    ("observe the repository, its CI and running services", "repo.read"),
    ("run experiments in the offline sandbox", "sandbox.run"),
    ("install dependencies while building", "sandbox.provision"),
    ("send synthetic or public content to remote models", "model.remote.synthetic"),
    ("use capabilities it built for itself", "capability.use"),
    ("open pull requests", "github.open_pull_request"),
    ("merge pull requests", "github.merge_pull_request"),
    ("deploy with the team's steps", "deploy.run"),
    ("roll back a deploy", "deploy.rollback"),
    ("write through connections (typed, limited actions)", "connection.write"),
)


class PermissionRow(TypedDict):
    what: str
    capability: str
    decision: str
    rule: str


def effective_permissions(mandate: Mandate) -> list[PermissionRow]:
    engine = PolicyEngine(mandate)
    rows: list[PermissionRow] = []
    for what, capability in ROWS:
        verdict = engine.evaluate(ActionRequest(capability=capability, purpose="setup.summary"))
        rows.append({"what": what, "capability": capability, "decision": verdict.decision.value, "rule": verdict.rule})
    return rows


MARK = {"allow": "allowed", "require_approval": "asks first", "deny": "denied"}


def render(rows: list[PermissionRow]) -> list[str]:
    width = max(len(r["what"]) for r in rows)
    return [f"  {r['what']:<{width}}  {MARK.get(r['decision'], r['decision'])}" for r in rows]
