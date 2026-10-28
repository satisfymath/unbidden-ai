"""The root cause of where a repository's run stopped, from its record alone.

Rules are ordered: the first that explains the record wins. They read what Unbidden recorded (stack, problems,
analyzers, the Director's decisions) and the file census, never the repository's name. A record no rule explains is
`unclassified`, read by a person, and either given a cause or used to add a rule.
"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED = {"Python", "TypeScript", "JavaScript"}
MIN_CODE_FILES = 5

# The installer's own words, most specific first.
DEPENDENCY_CAUSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("deps_python_version", re.compile(
        r"does not satisfy Python|requires-python|Python>=\d|python_requires|current Python version", re.I)),
    ("deps_private_or_network", re.compile(
        r"\b40[134]\b|Could not resolve host|ETIMEDOUT|ECONNRESET|unable to access|Authentication failed|"
        r"private registry|git@", re.I)),
    # Building the project's own metadata (a dynamic version, a declared readme), not compiling anything.
    ("deps_project_metadata", re.compile(
        r"prepare_metadata|get_requires_for_build|setuptools-scm|Readme file|ModuleNotFoundError", re.I)),
    ("deps_native_build", re.compile(
        r"fatal error: .*\.h|\bgcc\b|g\+\+|clang|command 'cc'|pg_config|Failed building wheel|Rust compiler|"
        r"\bcargo\b|cmake|node-gyp", re.I)),
    ("deps_resolution", re.compile(
        r"No solution found|ResolutionImpossible|ERESOLVE|conflicting|unsatisfiable|Because .* depends on", re.I)),
)  # fmt: skip


def _dependency_cause(problem: str) -> str:
    for cause, pattern in DEPENDENCY_CAUSES:
        if pattern.search(problem):
            return cause
    return "deps_other"


def root_cause(row: dict[str, Any]) -> str:
    if row["steps"].get("checkout", {}).get("code") != 0:
        return "checkout_failed"
    state = row.get("state") or {}
    files = row.get("files") or {}
    languages = state.get("languages") or []
    if not languages:
        if files and files.get("code", 0) < MIN_CODE_FILES:
            return "not_software"
        present = set((files.get("by_language") or {}).keys())
        if present and not present & SUPPORTED:
            return "unsupported_language"
        if any("is not analyzed" in b for b in state.get("blind_spots") or []) and not present & SUPPORTED:
            return "unsupported_language"
        return "no_dependency_manifest"
    problems = [p for p in state.get("problems") or [] if "failed to build" in p or "not installed" in p]
    analyzers = state.get("analyzers") or []
    if problems and not any(a["completeness"] == "complete" for a in analyzers):
        return _dependency_cause(problems[0])
    if not analyzers:
        return "no_applicable_analyzer"
    if not any(a["completeness"] == "complete" for a in analyzers):
        return "analyzer_failed"
    decided = (row.get("decide") or {}).get("chosen") or {}
    opportunities = state.get("opportunities") or []
    if decided.get("run_experiment") or decided.get("propose_change"):
        return "actionable"
    if opportunities or decided:
        return "findings_declined"
    return "nothing_found"
