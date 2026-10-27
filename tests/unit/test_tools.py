from __future__ import annotations

import json

import pytest

from unbidden.contracts.finding import Completeness
from unbidden.sandbox.runner import SandboxResult
from unbidden.sandbox.tools import parse_eslint, parse_pyright, parse_ruff, parse_tsc

pytestmark = pytest.mark.unit


def result(stdout: str = "", exit_code: int | None = 0, *, timed_out: bool = False, cut: bool = False) -> SandboxResult:
    return SandboxResult(
        exit_code=exit_code, stdout=stdout, stderr="", timed_out=timed_out, duration_s=1.0,
        stdout_truncated=cut, stderr_truncated=False,
    )  # fmt: skip


def test_tsc_findings_and_clean_run() -> None:
    out = "src/a.ts(14,7): error TS2345: Argument of type 'string | undefined' is not assignable.\n"
    report = parse_tsc(result(out, 2), ["tsc"])
    assert report.completeness is Completeness.COMPLETE
    (finding,) = report.findings
    assert (finding.rule, finding.path, finding.line) == ("TS2345", "src/a.ts", 14)
    assert parse_tsc(result("", 0), ["tsc"]).completeness is Completeness.COMPLETE


def test_tsc_crash_is_failed_not_clean() -> None:
    assert parse_tsc(result("error: cannot find tsconfig", 1), ["tsc"]).completeness is Completeness.FAILED


def test_truncated_output_can_never_resolve() -> None:
    report = parse_tsc(result("", 0, cut=True), ["tsc"])
    assert report.completeness is Completeness.TRUNCATED
    assert not report.can_resolve
    assert not parse_tsc(result("", None, timed_out=True), ["tsc"]).can_resolve


def test_eslint_json() -> None:
    out = json.dumps(
        [{"filePath": "/work/src/a.ts", "messages": [{"ruleId": "no-var", "severity": 2, "message": "m", "line": 3}]}]
    )
    (finding,) = parse_eslint(result(out, 1), ["eslint"]).findings
    assert (finding.rule, finding.path, finding.severity) == ("no-var", "src/a.ts", "error")
    assert parse_eslint(result("Oops", 2), ["eslint"]).completeness is Completeness.FAILED


def test_ruff_and_pyright_json() -> None:
    ruff = json.dumps([{"code": "F401", "filename": "/work/pkg/a.py", "location": {"row": 1}, "message": "unused"}])
    assert parse_ruff(result(ruff), ["ruff"]).findings[0].path == "pkg/a.py"
    pyright = json.dumps(
        {
            "generalDiagnostics": [
                {"file": "/work/pkg/a.py", "severity": "error", "message": "bad\nmore", "rule": "reportX",
                 "range": {"start": {"line": 4}}},
                {"file": "/work/pkg/a.py", "severity": "information", "message": "fyi"},
            ]
        }
    )  # fmt: skip
    (finding,) = parse_pyright(result(pyright, 1), ["pyright"]).findings
    assert (finding.line, finding.message) == (5, "bad")
