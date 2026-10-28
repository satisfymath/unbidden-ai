from __future__ import annotations

import subprocess
import sys

import pytest

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, Opportunity
from unbidden.director.decide import Context, decide

pytestmark = pytest.mark.unit


def test_every_adapter_loads_in_one_order_whatever_module_is_imported_first() -> None:
    code = (
        "import unbidden.languages.golang; from unbidden.languages import adapters; print([a.name for a in adapters()])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "['node', 'python', 'go']"


def test_findings_in_a_language_whose_lab_is_not_shown_wait(mandate: Mandate) -> None:
    found = Opportunity(
        source="go-vet", category="bugs", title="1 go-vet finding", summary="printf", dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="report/report.go")],
        details={"tool": "go-vet", "paths": ["report/report.go"]},
    )  # fmt: skip
    decided = decide(found, mandate, Context(open_pull_requests=0, attempts=0, ci_commands="go test ./..."))
    assert decided.chosen is ActionKind.WAIT and "not shown for Go" in decided.reason
