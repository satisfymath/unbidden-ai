from __future__ import annotations

from pathlib import Path

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


def test_a_finding_in_a_deep_path_still_gets_a_title() -> None:
    from unbidden.observe.analyzers import TITLE_MAX, _title  # pyright: ignore[reportPrivateUsage]

    deep = "packages/" + "/".join(["very-long-directory-name"] * 12) + "/generated/system.gen.d.ts"
    finding = Finding(
        tool="tsc", rule="TS2307", severity="error", category="types", path=deep, line=1, message="m",
        fingerprint="0123456789abcdef",
    )  # type: ignore[arg-type]  # fmt: skip
    assert len(_title("tsc:packages/lexical-devtools", [finding])) <= TITLE_MAX


def test_postinstall_scripts_that_only_install_git_hooks_are_not_run() -> None:
    from unbidden.observe.scan import GIT_HOOK_TOOLS

    assert GIT_HOOK_TOOLS.match("husky") and GIT_HOOK_TOOLS.match("husky install")
    assert not GIT_HOOK_TOOLS.match("pnpm build:packages")


def test_a_build_that_names_a_missing_header_retries_with_its_debian_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from unbidden.observe.stack import PythonStack
    from unbidden.sandbox import provision as prov

    attempts: list[tuple[bool, tuple[str, ...]]] = []
    errors = [
        "error: Failed to build `python-ldap==3.4.8`\nerror: [Errno 2] No such file or directory: 'cc'",
        "Modules/LDAPObject.c:3:10: fatal error: lber.h: No such file or directory",
        "hint: you need to install a library that provides `sasl/sasl.h` for `python-ldap@3.4.8`",
    ]

    def fake(*_: object, system_build_tools: bool, headers: tuple[str, ...] = (), **__: object) -> str:
        attempts.append((system_build_tools, headers))
        if errors:
            raise prov.ProvisionError(errors.pop(0))
        return "image"

    monkeypatch.setattr(prov, "_provision", fake)
    stack = PythonStack(
        version="3.12", lockfile="uv.lock", manifest="pyproject.toml", ruff=True, pyright=False, pytest=True
    )
    assert prov.provision(tmp_path, "HEAD", stack, system_build_tools=True) == "image"  # pyright: ignore[reportArgumentType]
    assert attempts == [(False, ()), (True, ()), (True, ("libldap2-dev",)), (True, ("libldap2-dev", "libsasl2-dev"))]
    assert "build-essential a &&" in prov.python_dockerfile(stack, system_build_tools=True, headers=("a",))


def test_an_unknown_header_is_named_rather_than_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from unbidden.observe.stack import PythonStack
    from unbidden.sandbox import provision as prov

    errors = ["No such file or directory: 'gcc'", "fatal error: frobnicate.h: No such file or directory"]

    def fake(*_: object, **__: object) -> str:
        raise prov.ProvisionError(errors.pop(0) if errors else "unreachable")

    monkeypatch.setattr(prov, "_provision", fake)
    stack = PythonStack(
        version="3.12", lockfile="uv.lock", manifest="pyproject.toml", ruff=True, pyright=False, pytest=True
    )
    with pytest.raises(prov.ProvisionError, match=r"does not know a Debian package for: frobnicate\.h"):
        prov.provision(tmp_path, "HEAD", stack, system_build_tools=True)


def test_the_python_version_comes_from_requires_python_when_no_file_pins_it() -> None:
    from unbidden.observe.stack import requires_python

    assert requires_python('[project]\nrequires-python = ">=3.14,<3.15"\n') == "3.14"
    assert requires_python('[project]\nrequires-python = "~=3.11.2"\n') == "3.11"
    assert requires_python('[project]\nname = "x"\n') is None
    assert requires_python("not toml [") is None


