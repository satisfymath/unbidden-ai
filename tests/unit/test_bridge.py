from __future__ import annotations

import json
from pathlib import Path

import pytest

from unbidden.brain.providers.mock import MockProvider
from unbidden.brain.router import Brain
from unbidden.bridge.rename import RenameMap, build_map, private_names
from unbidden.bridge.service import PrivacyBridge
from unbidden.config import load_config
from unbidden.contracts.finding import Finding
from unbidden.contracts.guardian import EgressAttempt, Mandate
from unbidden.contracts.llm import LLMRequest, Tier
from unbidden.store import Store

pytestmark = pytest.mark.unit

CODE = """from billing.ledger import post_entry

TAX_RATE = 0.19


def invoice_total(customer_id: str, lines: list[float]) -> float:
    total = sum(lines)
    return post_entry(customer_id, total * (1 + TAX_RATE))
"""


def test_private_names_cover_definitions_imports_and_paths() -> None:
    names = private_names({"acme/billing/invoice.py": CODE}, extra=("acme-shop",))
    assert {"acme", "billing", "invoice", "ledger", "post_entry", "TAX_RATE", "invoice_total", "acme-shop"} <= names
    assert "total" not in names  # a local variable says nothing about the owner
    assert "float" not in names


def test_rename_round_trip_and_unsafe_suggestions() -> None:
    private = {"invoice_total", "TAX_RATE", "billing"}
    rename = build_map(private, {"invoice_total": "compute_sum", "TAX_RATE": "lines", "billing": "billing"}, [CODE])
    assert rename.forward["invoice_total"] == "compute_sum"
    assert rename.forward["TAX_RATE"] != "lines"  # already used in the code: reversing would corrupt it
    assert rename.forward["billing"] != "billing"
    synthetic = rename.to_synthetic(CODE)
    assert "invoice_total" not in synthetic and "TAX_RATE" not in synthetic
    assert rename.to_real(synthetic) == CODE


def test_imported_names_are_private() -> None:
    js = 'import { chargeCard, refund as undo } from "./payments";\nimport Stripe from "stripe";\n'
    names = private_names({"a.ts": js, "b.py": "from shop.cart import (\n    add_item,\n    drop_item,\n)\n"})
    assert {"chargeCard", "refund", "undo", "Stripe", "payments", "add_item", "drop_item", "shop", "cart"} <= names


def test_paths_keep_extensions() -> None:
    rename = RenameMap({"billing": "module_a", "invoice": "part_b"})
    assert rename.path_to_synthetic("billing/invoice.py") == "module_a/part_b.py"
    assert rename.path_to_real("module_a/part_b.py") == "billing/invoice.py"


class RemoteMock(MockProvider):
    host = "api.meta.ai"


async def test_only_the_synthetic_task_leaves_and_the_answer_comes_back_real(
    store: Store, mandate: Mandate, tmp_path: Path
) -> None:
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "invoice.py").write_text(CODE)
    config = load_config()
    config.routing[Tier.LOCAL].provider = "local"
    config.routing[Tier.CODE].provider = "remote"
    local, remote = MockProvider(), RemoteMock()
    local.script(
        "bridge.names",
        {
            "renames": [{"real": "invoice_total", "synthetic": "compute_amount"}],
            "task": "Fix an unused import in a module.",
        },
    )

    def solve(request: LLMRequest) -> str:
        sent = request.messages[0].content
        path = next(line.split("file: ")[1] for line in sent.splitlines() if line.startswith("# file: "))
        body = sent.split("```\n", 1)[1].split("```", 1)[0]
        return f"# file: {path}\n```python\n{body.replace('* (1 + ', '* (1.0 + ')}```"

    remote.script("bridge.solve", solve)
    brain = Brain(config, {"local": local, "remote": remote}, store, mandate)
    finding = Finding.build(
        tool="ruff", rule="F401", severity="error", category="lint", path="billing/invoice.py",
        message="`billing.ledger.post_entry` imported but unused",
    )  # fmt: skip
    result = await PrivacyBridge(brain, repo_name="acme-shop").solve(tmp_path, [finding], correlation_id="opp_1")

    (attempt,) = store.list("egress", EgressAttempt)
    assert attempt.status == "allowed_sent"
    for real in ("invoice_total", "billing", "ledger", "post_entry", "TAX_RATE", "invoice", "acme"):
        assert real not in attempt.payload, real
    assert "compute_amount" in json.loads(attempt.payload)["messages"][0]["content"]
    assert result.files is not None
    fixed = result.files["billing/invoice.py"]
    assert "def invoice_total(" in fixed and "(1.0 + TAX_RATE)" in fixed
