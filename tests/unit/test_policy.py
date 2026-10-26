from __future__ import annotations

import pytest

from unbidden.contracts.guardian import ActionRequest, Decision, Mandate
from unbidden.guardian.policy import PolicyEngine

pytestmark = pytest.mark.unit


def ask(mandate: Mandate, capability: str, *, approved: bool = False, **kwargs: object) -> Decision:
    request = ActionRequest(capability=capability, purpose="test", **kwargs)  # type: ignore[arg-type]
    return PolicyEngine(mandate).evaluate(request, approved=approved).decision


def test_unknown_capability_is_denied(mandate: Mandate) -> None:
    assert ask(mandate, "shell.exec") is Decision.DENY


def test_default_mandate_denies_everything() -> None:
    empty = Mandate(workspace="x")
    assert ask(empty, "repo.read") is Decision.DENY
    assert ask(empty, "sandbox.run") is Decision.DENY


def test_destructive_is_denied_even_when_allowed(mandate: Mandate) -> None:
    assert ask(mandate, "sandbox.run", destructive=True) is Decision.DENY


def test_destinations_outside_allowlist_are_denied(mandate: Mandate) -> None:
    assert ask(mandate, "model.remote.synthetic", destinations=["api.meta.ai"]) is Decision.ALLOW
    assert ask(mandate, "model.remote.synthetic", destinations=["evil.example"]) is Decision.DENY
    assert ask(mandate, "sandbox.provision", destinations=["registry.npmjs.org"]) is Decision.ALLOW


def test_offline_capability_may_not_use_network(mandate: Mandate) -> None:
    assert ask(mandate, "sandbox.run", destinations=["pypi.org"]) is Decision.DENY


def test_pull_requests_need_approval(mandate: Mandate) -> None:
    assert ask(mandate, "github.open_pull_request", destinations=["api.github.com"]) is Decision.REQUIRE_APPROVAL
    assert ask(mandate, "github.open_pull_request", destinations=["api.github.com"], approved=True) is Decision.ALLOW


def test_merge_is_denied_by_default(mandate: Mandate) -> None:
    assert ask(mandate, "github.merge_pull_request", approved=True) is Decision.DENY
