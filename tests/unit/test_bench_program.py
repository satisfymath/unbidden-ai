from __future__ import annotations

from typing import Any

import pytest

from bench.causes import root_cause
from bench.compare import mcnemar_exact
from bench.corpus import split_counts

pytestmark = pytest.mark.unit


def row(**state: Any) -> dict[str, Any]:
    files = state.pop("files", {"code": 50, "by_language": {"Python": 50}})
    decide = state.pop("decide", None)
    return {"steps": {"checkout": {"code": 0}}, "files": files, "decide": decide, "state": state}


def test_root_causes_follow_the_record_in_order() -> None:
    assert root_cause({"steps": {"checkout": {"code": 128}}}) == "checkout_failed"
    assert root_cause(row(languages=[], files={"code": 2, "by_language": {"Shell": 2}})) == "not_software"
    assert root_cause(row(languages=[], files={"code": 90, "by_language": {"Go": 90}})) == "unsupported_language"
    assert root_cause(row(languages=[])) == "no_dependency_manifest"
    py39 = "dependency image for python failed to build: ... does not satisfy Python>=3.10 ..."
    assert root_cause(row(languages=["python"], problems=[py39], analyzers=[])) == "deps_python_version"
    meta = "dependency image for python failed to build: prepare_metadata_for_build_editable ... ModuleNotFoundError"
    assert root_cause(row(languages=["python"], problems=[meta], analyzers=[])) == "deps_project_metadata"
    assert root_cause(row(languages=["node"], analyzers=[])) == "no_applicable_analyzer"
    assert root_cause(row(languages=["python"], analyzers=[{"completeness": "failed"}])) == "analyzer_failed"
    done = [{"completeness": "complete"}]
    assert root_cause(row(languages=["python"], analyzers=done)) == "nothing_found"
    declined = {"chosen": {"decline": 3}}
    assert root_cause(row(languages=["python"], analyzers=done, decide=declined)) == "findings_declined"
    acting = {"chosen": {"decline": 1, "run_experiment": 1}}
    assert root_cause(row(languages=["python"], analyzers=done, decide=acting)) == "actionable"


def test_mcnemar_exact_is_two_sided_on_discordant_pairs() -> None:
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 6) == pytest.approx(2 / 64)  # six gained, none lost
    assert mcnemar_exact(3, 3) == 1.0


def test_every_language_reaches_every_split() -> None:
    assert split_counts(3) == {"dev": 1, "validation": 1, "holdout": 1}
    assert split_counts(30) == {"dev": 12, "validation": 9, "holdout": 9}
    assert sum(split_counts(7).values()) == 7


def test_subprojects_analyzed_count_even_when_the_root_has_no_stack() -> None:
    done = [{"completeness": "complete"}]
    assert root_cause(row(languages=[], analyzers=done)) == "nothing_found"
