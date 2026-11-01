"""One language's provisioning does not block another's work (stage 8, LNbits independent run: the frontend's npm
registry, which the mandate did not list, stopped a probe of the Python code)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import unbidden.runtime as runtime_module
from unbidden.runtime import Runtime

pytestmark = pytest.mark.unit


def test_a_language_that_cannot_be_provisioned_raises_its_own_cause_only_when_asked(monkeypatch: Any) -> None:
    refused = PermissionError("sandbox.provision: destination registry.npmjs.org is not in the mandate's allowlist")

    def provision(repo: Any, rev: str, part: Any, *, policy: Any) -> Any:
        if part == "node-part":
            raise refused
        return "python-image"

    stack = SimpleNamespace(languages=["node", "python"], part=lambda lang: f"{lang}-part")
    monkeypatch.setattr(runtime_module, "provision", provision)
    monkeypatch.setattr(runtime_module, "detect_stack", lambda repo, rev: stack)
    monkeypatch.setattr("unbidden.guardian.policy.PolicyEngine", lambda mandate: None)
    fake = SimpleNamespace(workspace=SimpleNamespace(repo=".", mandate=lambda: None))
    _, images = Runtime.stack_and_images(fake, "HEAD")  # type: ignore[arg-type]
    assert images["python"] == "python-image" and "node" not in images
    with pytest.raises(PermissionError, match=r"registry\.npmjs\.org"):
        images["node"]
