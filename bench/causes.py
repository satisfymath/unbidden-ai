"""The root cause of where a repository's run stopped, from its record alone.

Rules are ordered: the first that explains the record wins. They read what Unbidden recorded (stack, problems,
analyzers, the Director's decisions) and the file census, never the repository's name. A record no rule explains is
`unclassified`, read by a person, and either given a cause or used to add a rule.
"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED = {"Python", "TypeScript", "JavaScript"}
# Files that accompany any project (scripts, headers) and say little about what it is written in.
INCIDENTAL = {"Shell", "C"}


def dominant_language(files: dict[str, Any]) -> str | None:
    counts = {k: v for k, v in (files.get("by_language") or {}).items() if k not in INCIDENTAL}
    return max(counts, key=lambda k: counts[k]) if counts else None


MIN_CODE_FILES = 5

# The installer's own words, most specific first.
DEPENDENCY_CAUSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A dependency from a git repository: installing it needs network access the mandate does not grant.
    ("deps_vcs_source", re.compile(r"@ git\+|git\+https?://|git\+ssh://", re.I)),
    ("deps_python_version", re.compile(
        r"does not satisfy Python|requires-python|Python>=\d|python_requires|current Python version|"
        r"supported environments|resolved to Python", re.I)),
    ("deps_tool_version", re.compile(r"Required uv version|required-version|packageManager|corepack", re.I)),
    ("deps_private_or_network", re.compile(
        r"\b40[134]\b|Could not resolve host|ETIMEDOUT|ECONNRESET|unable to access|Authentication failed|"
        r"private registry|git@", re.I)),
    # Building the project's own metadata (a dynamic version, a declared readme), not compiling anything.
    ("deps_project_metadata", re.compile(
        r"prepare_metadata|get_requires_for_build|setuptools-scm|Readme file|ModuleNotFoundError", re.I)),
    ("deps_native_build", re.compile(
        r"fatal error: .*\.h|\bgcc\b|g\+\+|clang|command 'cc'|pg_config|Failed building wheel|Rust compiler|"
        r"\bcargo\b|cmake|node-gyp", re.I)),
    ("deps_stale_lockfile", re.compile(
        r"lockfile .* needs to be updated|lockfile had changes|ERR_PNPM_OUTDATED_LOCKFILE|lockfile is not up to date",
        re.I)),
    ("deps_resolution", re.compile(
        r"No solution found|ResolutionImpossible|ERESOLVE|conflicting|unsatisfiable|Because .* depends on", re.I)),
    ("deps_missing_file", re.compile(r"Couldn't find patch file|Distribution not found at|does not exist", re.I)),
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
    analyzed = any(a["completeness"] == "complete" for a in state.get("analyzers") or [])
    dominant = dominant_language(files)
    if not analyzed and dominant is not None and dominant not in SUPPORTED and files.get("code", 0) >= MIN_CODE_FILES:
        # What could not be analyzed is mostly in a language Unbidden does not read; a few scripts in one it does
        # read do not make it a dependency problem.
        return "unsupported_language"
    if not languages and not analyzed:
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
