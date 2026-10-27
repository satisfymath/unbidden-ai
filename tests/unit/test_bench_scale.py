from __future__ import annotations

from typing import Any

import pytest

from bench.scale import bench_mandate, classify
from unbidden.guardian.mandate import load_mandate
from unbidden.workspace import default_mandate

pytestmark = pytest.mark.unit


def test_the_benchmark_mandate_never_reaches_github_and_caps_spend(tmp_path: Any) -> None:
    raw = bench_mandate(default_mandate("x", "upstream/x"), profile="frontier", repo_budget_usd=0.75)
    path = tmp_path / "mandate.yaml"
    import yaml

    path.write_text(yaml.safe_dump(raw))
    mandate = load_mandate(path)
    a = mandate.autonomy
    assert (a.open_pull_requests, a.merge_pull_requests, a.deploy, a.rollback) == ("deny",) * 4
    assert a.run_experiments == "allow" and a.use_new_capabilities == "allow"
    assert mandate.business_constraints.maximum_monthly_spend_usd == 0.75
    assert mandate.models.profile == "frontier" and mandate.models.private_code_to_frontier == "deny"


def _row(**state: Any) -> dict[str, Any]:
    return {"steps": {"checkout": {"code": 0}}, "state": state}


def test_outcomes_follow_fixed_rules() -> None:
    assert classify({"steps": {"checkout": {"code": 1}}}) == "checkout failed"
    assert classify(_row(languages=[])) == "unsupported stack"
    assert classify(_row(languages=["python"], analyzers=[{"completeness": "failed"}])) == "bootstrap failed"
    complete = [{"completeness": "complete"}]
    assert classify(_row(languages=["python"], analyzers=complete, opportunities=[])) == "nothing found"
    found = [{"level": 2}]
    assert classify(_row(languages=["python"], analyzers=complete, opportunities=found)) == "found, not experimented"
    assert (
        classify(_row(languages=["python"], analyzers=complete, opportunities=found, experiments=2))
        == "found, experiments did not validate"
    )
    # An L4 verdict that did not improve anything is not a validated improvement.
    verdicts = [{"improved": False, "level": 4}, {"improved": True, "level": 4}]
    assert classify(_row(languages=["python"], analyzers=complete, verdicts=verdicts[:1])) == "nothing found"
    assert classify(_row(languages=["python"], analyzers=complete, verdicts=verdicts)) == "validated improvement (L4)"
