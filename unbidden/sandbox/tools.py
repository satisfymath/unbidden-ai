"""The trusted tool table: fixed command lines and parsers. Findings come only from tools listed here."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from unbidden.contracts.finding import AnalyzerReport, Completeness, Finding, Severity
from unbidden.sandbox.runner import SandboxResult

Parser = Callable[[SandboxResult, list[str]], AnalyzerReport]
MISSING_MODULE_RULES = frozenset({"TS2305", "TS2307", "TS2792"})  # no exported member, cannot find module
MAX_FINDINGS = 2000


@dataclass(frozen=True)
class Tool:
    name: str
    language: str
    category: str
    argv: tuple[str, ...]
    parse: Parser
    fix_argv: tuple[str, ...] | None = None  # the tool's own correction, tried before any model is asked
    cwd: str = "."  # a workspace package's directory; findings are reported relative to the repository

    def in_package(self, path: str, argv: tuple[str, ...] | None = None) -> Tool:
        return replace(self, name=f"{self.name}:{path}", cwd=path, argv=argv or self.argv)

    def _repo_path(self, path: str) -> str:
        if self.cwd in (".", "") or path.startswith(f"{self.cwd}/"):
            return path
        return f"{self.cwd}/{path}"

    def report(self, result: SandboxResult, argv: list[str]) -> AnalyzerReport:
        """Parse, then label every finding with this tool's own name and category."""
        report = self.parse(result, argv)
        findings = [
            Finding.build(
                tool=self.name,
                rule=f.rule,
                severity=f.severity,
                category=self.category,
                path=self._repo_path(f.path),
                message=f.message,
                line=f.line,
                extra=f.extra,
            )
            if f.category != "config"
            else f.model_copy(update={"tool": self.name})
            for f in report.findings
        ]
        return report.model_copy(update={"tool": self.name, "findings": findings})


def _report(tool: str, result: SandboxResult, argv: list[str], findings: list[Finding], parsed: bool) -> AnalyzerReport:
    if result.timed_out:
        completeness, error = Completeness.TRUNCATED, "timed out"
    elif result.stdout_truncated or result.stderr_truncated:
        completeness, error = Completeness.TRUNCATED, "output exceeded the capture cap"
    elif not parsed:
        text = (result.stderr or result.stdout).strip()
        # The message is at the start, the stack at the end: keep both.
        error = (text if len(text) <= 900 else f"{text[:500]}\n...\n{text[-400:]}") or "unparseable"
        completeness = Completeness.FAILED
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
                    tool="tsc",
                    rule=match["rule"],
                    severity=sev,
                    category="types",
                    path=_rel(match["path"]),
                    line=int(match["line"]),
                    message=match["msg"].strip(),
                )
            )
    # tsc exits 0 when clean and 1 or 2 with diagnostics; anything else, or errors we could not parse, is a failure.
    parsed = result.exit_code == 0 or bool(findings)
    missing = [f for f in findings if f.rule in MISSING_MODULE_RULES]
    if len(missing) >= 20 or (findings and len(missing) / len(findings) >= 0.15):
        # A flood of missing modules or exports means the environment lacks generated or installed code (an
        # ungenerated ORM client, say): the code's real errors cannot be told apart, so this run says nothing.
        rules = ", ".join(sorted({f.rule for f in missing}))
        report = _report("tsc", result, argv, [], parsed=False)
        return report.model_copy(update={"error": f"environment: {len(missing)} missing modules or exports ({rules})"})
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
                    tool="eslint",
                    rule=rule,
                    severity="error" if msg.get("severity") == 2 else "warning",
                    # A parse error means the tool's configuration is broken, not that the code is: not ours to fix.
                    category="config" if rule == "parse-error" else "lint",
                    path=_rel(entry.get("filePath", "")),
                    line=msg.get("line"),
                    message=str(msg.get("message", "")),
                    extra={"fixable": bool(msg.get("fix"))},
                )
            )
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
                tool="biome",
                rule=category,
                severity="error" if diag.get("severity") == "error" else "warning",
                category="format" if category.startswith("format") else "lint",
                path=_rel(str(file or "")),
                message=str(diag.get("description") or diag.get("message") or category),
            )
        )
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
            tool="ruff",
            rule=str(item.get("code") or "syntax"),
            severity="error",
            category="lint",
            path=_rel(str(item.get("filename", ""))),
            line=(item.get("location") or {}).get("row"),
            message=str(item.get("message", "")),
            extra={"fixable": item.get("fix") is not None},
        )
        for item in items
    ]
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
            tool="pyright",
            rule=str(d.get("rule") or "general"),
            severity="error" if d.get("severity") == "error" else "warning",
            category="types",
            path=_rel(str(d.get("file", ""))),
            line=((d.get("range") or {}).get("start") or {}).get("line", 0) + 1,
            message=str(d.get("message", "")).splitlines()[0],
        )
        for d in diagnostics
        if d.get("severity") in ("error", "warning")
    ]
    return _report("pyright", result, argv, findings, parsed=True)


