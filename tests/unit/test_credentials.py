from __future__ import annotations

import os
from pathlib import Path

import pytest

from unbidden.guardian.credentials import CredentialBroker
from unbidden.guardian.egress import evaluate_synthetic

pytestmark = pytest.mark.unit


def test_secrets_leave_the_environment_and_are_given_only_for_their_purpose(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("MODEL_API_KEY=sk-live-0123456789abcdef\nPROBE_PASSWORD=hunter2hunter2\n")
    os.environ["MODEL_API_KEY"] = "sk-live-0123456789abcdef"
    seen: list[tuple[str, str, bool]] = []
    held = CredentialBroker(audit=lambda n, p, g: seen.append((n, p, g)))
    held.load([env])
    held.grant("MODEL_API_KEY", "model.remote")
    assert "MODEL_API_KEY" not in os.environ
    assert held.get("MODEL_API_KEY", "model.remote") == "sk-live-0123456789abcdef"
    assert held.get("MODEL_API_KEY", "github") is None
    assert held.get("PROBE_PASSWORD", "probe") is None  # never granted
    assert seen == [
        ("MODEL_API_KEY", "model.remote", True),
        ("MODEL_API_KEY", "github", False),
        ("PROBE_PASSWORD", "probe", False),
    ]
    assert all("0123456789abcdef" not in repr(s) for s in seen)


def test_the_egress_gate_refuses_a_payload_holding_a_credential_value(credentials: CredentialBroker, mandate) -> None:  # type: ignore[no-untyped-def]
    os.environ["GITHUB_TOKEN"] = "gho_notAPatternScannersKnow42"
    assert credentials.get("GITHUB_TOKEN", "github")
    from unbidden.guardian.scanner import SensitiveTermIndex

    verdict = evaluate_synthetic(
        mandate, "api.meta.ai", "fix this: token gho_notAPatternScannersKnow42", SensitiveTermIndex()
    )
    assert not verdict.allowed and any("held credential" in r for r in verdict.reasons)
