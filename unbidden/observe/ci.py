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
    r"(?ix)\b(docker|compose|pip\s+install|uv\s+sync|uv\s+lock|uv\s+pip|poetry\s+install|npm\s+(ci|install)|pnpm\s+install"
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
# Checks the scan already runs, offline and pinned; in a test plan they only add time and network needs.
_CHECK_RUN = re.compile(r"\b(pre-commit|mypy|pyright|semgrep|ruff|flake8|black|isort|pylint|codespell)\b")
# A job that does any of this publishes something: never run as a test plan, whatever else it does.
_PUBLISHES = re.compile(
    r"\bgh\s+(pr|release|issue|api)\b|\bgit\s+push\b|\b(docker|helm)\s+push\b|"
    r"\btwine\s+upload\b|\b(npm|pnpm|yarn)\s+publish\b|\buv\s+publish\b"
)
_TASK_CALL = re.compile(r"^\s*task\s+(?P<name>[\w:.-]+)(?P<rest>.*)$")
TASKFILES = ("Taskfile.yml", "Taskfile.yaml", "taskfile.yml", "taskfile.yaml")


def taskfile_tasks(repo: Path, rev: str) -> dict[str, list[str]]:
    """The commands of each task in the repository's Taskfile (go-task), nested `task:` calls expanded once."""
    for name in TASKFILES:
        text = _git(repo, "show", f"{rev}:{name}")
        if not text:
            continue
        try:
            tasks = (yaml.safe_load(text) or {}).get("tasks") or {}
        except yaml.YAMLError:
            return {}
        raw: dict[str, list[Any]] = {
            str(k): (v.get("cmds") or []) if isinstance(v, dict) else [v] if isinstance(v, str) else []
            for k, v in tasks.items()
        }

        def commands(cmds: list[Any], depth: int = 0, raw: dict[str, list[Any]] = raw) -> list[str]:
            out: list[str] = []
            for cmd in cmds:
                if isinstance(cmd, str):
                    out.append(cmd)
                elif isinstance(cmd, dict) and isinstance(cmd.get("cmd"), str):
                    out.append(str(cmd["cmd"]))
                elif isinstance(cmd, dict) and isinstance(cmd.get("task"), str) and depth < 2:
                    out += commands(raw.get(str(cmd["task"]), []), depth + 1)
            return out

        return {k: commands(v) for k, v in raw.items()}
    return {}


def _expand_tasks(command: str, tasks: dict[str, list[str]]) -> str:
    """`task py:test -- -k x` becomes the task's own commands, its CLI arguments in place of `{{ .CLI_ARGS }}`."""
    lines: list[str] = []
    for line in command.splitlines():
        call = _TASK_CALL.match(line)
        if call is None or call.group("name") not in tasks:
            lines.append(line)
            continue
        args = call.group("rest").partition("--")[2].strip()
        lines += [re.sub(r"\{\{\s*\.CLI_ARGS\s*\}\}", args, c) for c in tasks[call.group("name")]]
    return "\n".join(lines)


def _parses(command: str) -> bool:
    """Whether a cleaned step is still valid shell: dropping lines can leave an empty `if ... then else fi`."""
    return subprocess.run(["bash", "-n"], input=command, capture_output=True, text=True, check=False).returncode == 0


# Jobs that need more than the repository: a browser, a deployed system, another operating system.
_NEEDS_MORE = re.compile(r"e2e|browser|playwright|cypress|integration|smoke|deploy|release|\bwin|windows|macos")


def _job_plan(
    workflow: str, job_name: str, job: dict[str, Any], language: str, tasks: dict[str, list[str]] | None = None
) -> CiPlan | None:
    defaults = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
    steps: list[CiStep] = []
    services: list[str] = []
    runs = [s for s in job.get("steps") or [] if isinstance(s, dict) and isinstance(s.get("run"), str)]
    if any(_PUBLISHES.search(_expand_tasks(str(s["run"]), tasks or {})) for s in runs):
        return None
    for step in runs:
        if step.get("continue-on-error") is True:  # optional by the team's own account (a cache check)
            continue
        run = _expand_tasks(str(step["run"]), tasks or {})
        for match in _COMPOSE_UP.finditer(run):
            services += [a for a in match.group("args").split() if not a.startswith("-")]
        command = _clean(run)
        if command is not None:
            command = "\n".join(line for line in command.splitlines() if not _CHECK_RUN.search(line))
        if command and _parses(command):
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
    tasks = taskfile_tasks(repo, rev)
    for name, job_name, job in jobs:
        hint = " ".join(
            str(s.get("run", "")) + str(s.get("uses", "")) for s in job.get("steps") or [] if isinstance(s, dict)
        )
        hint = _expand_tasks(hint, tasks) if tasks else hint
        if language == "python" and not re.search(r"python|pytest|uv |poetry", hint):
            continue
        if language == "node" and not re.search(r"node|npm|pnpm|yarn|bun", hint):
            continue
        plan = _job_plan(name, job_name, job, language, tasks)
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


