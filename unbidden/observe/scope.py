"""Compatibility diagnosis (campaign to v1.0, section 11): what of this repository is inside the scope v1.0
declares, what is outside, and why, read from its files; no image is built and nothing runs."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from unbidden.observe.ci import ci_test_plan
from unbidden.observe.compose import load_compose
from unbidden.observe.stack import detect_stack

Check = tuple[str, bool, str]


def diagnose(repo: Path, rev: str = "HEAD") -> list[Check]:
    """(name, in scope, why) for the stack, the tests, the database and the languages seen."""
    out: list[Check] = []
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", rev], capture_output=True, text=True,
                              check=True).stdout.strip()  # fmt: skip
    except subprocess.CalledProcessError:
        return [("scope", False, "not a git repository with a commit")]
    stack = detect_stack(repo, head)
    py = stack.python
    if py is None:
        others = ", ".join(stack.languages) or "none detected"
        why = f"no Python project at the root (seen: {others}); full cycles are Python only"
        return [("scope: stack", False, why)]
    stack_note = f"Python {py.version} ({py.manifest}"
    stack_note += f", {py.lockfile}" if py.lockfile else ""
    stack_note += f"; workspace members {', '.join(py.members)}" if py.members else ""
    out.append(("scope: stack", True, stack_note + ")"))
    plan = ci_test_plan(repo, head, "python")
    if plan is None:
        out.append(("scope: tests", py.pytest, "no CI job that runs pytest was read; "
                    + ("pytest files found: the default command is used, partially" if py.pytest
                       else "no tests found: experiments cannot be validated")))  # fmt: skip
    else:
        notes = "; ".join(plan.notes[:2])
        out.append(
            ("scope: tests", True, f"{plan.workflow} > {plan.job} ({plan.scope})" + (f"; {notes}" if notes else ""))
        )
    compose = load_compose(repo, head)
    services = [s for s in (compose.services.values() if compose else [])]
    db = [s.name for s in services if s.data_kind]
    images = " ".join(str(s.image or "") for s in services).lower()
    postgres = "postgres" in images or any(re.search(r"postgres|psycopg|asyncpg", f, re.I) for f in [py.manifest])
    if db:
        seen = f"services in compose: {', '.join(db)}"
        seen += "" if postgres else " (PostgreSQL is where performance work is measured; not seen)"
        out.append(("scope: database", True, seen))
    else:
        out.append(("scope: database", False, "no database service declared: consistency and performance work need one "
                    "(the project's checks and robustness probes still run)"))  # fmt: skip
    for language in stack.languages:
        if language != "python":
            out.append((f"scope: {language}", False, "analyzed for findings only; no full cycle in v1.0"))
    return out