def test_mypy_findings_come_from_its_json_lines_and_a_silent_failure_is_not_a_clean_run() -> None:
    from unbidden.contracts.finding import Completeness
    from unbidden.sandbox.runner import SandboxResult
    from unbidden.sandbox.tools import parse_mypy

    out = "\n".join(
        [
            '{"file": "mealie/a.py", "line": 7, "column": 4, "message": "Incompatible types", "code": "assignment",'
            ' "severity": "error"}',
            '{"file": "mealie/a.py", "line": 7, "message": "See docs", "code": null, "severity": "note"}',
        ]
    )
    report = parse_mypy(SandboxResult(1, out, "", False, 1.0, False, False), ["mypy"])
    assert [(f.path, f.line, f.rule) for f in report.findings] == [("mealie/a.py", 7, "assignment")]
    assert report.completeness is Completeness.COMPLETE
    broken = parse_mypy(SandboxResult(1, "", "error: plugin not found", False, 1.0, False, False), ["mypy"])
    assert broken.completeness is not Completeness.COMPLETE and not broken.findings
    # marshmallow under Python 3.14: exit 1 with --output json and nothing but a note; plain mypy said "Success".
    note = (
        '{"file": "src/m/validate.py", "line": 102, "message": "By default...", "code": "annotation-unchecked", '
        '"severity": "note"}'
    )
    clean = parse_mypy(SandboxResult(1, note, "", False, 1.0, False, False), ["mypy"])
    assert clean.completeness is Completeness.COMPLETE and not clean.findings


def test_mypy_checks_what_its_config_names_else_the_project_package() -> None:
    from unbidden.observe.stack import mypy_targets

    files = {"mealie/__init__.py", "tests/test_x.py"}
    assert mypy_targets('[project]\nname = "mealie"\n[tool.mypy]\nfiles = ["x"]\n', files, ()) == ()
    assert mypy_targets('[project]\nname = "mealie"\n[tool.mypy]\nstrict = true\n', files, ()) == ("mealie",)
    assert mypy_targets('[project]\nname = "other"\n', files, ("pkg",)) == ("pkg",)
    assert mypy_targets('[project]\nname = "other"\n', files, ()) == (".",)


def test_go_vet_and_go_test_output_are_read() -> None:
    from unbidden.languages.golang import go_test_failures, parse_go_vet
    from unbidden.sandbox.runner import SandboxResult

    vet = (
        '# example.com/x/report\n{\n\t"example.com/x/report": {\n\t\t"printf": [\n\t\t\t{\n'
        '\t\t\t\t"posn": "/work/report/report.go:6:2",\n'
        '\t\t\t\t"message": "fmt.Printf format %d has arg of wrong type"\n'
        "\t\t\t}\n\t\t]\n\t}\n}\n"
    )
    report = parse_go_vet(SandboxResult(0, "", vet, False, 1.0, False, False), ["go", "vet"])
    assert [(f.rule, f.path, f.line, f.category) for f in report.findings] == [
        ("printf", "report/report.go", 6, "bugs")
    ]
    broken = "# example.com/x\nvet: ./calc.go:4:9: undefined: missing\n"
    report = parse_go_vet(SandboxResult(1, "", broken, False, 1.0, False, False), ["go", "vet"])
    assert [(f.rule, f.path, f.line) for f in report.findings] == [("compile", "calc.go", 4)]
    events = "\n".join(
        [
            '{"Action":"run","Package":"x","Test":"TestA"}',
            '{"Action":"fail","Package":"x","Test":"TestA"}',
            '{"Action":"fail","Package":"x"}',
            '{"Action":"fail","Package":"x/report"}',
        ]
    )
    assert go_test_failures(events) == ["x/TestA", "x/report (package)"]
    assert go_test_failures("go: cannot find main module") is None


def test_go_test_counts_the_tests_it_ran() -> None:
    from unbidden.languages.golang import go_test_count

    out = (
        '{"Action":"run","Package":"x","Test":"TestA"}\n{"Action":"run","Package":"x","Test":"TestA/sub"}\n'
        '{"Action":"output","Package":"x"}\n'
    )
    assert go_test_count(out) == 2 and go_test_count("") == 0
