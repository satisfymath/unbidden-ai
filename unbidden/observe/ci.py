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
    # Activating a virtualenv: the dependency image already puts its environment first.
    r"|^\s*(source|\.)\s+\S*(venv|VENV|activate)\S*\s*$"
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


# A Python job tests when it runs a test runner, not when the word "test" appears (`codespell --skip tests`).
_PY_TESTS = re.compile(
    r"\bpytest\b|-m (pytest|unittest)\b|\b(make|tox|nox|hatch run|poetry run|uv run)\s+[\w:-]*test"
    r"|[\w./-]*test[\w-]*\.(sh|py)\b"
)
# Jobs that need more than the repository: a browser, a deployed system, another operating system.
_NEEDS_MORE = re.compile(r"e2e|browser|playwright|cypress|integration|smoke|deploy|release|\bwin|windows|macos")


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
    runs_tests = _PY_TESTS.search(text) if language == "python" else re.search(r"\btest\b", text)
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
    jobs: list[tuple[str, str, dict[str, Any]]] = []
    for name in names:
        try:
            workflow = yaml.safe_load(_git(repo, "show", f"{rev}:.github/workflows/{name}")) or {}
        except yaml.YAMLError:
            continue
        jobs += [(name, str(j), job) for j, job in (workflow.get("jobs") or {}).items() if isinstance(job, dict)]

    # A job is judged by what its steps run, not by its name (rich tests in `pythonpackage.yml`, job `build`); jobs
    # named for tests are tried first.
    def rank(item: tuple[str, str, dict[str, Any]]) -> tuple[int, int, int, str, str]:
        label = f"{item[0]} {item[1]} {item[2].get('runs-on', '')}".lower()
        canonical = item[0].rsplit(".", 1)[0].lower() in ("test", "tests", "ci", "check", "checks")
        return (
            1 if _NEEDS_MORE.search(label) else 0,
            0 if canonical else 1,
            0 if "test" in label else 1,
            item[0],
            item[1],
        )

    jobs.sort(key=rank)
    for name, job_name, job in jobs:
        hint = " ".join(
            str(s.get("run", "")) + str(s.get("uses", "")) for s in job.get("steps") or [] if isinstance(s, dict)
        )
        if language == "python" and not re.search(r"python|pytest|uv |poetry", hint):
            continue
        if language == "node" and not re.search(r"node|npm|pnpm|yarn|bun", hint):
            continue
        plan = _job_plan(name, job_name, job, language)
        if plan is not None:
            return plan
    return None


_LINT_RUN = re.compile(r"\b(lint|eslint|biome|ruff|prettier)\b")
_FILTER = re.compile(r"(?:--filter|-F|--workspace|-w)[ =]+(?P<name>[@\w./-]+)|yarn\s+workspace\s+(?P<yarn>[@\w./-]+)")
_SCRIPT_CALL = re.compile(r"\b(?:pnpm|npm|yarn)\s+(?:run\s+)?(?P<script>[\w:-]+)")


def ci_lint_packages(repo: Path, rev: str, packages: dict[str, str], root_scripts: dict[str, str]) -> set[str] | None:
    """Directories whose code the team's CI lints, from the workflows' own commands.

    `packages` maps workspace package names to directories. A filtered command (`pnpm --filter @app/web lint`)
    names its package; a root script (`pnpm lint`) is expanded once. None means CI does not say: no filtering.
    """
    commands: list[str] = []
    for name in _git(repo, "ls-tree", "--name-only", f"{rev}:.github/workflows").split():
        if not name.endswith((".yml", ".yaml")):
            continue
        try:
            workflow = yaml.safe_load(_git(repo, "show", f"{rev}:.github/workflows/{name}")) or {}
        except yaml.YAMLError:
            continue
        for job in (workflow.get("jobs") or {}).values():
            for step in (job.get("steps") or []) if isinstance(job, dict) else []:
                run = step.get("run") if isinstance(step, dict) else None
                if isinstance(run, str):
                    commands += [ln.strip() for ln in run.splitlines() if _LINT_RUN.search(ln)]
    if not commands:
        return None
    expanded: list[str] = []
    for command in commands:
        call = _SCRIPT_CALL.search(command)
        if call and not _FILTER.search(command) and call.group("script") in root_scripts:
            expanded.append(root_scripts[call.group("script")])  # the root script says what it lints
        else:
            expanded.append(command)
    dirs: set[str] = set()
    for command in expanded:
        filtered = [m.group("name") or m.group("yarn") for m in _FILTER.finditer(command)]
        if not filtered:
            dirs.add(".")  # a lint run over the whole repository
        dirs.update(packages[n] for n in filtered if n in packages)
    return dirs


def ci_commands(repo: Path, rev: str) -> str | None:
    """Everything the repository's workflows run, lowercased; None when it has no workflow Unbidden can read."""
    names = [
        n
        for n in _git(repo, "ls-tree", "--name-only", f"{rev}:.github/workflows").split()
        if n.endswith((".yml", ".yaml"))
    ]
    runs: list[str] = []
    for name in names:
        try:
            workflow = yaml.safe_load(_git(repo, "show", f"{rev}:.github/workflows/{name}")) or {}
        except yaml.YAMLError:
            continue
        for job in (workflow.get("jobs") or {}).values():
            for step in (job.get("steps") or []) if isinstance(job, dict) else []:
                if isinstance(step, dict):
                    runs.append(f"{step.get('run', '')} {step.get('uses', '')}")
    if not runs:
        return None
    text = "\n".join(runs)
    # One level of indirection: what the workflows call is part of what they run (`bash scripts/lint.sh` runs ruff).
    tracked = set(_git(repo, "ls-tree", "-r", "--name-only", rev).split())
    called = {t.lstrip("./") for t in re.findall(r"[\w./-]+\.(?:sh|py|bash)\b", text)} & tracked
    if re.search(r"\bmake\b", text):
        called |= {"Makefile"} & tracked
    if "pre-commit" in text:
        called |= {".pre-commit-config.yaml"} & tracked
    extra = [_git(repo, "show", f"{rev}:{path}")[:20000] for path in sorted(called)]
    return "\n".join([text, *extra]).lower()
