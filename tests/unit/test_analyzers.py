from __future__ import annotations

import pytest

from unbidden.contracts.finding import AnalyzerReport, Completeness, Finding
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.observe.analyzers import COLLECTION, group_key, record_report
from unbidden.store import Store

pytestmark = pytest.mark.unit


def finding(path: str, rule: str = "TS2345", category: str = "types", tool: str = "tsc") -> Finding:
    return Finding.build(tool=tool, rule=rule, severity="error", category=category, path=path, message=f"{rule} m")


def report(findings: list[Finding], completeness: Completeness = Completeness.COMPLETE) -> AnalyzerReport:
    return AnalyzerReport(tool="tsc", argv=["tsc"], exit_code=2, findings=findings, completeness=completeness)


def test_grouping() -> None:
    assert group_key(finding("src/a.ts")) == "tsc:src/a.ts"
    lint = finding("src/x/a.ts", rule="no-var", category="lint", tool="eslint")
    assert group_key(lint) == "eslint:no-var:src/x"


def test_open_refresh_and_resolve(store: Store) -> None:
    sweep = record_report(store, report([finding("a.ts"), finding("a.ts", "TS2322"), finding("b.ts")]), "r1")
    assert len(sweep.opened) == 2
    sweep = record_report(store, report([finding("a.ts")]), "r2")
    assert len(sweep.updated) == 1 and len(sweep.resolved) == 1
    closed = store.get_by_key(COLLECTION, "tsc:b.ts", Opportunity)
    assert closed is not None and closed.status is OpportunityStatus.CLOSED


def test_incomplete_report_resolves_nothing(store: Store) -> None:
    record_report(store, report([finding("a.ts")]), "r1")
    sweep = record_report(store, report([], Completeness.TRUNCATED), "r2")
    assert sweep.resolved == []
    still = store.get_by_key(COLLECTION, "tsc:a.ts", Opportunity)
    assert still is not None and still.status is OpportunityStatus.OPEN


def test_a_build_failure_keeps_the_installers_own_error() -> None:
    from unbidden.sandbox.provision import NEEDS_COMPILER, build_error

    stderr = "\n".join(
        [
            "#8 [4/5] RUN uv sync --frozen",
            "#8 2.101 Resolved 210 packages in 3ms",
            "#8 2.133 error: Failed to build `pywatchman==3.0.0`",
            "#8 2.133          error: [Errno 2] No such file or directory: 'gcc'",
            "#8 ERROR: process did not complete successfully: exit code: 1",
            "Dockerfile:12",
            "  12 | >>> RUN uv sync --frozen",
            "ERROR: failed to build: failed to solve: exit code: 1",
        ]
    )
    kept = build_error(stderr)
    assert "pywatchman" in kept and NEEDS_COMPILER.search(kept)
