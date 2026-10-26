"""How the repository's own CI runs its tests, read from its GitHub Actions workflows.

Unbidden judges a change with the repository's checks run the way its team runs them: same working
directories, same setup scripts, same services. Steps that install tools, talk to Docker or publish reports
are dropped; the sandbox provides dependencies and services itself.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_SKIP = re.compile(
    r"(?ix)\b(docker|compose|pip\s+install|uv\s+sync|uv\s+pip|poetry\s+install|npm\s+(ci|install)|pnpm\s+install"
    r"|yarn\s+install|apt-get|brew|curl|wget|codecov|coverage\s+report|coverage\s+html|smokeshow|git\s+)"
)
_COMPOSE_UP = re.compile(r"compose\s+up\b(?P<args>[^\n]*)")
_EXPR = re.compile(r"\$\{\{[^}]*\}\}")
_RUNNERS = re.compile(r"^(?:uv\s+run|poetry\s+run|pipenv\s+run|pdm\s+run)\s+(?:--[\w-]+\s+)*")


@dataclass(frozen=True)
class CiStep:
    cwd: str  # relative to the repository root
    command: str


@dataclass(frozen=True)
class CiPlan:
    workflow: str
    job: str
    steps: tuple[CiStep, ...]
    services: tuple[str, ...]  # compose services the job starts before testing

    def script(self) -> str:
        lines = ["set -e"]
        for step in self.steps:
            target = "/work" if step.cwd in ("", ".") else f"/work/{step.cwd}"
            lines.append(f"cd {target}")
            lines.append(step.command)
        return "\n".join(lines)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def _clean(command: str) -> str | None:
    kept: list[str] = []
    for line in _EXPR.sub("", command).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or _SKIP.search(line):
            continue
        kept.append(_RUNNERS.sub("", line))
    return "\n".join(kept) or None


def _job_plan(workflow: str, job_name: str, job: dict[str, Any], language: str) -> CiPlan | None:
    defaults = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
    steps: list[CiStep] = []
    services: list[str] = []
    for step in job.get("steps") or []:
        run = step.get("run") if isinstance(step, dict) else None
        if not isinstance(run, str):
            continue
        for match in _COMPOSE_UP.finditer(run):
            services += [a for a in match.group("args").split() if not a.startswith("-")]
        command = _clean(run)
        if command is not None:
            steps.append(CiStep(cwd=str(step.get("working-directory") or defaults), command=command))
    text = " ".join(s.command for s in steps)
    runs_tests = "pytest" in text or "test" in text if language == "python" else re.search(r"\btest\b", text)
    if not steps or not runs_tests:
        return None
    return CiPlan(workflow=workflow, job=job_name, steps=tuple(steps), services=tuple(dict.fromkeys(services)))


def ci_test_plan(repo: Path, rev: str, language: str) -> CiPlan | None:
    """The first workflow job that tests `language` code, as a plan the sandbox can run offline."""
    names = [
        n
        for n in _git(repo, "ls-tree", "--name-only", f"{rev}:.github/workflows").split()
        if n.endswith((".yml", ".yaml"))
    ]
    names.sort(key=lambda n: (0 if "test" in n else 1, n))
    for name in names:
        try:
            workflow = yaml.safe_load(_git(repo, "show", f"{rev}:.github/workflows/{name}")) or {}
        except yaml.YAMLError:
            continue
        for job_name, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict) or "test" not in f"{name} {job_name}".lower():
                continue
            hint = " ".join(
                str(s.get("run", "")) + str(s.get("uses", "")) for s in job.get("steps") or [] if isinstance(s, dict)
            )
            if language == "python" and not re.search(r"python|pytest|uv |poetry", hint):
                continue
            if language == "node" and not re.search(r"node|npm|pnpm|yarn|bun", hint):
                continue
            plan = _job_plan(name, str(job_name), job, language)
            if plan is not None:
                return plan
    return None