def ci_status(slug: str, sha: str, token: str | None = None, *, timeout_s: float = 10.0) -> str | None:
    """'green' when every check run of the commit that finished succeeded (or was skipped), 'red' when one failed,
    None when there are none or GitHub cannot be read. Read-only, one request."""
    import httpx

    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{slug}/commits/{sha}/check-runs",
            params={"per_page": "100"},
            headers=headers,
            timeout=timeout_s,
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    runs = [r for r in response.json().get("check_runs", []) if r.get("status") == "completed"]
    if not runs:
        return None
    conclusions = {str(r.get("conclusion")) for r in runs}
    return "red" if conclusions & {"failure", "timed_out", "action_required"} else "green"


def check_runs(slug: str, sha: str, token: str | None = None, *, timeout_s: float = 10.0) -> dict[str, str]:
    """name -> conclusion of each finished check run on the commit; empty when GitHub cannot be read."""
    import httpx

    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{slug}/commits/{sha}/check-runs",
            params={"per_page": "100"},
            headers=headers,
            timeout=timeout_s,
        )
    except httpx.HTTPError:
        return {}
    if response.status_code != 200:
        return {}
    return {
        str(r.get("name")): str(r.get("conclusion"))
        for r in response.json().get("check_runs", [])
        if r.get("status") == "completed"
    }


def tool_status(repo: Path, rev: str, tool: str, runs: dict[str, str]) -> str | None:
    """'green' when every job whose steps run `tool` (or a script that does) finished successfully on the commit,
    'red' when one failed, None when no such job's run is known. A red check elsewhere does not count."""
    names = [
        n
        for n in _git(repo, "ls-tree", "--name-only", f"{rev}:.github/workflows").split()
        if n.endswith((".yml", ".yaml"))
    ]
    tracked = set(_git(repo, "ls-tree", "-r", "--name-only", rev).split())
    jobs: list[str] = []
    for name in names:
        try:
            workflow = yaml.safe_load(_git(repo, "show", f"{rev}:.github/workflows/{name}")) or {}
        except yaml.YAMLError:
            continue
        for key, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            text = " ".join(str(s.get("run", "")) for s in job.get("steps") or [] if isinstance(s, dict))
            called = {t.lstrip("./") for t in re.findall(r"[\w./-]+\.(?:sh|py|bash)\b", text)} & tracked
            text += " ".join(_git(repo, "show", f"{rev}:{c}")[:20000] for c in sorted(called))
            if tool in text.lower():
                jobs.append(str(job.get("name") or key))
    # A matrix job's runs are named "<job> (<values>)".
    concluded = [c for job in jobs for run, c in runs.items() if run == job or run.startswith(f"{job} (")]
    if not concluded:
        return None
    return "red" if any(c in ("failure", "timed_out", "action_required") for c in concluded) else "green"


def ci_verdicts(
    repo: Path, rev: str, slug: str, token: str | None, tools: set[str]
) -> tuple[str | None, dict[str, str]]:
    """The team's CI on this commit: the whole commit's status, and per tool the status of the jobs that run it.
    Used by the Director wherever it decides, so `unbidden decide` and the autonomous cycle judge alike."""
    status = ci_status(slug, rev, token)
    runs = check_runs(slug, rev, token)
    per_tool = {t: v for t in sorted(tools) if t and (v := tool_status(repo, rev, t, runs)) is not None}
    return status, per_tool


def analyzer_tool(details: dict[str, object]) -> str:
    """The tool an analyzer finding came from, without the baseline suffix or a scope after the colon."""
    return str(details.get("tool", "")).split(":")[0].removesuffix("-baseline")
