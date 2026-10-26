"""The trusted tool table: fixed command lines and parsers. Findings come only from tools listed here."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from unbidden.contracts.finding import AnalyzerReport, Completeness, Finding, Severity
from unbidden.sandbox.runner import SandboxResult

Parser = Callable[[SandboxResult, list[str]], AnalyzerReport]
MAX_FINDINGS = 2000


@dataclass(frozen=True)
class Tool:
    name: str
    language: str
    category: str
    argv: tuple[str, ...]
    parse: Parser
    fix_argv: tuple[str, ...] | None = None  # the tool's own correction, tried before any model is asked


def _report(tool: str, result: SandboxResult, argv: list[str], findings: list[Finding], parsed: bool) -> AnalyzerReport:
    if result.timed_out:
        completeness, error = Completeness.TRUNCATED, "timed out"
    elif result.stdout_truncated or result.stderr_truncated:
        completeness, error = Completeness.TRUNCATED, "output exceeded the capture cap"
    elif not parsed:
        completeness, error = Completeness.FAILED, (result.stderr or result.stdout).strip()[-500:] or "unparseable"
    else:
        completeness, error = Completeness.COMPLETE, None
    dropped = max(0, len(findings) - MAX_FINDINGS)
    if dropped:
        completeness = Completeness.PARTIAL
    return AnalyzerReport(
        tool=tool,
        argv=argv,
        exit_code=result.exit_code,
        findings=findings[:MAX_FINDINGS],
        completeness=completeness,
        dropped=dropped,
        error=error,
    )


def _rel(path: str) -> str:
    return path.removeprefix("/work/").removeprefix("./")


# tsc ---------------------------------------------------------------------------------------------------

_TSC = re.compile(
    r"^(?P<path>[^\s(][^(]*)\((?P<line>\d+),(?P<col>\d+)\): (?P<sev>error|warning) (?P<rule>TS\d+): (?P<msg>.*)$"
)


def parse_tsc(result: SandboxResult, argv: list[str]) -> AnalyzerReport:
    findings: list[Finding] = []
    for line in result.stdout.splitlines():
        match = _TSC.match(line)
        if match:
            sev: Severity = "error" if match["sev"] == "error" else "warning"
            findings.append(
                Finding.build(
                    tool="tsc", rule=match["rule"], severity=sev, category="types",
                    path=_rel(match["path"]), line=int(match["line"]), message=match["msg"].strip(),
                )
            )  # fmt: skip
    # tsc exits 0 when clean and 1 or 2 with diagnostics; anything else, or errors we could not parse, is a failure.
    parsed = result.exit_code == 0 or bool(findings)
    return _report("tsc", result, argv, findings, parsed)


# eslint ------------------------------------------------------------------------------------------------


def parse_eslint(result: SandboxResult, argv: list[str]) -> AnalyzerReport:
    try:
        files: list[dict[str, Any]] = json.loads(result.stdout or "null")
        if not isinstance(files, list):
            raise ValueError("not a list")
    except ValueError:
        return _report("eslint", result, argv, [], parsed=False)
    findings: list[Finding] = []
    for entry in files:
        for msg in entry.get("messages", []):
            rule = "parse-error" if msg.get("fatal") else msg.get("ruleId") or "unknown"
            findings.append(
                Finding.build(
                    tool="eslint", rule=rule, severity="error" if msg.get("severity") == 2 else "warning",
                    category="lint", path=_rel(entry.get("filePath", "")), line=msg.get("line"),
                    message=str(msg.get("message", "")), extra={"fixable": bool(msg.get("fix"))},
                )
            )  # fmt: skip
    return _report("eslint", result, argv, findings, parsed=True)


# biome -------------------------------------------------------------------------------------------------


def parse_biome(result: SandboxResult, argv: list[str]) -> AnalyzerReport:
    try:
        data: dict[str, Any] = json.loads(result.stdout or "null")
        diagnostics: list[dict[str, Any]] = data["diagnostics"]
    except (ValueError, KeyError, TypeError):
        return _report("biome", result, argv, [], parsed=False)
    findings: list[Finding] = []
    for diag in diagnostics:
        location = diag.get("location") or {}
        path = location.get("path") or {}
        file = path.get("file") if isinstance(path, dict) else path
        category = str(diag.get("category", "unknown"))
        findings.append(
            Finding.build(
                tool="biome", rule=category, severity="error" if diag.get("severity") == "error" else "warning",
                category="format" if category.startswith("format") else "lint", path=_rel(str(file or "")),
                message=str(diag.get("description") or diag.get("message") or category),
            )
        )  # fmt: skip
    return _report("biome", result, argv, findings, parsed=True)


# ruff --------------------------------------------------------------------------------------------------


def parse_ruff(result: SandboxResult, argv: list[str]) -> AnalyzerReport:
    try:
        items: list[dict[str, Any]] = json.loads(result.stdout or "null")
        if not isinstance(items, list):
            raise ValueError("not a list")
    except ValueError:
        return _report("ruff", result, argv, [], parsed=False)
    findings = [
        Finding.build(
            tool="ruff", rule=str(item.get("code") or "syntax"), severity="error", category="lint",
            path=_rel(str(item.get("filename", ""))), line=(item.get("location") or {}).get("row"),
            message=str(item.get("message", "")), extra={"fixable": item.get("fix") is not None},
        )
        for item in items
    ]  # fmt: skip
    return _report("ruff", result, argv, findings, parsed=True)


# pyright -----------------------------------------------------------------------------------------------


def parse_pyright(result: SandboxResult, argv: list[str]) -> AnalyzerReport:
    try:
        data: dict[str, Any] = json.loads(result.stdout or "null")
        diagnostics: list[dict[str, Any]] = data["generalDiagnostics"]
    except (ValueError, KeyError, TypeError):
        return _report("pyright", result, argv, [], parsed=False)
    findings = [
        Finding.build(
            tool="pyright", rule=str(d.get("rule") or "general"),
            severity="error" if d.get("severity") == "error" else "warning", category="types",
            path=_rel(str(d.get("file", ""))), line=((d.get("range") or {}).get("start") or {}).get("line", 0) + 1,
            message=str(d.get("message", "")).splitlines()[0],
        )
        for d in diagnostics
        if d.get("severity") in ("error", "warning")
    ]  # fmt: skip
    return _report("pyright", result, argv, findings, parsed=True)


TOOLS: dict[str, Tool] = {
    "tsc": Tool("tsc", "node", "types", ("tsc", "--noEmit", "--pretty", "false"), parse_tsc),
    "eslint": Tool(
        "eslint", "node", "lint", ("eslint", ".", "--format", "json", "--no-error-on-unmatched-pattern"),
        parse_eslint, fix_argv=("eslint", ".", "--fix"),
    ),
    "biome": Tool(
        "biome", "node", "lint", ("biome", "check", "--reporter=json", "--max-diagnostics=none", "."),
        parse_biome, fix_argv=("biome", "check", "--write", "."),
    ),
    "ruff": Tool(
        "ruff", "python", "lint", ("ruff", "check", "--output-format", "json", "--no-cache", "--exit-zero", "."),
        parse_ruff, fix_argv=("ruff", "check", "--fix", "--no-cache", "."),
    ),
    "pyright": Tool(
        "pyright", "python", "types", ("pyright", "--outputjson", "--pythonpath", "/deps/.venv/bin/python"),
        parse_pyright,
    ),
}  # fmt: skip


def tools_for(stack: Any) -> list[Tool]:
    """The tools a detected stack can run: only those the repository itself uses."""
    selected: list[Tool] = []
    if stack.node is not None:
        if stack.node.typescript:
            selected.append(TOOLS["tsc"])
        if stack.node.eslint:
            selected.append(TOOLS["eslint"])
        if stack.node.biome:
            selected.append(TOOLS["biome"])
    if stack.python is not None:
        if stack.python.ruff:
            selected.append(TOOLS["ruff"])
        if stack.python.pyright:
            selected.append(TOOLS["pyright"])
    return selected
