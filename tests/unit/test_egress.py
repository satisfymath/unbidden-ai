from __future__ import annotations

import pytest

from unbidden.contracts.guardian import Mandate
from unbidden.guardian.egress import evaluate_github, evaluate_synthetic
from unbidden.guardian.scanner import SensitiveTermIndex

pytestmark = pytest.mark.unit

REAL = SensitiveTermIndex(["order_items", "acme-payments", "/orders/{order_id}"])


def test_synthetic_task_passes(mandate: Mandate) -> None:
    payload = "Write a function that groups child_rows by parent_id without one query per parent."
    verdict = evaluate_synthetic(mandate, "api.meta.ai", payload, REAL)
    assert verdict.allowed, verdict.reasons
    assert verdict.payload_bytes == len(payload)


def test_real_identifiers_block_a_remote_task(mandate: Mandate) -> None:
    verdict = evaluate_synthetic(mandate, "api.meta.ai", "Fix the N+1 on order_items in acme-payments", REAL)
    assert not verdict.allowed
    assert "identifier:order_items" in verdict.matched


def test_unknown_destination_and_size_cap(mandate: Mandate) -> None:
    verdict = evaluate_synthetic(mandate, "api.other.ai", "x" * 30_000, REAL)
    assert not verdict.allowed
    assert len(verdict.reasons) == 2


def test_github_payload_may_name_code_but_not_secrets(mandate: Mandate) -> None:
    assert evaluate_github(mandate, "api.github.com", "fix: order_items query").allowed
    leaked = evaluate_github(mandate, "api.github.com", "DB_PASSWORD=abcdefgh123")
    assert not leaked.allowed


def test_github_needs_a_configured_repository() -> None:
    assert not evaluate_github(Mandate(workspace="x"), "api.github.com", "hello").allowed
