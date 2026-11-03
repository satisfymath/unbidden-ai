"""Known vulnerabilities in the packages a Python project installs (campaign 13, WS5: security and dependencies).

What is installed is read inside the sandbox from the dependency image (the distributions in `/deps/.venv`, never by
running the project's code); each name and version is then looked up in PyPI's JSON API, whose `vulnerabilities`
list comes from the Python advisory database and OSV. PyPI is already the registry the mandate lets the image fetch
from; without it in `egress.package_registries` nothing is looked up. Each vulnerable package is one finding per
advisory, grouped into one opportunity per package (category `security`), with the lowest version that fixes every
advisory, which is what the dependency lab bumps to (`lab/deps.py`).
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from unbidden.contracts.finding import AnalyzerReport, Completeness, Finding
from unbidden.sandbox.provision import DependencyImage, link_dependencies, sandbox_spec
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot

TOOL = "pypi-advisories"
HOST = "pypi.org"
LIST_INSTALLED = (
    "import importlib.metadata as m, json; "
    "print(json.dumps(sorted({(d.metadata['Name'] or '', d.version) for d in m.distributions()})))"
)
Fetch = Callable[[str, str], list[dict[str, Any]] | None]


def installed(runner: SandboxRunner, repo: Path, rev: str, image: DependencyImage) -> list[tuple[str, str]] | None:
    """(name, version) of every distribution in the project's environment, read offline; None when unreadable."""
    work = snapshot(repo, rev)
    try:
        link_dependencies(work, image)
        result = runner.run(sandbox_spec(image, ["/deps/.venv/bin/python", "-c", LIST_INSTALLED], timeout_s=120), work)
    finally:
        discard(work)
    try:
        rows = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return [(str(n), str(v)) for n, v in rows if n]


def pypi_vulnerabilities(name: str, version: str) -> list[dict[str, Any]] | None:
    """PyPI's advisories for one release; None when PyPI did not answer."""
    url = f"https://{HOST}/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # a fixed https host
            data = json.loads(response.read())
    except Exception:  # a failed lookup is incomplete, never safe
        return None
    return [v for v in data.get("vulnerabilities") or [] if not v.get("withdrawn")]


def _version_key(version: str) -> tuple[int | str, ...]:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\-+]", version))


def lowest_fix(advisories: list[dict[str, Any]], current: str) -> str | None:
    """The lowest version that fixes every advisory (each advisory's smallest fix above `current`); None when one
    has no fix."""
    needed: list[str] = []
    for advisory in advisories:
        fixes = sorted((f for f in advisory.get("fixed_in") or [] if _version_key(f) > _version_key(current)),
                       key=_version_key)  # fmt: skip
        if not fixes:
            return None
        needed.append(fixes[0])
    return max(needed, key=_version_key) if needed else None


def advisory_report(
    packages: list[tuple[str, str]], manifest: str, fetch: Fetch = pypi_vulnerabilities
) -> AnalyzerReport:
    findings: list[Finding] = []
    unanswered = 0
    for name, version in packages:
        advisories = fetch(name, version)
        if advisories is None:
            unanswered += 1
            continue
        if not advisories:
            continue
        fix = lowest_fix(advisories, version)
        for advisory in advisories:
            ident = str(advisory.get("id") or "advisory")
            aliases = [a for a in advisory.get("aliases") or [] if a != ident]
            findings.append(
                Finding.build(
                    tool=TOOL,
                    rule=name.lower(),
                    severity="error",
                    category="security",
                    path=manifest,
                    message=f"{name} {version}: {ident}"
                    + (f" ({', '.join(aliases[:2])})" if aliases else "")
                    + (f"; fixed in {', '.join(advisory.get('fixed_in') or [])}" if advisory.get("fixed_in") else "")
                    + f": {str(advisory.get('summary') or advisory.get('details') or '')[:200]}",
                    extra={
                        "package": name,
                        "version": version,
                        "advisory": ident,
                        "aliases": aliases,
                        "fixed_in": advisory.get("fixed_in") or [],
                        "lowest_fix": fix,
                        "link": advisory.get("link"),
                    },
                )
            )
    completeness = Completeness.COMPLETE if unanswered == 0 else Completeness.PARTIAL
    error = f"PyPI did not answer for {unanswered} of {len(packages)} package(s)" if unanswered else None
    return AnalyzerReport(tool=TOOL, argv=[f"https://{HOST}/pypi/<name>/<version>/json"], exit_code=0,
                          findings=findings, completeness=completeness, error=error)  # fmt: skip


def manifest_of(stack: Any) -> str:
    """Where a bump would be written: the lock file when there is one, otherwise the manifest."""
    return str(getattr(stack, "lockfile", None) or getattr(stack, "manifest", "pyproject.toml"))