# mypy ------------------------------------------------------------------------------------------------


def parse_mypy(result: SandboxResult, argv: list[str]) -> AnalyzerReport:
    """mypy's `--output json`: one object per line. A run with errors exits 1; anything else unparsed is a failure."""
    findings: list[Finding] = []
    parsed = result.exit_code in (0, 1)
    for line in (result.stdout or "").splitlines():
        try:
            d: dict[str, Any] = json.loads(line)
        except ValueError:
            continue
        if d.get("severity") != "error":
            continue
        findings.append(
            Finding.build(
                tool="mypy",
                rule=str(d.get("code") or "general"),
                severity="error",
                category="types",
                path=_rel(str(d.get("file", ""))),
                line=int(d.get("line") or 0),
                message=str(d.get("message", "")).splitlines()[0],
            )
        )
    if result.exit_code == 1 and not findings:
        parsed = False  # it failed without reporting a type error: configuration, plugin or import trouble
    return _report("mypy", result, argv, findings, parsed=parsed)


# Rules that find bugs, not style: syntax errors, undefined names, shadowed definitions, broken comparisons,
# mutable default arguments. Run with Unbidden's own pinned ruff, ignoring the repository's configuration.
BASELINE_RUFF_RULES = "E9,F63,F7,F82,F811,B006"

# ESLint's JSON repeats each file's whole source; a fixed filter drops it so large projects fit the capture.
_ESLINT_SLIM = (
    'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const r=JSON.parse(s);'
    "for(const f of r){delete f.source;delete f.output}process.stdout.write(JSON.stringify(r))})"
)
ESLINT_ARGV = ("sh", "-c", f"eslint . --format json --no-error-on-unmatched-pattern | node -e '{_ESLINT_SLIM}'")

TOOLS: dict[str, Tool] = {
    "tsc": Tool("tsc", "node", "types", ("tsc", "--noEmit", "--pretty", "false"), parse_tsc),
    "eslint": Tool(
        "eslint",
        "node",
        "lint",
        ESLINT_ARGV,
        parse_eslint,
        fix_argv=("eslint", ".", "--fix"),
    ),
    "biome": Tool(
        "biome",
        "node",
        "lint",
        ("biome", "check", "--reporter=json", "--max-diagnostics=none", "."),
        parse_biome,
        fix_argv=("biome", "check", "--write", "."),
    ),
    "ruff": Tool(
        "ruff",
        "python",
        "lint",
        ("ruff", "check", "--output-format", "json", "--no-cache", "--exit-zero", "."),
        parse_ruff,
        fix_argv=("ruff", "check", "--fix", "--no-cache", "."),
    ),
    "ruff-baseline": Tool(
        "ruff-baseline",
        "python",
        "bugs",
        (
            "/opt/tools/bin/ruff",
            "check",
            "--isolated",
            "--select",
            BASELINE_RUFF_RULES,
            "--output-format",
            "json",
            "--no-cache",
            "--exit-zero",
            ".",
        ),
        parse_ruff,
    ),
    "pyright": Tool(
        "pyright",
        "python",
        "types",
        ("pyright", "--outputjson", "--pythonpath", "/deps/.venv/bin/python"),
        parse_pyright,
    ),
    # The repository's own mypy, from its environment: its configuration may load plugins installed there.
    "mypy": Tool(
        "mypy",
        "python",
        "types",
        ("/deps/.venv/bin/python", "-m", "mypy", "--output", "json", "--no-error-summary", "--cache-dir", "/tmp/mypy"),
        parse_mypy,
    ),
}


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
        for package in stack.node.packages:
            if package.typescript:
                argv = (*package.typecheck, "--pretty", "false") if package.typecheck else None
                selected.append(TOOLS["tsc"].in_package(package.path, argv))
            if package.eslint:
                selected.append(TOOLS["eslint"].in_package(package.path))
            if package.biome:
                selected.append(TOOLS["biome"].in_package(package.path))
    if stack.python is not None:
        if stack.python.ruff:
            selected.append(TOOLS["ruff"])
        else:
            # A repository that declares no linter still deserves a look for plain bugs.
            selected.append(TOOLS["ruff-baseline"])
        if stack.python.pyright:
            selected.append(TOOLS["pyright"])
        if stack.python.mypy is not None:
            mypy = TOOLS["mypy"]
            selected.append(replace(mypy, argv=(*mypy.argv, *stack.python.mypy)))
    return selected


def tool_named(stack: Any, name: str) -> Tool:
    """The tool an opportunity came from, including a workspace package's (`tsc:apps/web`)."""
    for tool in tools_for(stack):
        if tool.name == name:
            return tool
    return TOOLS[name]
