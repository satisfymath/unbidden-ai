"""How the repository's own CI runs its tests, read from its GitHub Actions workflows.

Unbidden judges a change with the repository's checks run the way its team runs them: same working
directories, same setup scripts, same services. Steps that install tools, talk to Docker or publish reports
are dropped; the sandbox provides dependencies and services itself.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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
            # `tox -e ${{ matrix.tox }}` runs whatever the matrix names: its values are part of what the job runs.
            matrix = ((job.get("strategy") or {}).get("matrix") or {}) if isinstance(job, dict) else {}
            if isinstance(matrix, dict):
                runs.append(yaml.safe_dump(matrix, default_flow_style=True))
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
    if re.search(r"\btox\b", text):
        called |= {"tox.ini", "setup.cfg", "pyproject.toml"} & tracked  # where tox's environments are defined
    if re.search(r"\bnox\b", text):
        called |= {"noxfile.py"} & tracked
    extra = [_git(repo, "show", f"{rev}:{path}")[:20000] for path in sorted(called)]
    scripts = package_scripts_run(repo, rev, "\n".join([text, *extra]))
    return "\n".join([text, *extra, *scripts]).lower()


_PACKAGE_SCRIPT_CALL = re.compile(
    r"\b(?:(?:pnpm|yarn|bun)(?:\s+-\S+)*(?:\s+run)?|npm(?:\s+-\S+)*\s+run(?:-script)?)\s+([@\w:.-]+)"
    r"|\bnpm\s+(test|start)\b"
)


def package_scripts_run(repo: Path, rev: str, text: str, depth: int = 3) -> list[str]:
    """The package.json scripts a CI's commands call (`pnpm check`, `npm run lint`, `yarn test`), and the scripts those
    call in turn, as their command lines: `pnpm check` that runs `tsc -b` is a CI that runs tsc."""
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:package.json"], capture_output=True, text=True)
    try:
        scripts = json.loads(shown.stdout).get("scripts", {}) if shown.returncode == 0 else {}
    except ValueError:
        return []
    if not isinstance(scripts, dict):
        return []
    found: list[str] = []
    seen: set[str] = set()
    frontier = text
    for _ in range(depth):
        names = {a or b for a, b in _PACKAGE_SCRIPT_CALL.findall(frontier)} - seen
        commands = [str(scripts[n]) for n in sorted(names) if isinstance(scripts.get(n), str)]
        seen |= names
        if not commands:
            break
        found += commands
        frontier = "\n".join(commands)
    return found


UNREADABLE = "unreadable"


MAX_PAGES = 5  # 500 check runs per commit at most; more is a monorepo whose jobs are not all read, said as unknown

# A check run's state, from GitHub's status and conclusion.
SUCCESS, FAILURE, PENDING, SKIPPED, CANCELLED, NEUTRAL, UNKNOWN = (
    "success",
    "failure",
    "pending",
    "skipped",
    "cancelled",
    "neutral",
    "unknown",
)
_FAILED = {"failure", "timed_out", "action_required", "startup_failure"}
# A commit's (or a tool's jobs') verdict: GREEN only when everything that ran succeeded and nothing is still running.
GREEN, RED, PENDING_CI, UNKNOWN_CI = "green", "red", "pending", "unknown"


def run_state(run: dict[str, Any]) -> str:
    if run.get("status") != "completed":
        return PENDING
    conclusion = str(run.get("conclusion"))
    if conclusion in _FAILED:
        return FAILURE
    return {"success": SUCCESS, "skipped": SKIPPED, "cancelled": CANCELLED, "neutral": NEUTRAL}.get(conclusion, UNKNOWN)


def verdict_of(states: list[str]) -> str | None:
    """None without runs; RED on any failure; PENDING while any run is not finished (a partial picture); UNKNOWN
    when a run was cancelled, neutral or of unknown conclusion (it said nothing); GREEN only when at least one run
    succeeded and every other one succeeded or was skipped."""
    if not states:
        return None
    if FAILURE in states:
        return RED
    if PENDING in states:
        return PENDING_CI
    if any(s in (CANCELLED, NEUTRAL, UNKNOWN) for s in states):
        return UNKNOWN_CI
    return GREEN if SUCCESS in states else UNKNOWN_CI


def fetch_runs(
    slug: str, sha: str, token: str | None = None, *, timeout_s: float = 10.0
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Every check run of a commit, finished or not, across pages; or None and why GitHub could not be read.

    "No checks" (an empty list) and "could not ask" (None) are different answers: the Director may act on the first
    and must not on the second."""
    import httpx

    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    runs: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            response = httpx.get(
                f"https://api.github.com/repos/{slug}/commits/{sha}/check-runs",
                params={"per_page": "100", "page": str(page)},
                headers=headers,
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            return None, f"GitHub could not be reached: {type(exc).__name__}"
        if response.status_code != 200:
            why = f"GitHub answered {response.status_code} for {slug}@{sha[:12]}"
            if response.headers.get("x-ratelimit-remaining") == "0":
                why += " (rate limit exhausted" + (", no token was used)" if not token else ")")
            return None, why
        data = response.json()
        batch = data.get("check_runs", [])
        runs += batch
        if len(runs) >= int(data.get("total_count", 0)) or len(batch) < 100:
            return runs, None
    # More runs than were read: what was not read could be anything.
    return [*runs, {"name": "(unread runs)", "status": "completed", "conclusion": "unknown"}], None


def ci_status(slug: str, sha: str, token: str | None = None, *, timeout_s: float = 10.0) -> str | None:
    """The commit's verdict (see verdict_of); None when it has no runs or GitHub cannot be read."""
    runs, _ = fetch_runs(slug, sha, token, timeout_s=timeout_s)
    return verdict_of([run_state(r) for r in runs]) if runs is not None else None


def check_runs(slug: str, sha: str, token: str | None = None, *, timeout_s: float = 10.0) -> dict[str, str]:
    """name -> state of each check run on the commit; empty when GitHub cannot be read."""
    runs, _ = fetch_runs(slug, sha, token, timeout_s=timeout_s)
    return {str(r.get("name")): run_state(r) for r in runs or []}


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
    states = [c for job in jobs for run, c in runs.items() if run == job or run.startswith(f"{job} (")]
    return verdict_of(states)


def ci_verdicts(
    repo: Path, rev: str, slug: str, token: str | None, tools: set[str]
) -> tuple[str | None, dict[str, str], str | None]:
    """The team's CI on this commit: the whole commit's status ('green', 'red', None for no checks, or UNREADABLE),
    per tool the status of the jobs that run it, and why it could not be read. Used by the Director wherever it
    decides, so `unbidden decide` and the autonomous cycle judge alike."""
    runs, problem = fetch_runs(slug, rev, token)
    if not runs and (parent := fork_parent(slug, token)) is not None:
        # A fork runs no checks on the commits it shares with its parent; the parent's CI judged them.
        runs, problem = fetch_runs(parent, rev, token)
    if runs is None:
        return UNREADABLE, {}, problem
    named = {str(r.get("name")): run_state(r) for r in runs}
    per_tool = {t: v for t in sorted(tools) if t and (v := tool_status(repo, rev, t, named)) is not None}
    return verdict_of([run_state(r) for r in runs]), per_tool, None


def analyzer_tool(details: dict[str, object]) -> str:
    """The tool an analyzer finding came from, without the baseline suffix or a scope after the colon."""
    return str(details.get("tool", "")).split(":")[0].removesuffix("-baseline")


def fork_parent(slug: str, token: str | None = None, *, timeout_s: float = 10.0) -> str | None:
    """owner/name of the repository `slug` was forked from, or None (not a fork, or GitHub cannot be read)."""
    import httpx

    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        response = httpx.get(f"https://api.github.com/repos/{slug}", headers=headers, timeout=timeout_s)
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or not response.json().get("fork"):
        return None
    parent = response.json().get("parent") or {}
    return str(parent["full_name"]) if parent.get("full_name") else None


_PY = re.compile(r"\b3\.(\d{1,2})\b")


def _expand_tox(envlist: str) -> list[str]:
    """`py{310,311}`, `py3{10-12}`, `py310`, `py3.12` -> minor versions as "3.N". Anything unreadable is skipped."""

    def minor(item: str, short: bool) -> int | None:
        item = item.strip().removeprefix("3.") if "." in item else item.strip()
        if not item.isdigit():
            return None
        value = (
            int(item) if short or "." in item else int(item[1:]) if item.startswith("3") and len(item) >= 2 else None
        )
        return value if value is not None and 6 <= value <= 30 else None

    out: list[int] = []
    for three, body in re.findall(r"py(3?)\{([^}]*)\}", envlist):
        for item in body.split(","):
            if "-" in item:
                lo, _, hi = item.partition("-")
                a, b = minor(lo, bool(three)), minor(hi, bool(three))
                if a is not None and b is not None and b - a <= 10:
                    out += list(range(a, b + 1))
            elif (m := minor(item, bool(three))) is not None:
                out.append(m)
    out += [int(m) for m in re.findall(r"\bpy3\.?(\d{1,2})\b", envlist)]
    return [f"3.{m}" for m in out]


def ci_python_versions(repo: Path, rev: str) -> list[str]:
    """The Python versions the team's CI runs on: setup-python values and matrices in the workflows, tox's envlist,
    nox sessions and `.python-version`. Read as data; sorted oldest first. Empty when none is named."""
    found: set[str] = set()
    tracked = set(_git(repo, "ls-tree", "-r", "--name-only", rev).split())
    for path in sorted(p for p in tracked if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))):
        text = _git(repo, "show", f"{rev}:{path}")
        for line in text.splitlines():
            if re.search(r"python[-_]version|python:", line, re.IGNORECASE) and "${{" not in line:
                found |= {f"3.{m}" for m in _PY.findall(line)}
        # A matrix list on the lines below its key: `python-version:\n  - "3.10"`.
        for block in re.findall(r"python[-_]version\s*:\s*\n((?:\s+-\s*['\"]?3\.\d+['\"]?\s*\n)+)", text, re.I):
            found |= {f"3.{m}" for m in _PY.findall(block)}
    for path in ("tox.ini", "pyproject.toml", "setup.cfg"):
        if path in tracked:
            text = _git(repo, "show", f"{rev}:{path}")
            for envlist in re.findall(r"env_?list\s*=\s*(.+(?:\n[ \t]+.+)*)", text):
                found |= set(_expand_tox(envlist))
    if "noxfile.py" in tracked:
        text = _git(repo, "show", f"{rev}:noxfile.py")
        for args in re.findall(r"python\s*=\s*\[([^\]]+)\]", text):
            found |= {f"3.{m}" for m in _PY.findall(args)}
    if ".python-version" in tracked:
        found |= {f"3.{m}" for m in _PY.findall(_git(repo, "show", f"{rev}:.python-version"))}
    return sorted(found, key=lambda v: int(v.split(".")[1]))


# Reading a tool's invocations in the CI's commands as argv, not as a substring: `cp tsconfig.json` does not run tsc,
# `tox -e mypy` names an environment, `[tool.mypy]` configures a tool something else may or may not run.
_INVOKERS = {"npx", "pnpm", "yarn", "bunx", "bun", "uv", "uvx", "poetry", "pdm", "hatch", "pipx", "exec", "run", "x",
            "dlx", "=", "commands"}  # fmt: skip
_LINTING = {"ruff": {None: True, "check": True, "format": False}, "biome": {"check": True, "lint": True, "ci": True,
            "format": False}}  # fmt: skip
CONFIG_FLAGS = {"-c", "--config", "--config-file", "-p", "--project", "--rcfile", "--settings-path", "--config-path"}
_VALUE_FLAGS = CONFIG_FLAGS | {"-e", "--env", "-k", "--filter", "--format", "--output-format", "--reporter",
                               "--max-warnings", "--ext", "--target", "-t", "--python-version", "--select", "--ignore",
                               "--extend-select", "--cache-dir", "--outdir", "--out-dir", "-f"}  # fmt: skip
DEFAULT_CONFIGS = {
    "tsc": {"tsconfig.json"},
    "mypy": {"mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg"},
    "ruff": {"ruff.toml", ".ruff.toml", "pyproject.toml"},
    "pyright": {"pyrightconfig.json", "pyproject.toml"},
    "eslint": {"eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", ".eslintrc",
               ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml", ".eslintrc.yaml"},
    "biome": {"biome.json", "biome.jsonc"},
}  # fmt: skip


@dataclass(frozen=True)
class Invocation:
    subcommand: str | None
    paths: tuple[str, ...]  # where it runs, relative to the repository; empty: its whole working directory
    config: str | None  # an explicit configuration file
    cwd: str  # from a preceding `cd <dir> &&`

    def scopes(self) -> list[str]:
        base = self.cwd.strip("./")
        if not self.paths:
            return [base]
        return [str(PurePosixPath(base) / p).strip("./") if base else p for p in self.paths]


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def tool_invocations(commands: str, tool: str) -> list[Invocation]:
    """Every step in the CI's commands that runs `tool` itself, with its subcommand, paths, config and directory."""
    found: list[Invocation] = []
    for line in commands.splitlines():
        cwd = ""
        for segment in re.split(r"&&|\|\||;|\|", line):
            tokens = _tokens(segment)
            if len(tokens) >= 2 and tokens[0] == "cd":
                cwd = tokens[1]
                continue
            for i, token in enumerate(tokens):
                if PurePosixPath(token).name.removesuffix(".exe") != tool:
                    continue
                before = tokens[i - 1] if i else ""
                runs_it = (
                    i == 0
                    or before in _INVOKERS
                    or before.endswith(":")  # a YAML or Makefile-style key
                    or (before == "-m" and i >= 2 and tokens[i - 2].startswith("python"))
                )
                if not runs_it:
                    continue
                rest = tokens[i + 1 :]
                subcommand = (
                    rest[0] if rest and not rest[0].startswith("-") and rest[0] in _LINTING.get(tool, {}) else None
                )
                args = rest[1:] if subcommand else rest
                paths: list[str] = []
                config: str | None = None
                awaiting: str | None = None  # a flag whose value is the next token
                for arg in args:
                    if awaiting is not None:
                        config = arg if awaiting in CONFIG_FLAGS else config
                        awaiting = None
                    elif arg in (">", ">>", "2>", "2>&1"):
                        break
                    elif arg.startswith("-"):
                        flag, eq, value = arg.partition("=")
                        if flag in CONFIG_FLAGS and eq:
                            config = value
                        elif flag in _VALUE_FLAGS and not eq:
                            awaiting = flag
                    elif tool == "tsc" and arg.endswith(".json"):
                        config = arg  # `tsc -b tsconfig.json`: a project file, not a path to check
                    elif arg not in (".", "./") and ("/" in arg or "." in arg or arg.isidentifier()):
                        paths.append(arg.removeprefix("./").rstrip("/"))
                found.append(Invocation(subcommand, tuple(paths), config, cwd))
    return found


def runs_tool(commands: str | None, tool: str) -> bool:
    """Whether the CI's commands run `tool` itself, in a mode that reports what Unbidden's run of it reports."""
    if not commands or not tool:
        return False
    return any(_LINTING.get(tool, {}).get(inv.subcommand, True) for inv in tool_invocations(commands, tool))


SAME, UNRELATED, DIFFERS = "same", "unrelated", "differs"


def environment_equivalence(
    commands: str | None, tool: str, paths: list[str], *, source: str, own_rules: bool
) -> tuple[str, str]:
    """What a green CI run of `tool` says about these findings, and why:
    SAME: the same tool and mode, over these paths, with its default configuration, at the project's own version;
    a finding the CI does not report is then Unbidden's environment. UNRELATED: the CI's run does not cover them
    (another rule set, other files): it says nothing either way. DIFFERS: it covers them differently (another
    version or configuration): a discrepancy to investigate, never a reason to decline."""
    if own_rules:
        return UNRELATED, f"{tool} ran with Unbidden's own rule set, which the team's CI does not run"
    invocations = [i for i in tool_invocations(commands or "", tool) if _LINTING.get(tool, {}).get(i.subcommand, True)]
    if not invocations:
        return UNRELATED, f"no step of the team's CI runs {tool} itself"
    wanted = [p.lower() for p in paths]

    def covers(inv: Invocation) -> bool:
        return all(any(not s or p == s or p.startswith(f"{s}/") for s in inv.scopes()) for p in wanted)

    covering = [i for i in invocations if covers(i)]
    if not covering:
        scopes = sorted({s or "." for i in invocations for s in i.scopes()})
        return UNRELATED, f"the team's CI runs {tool} on {', '.join(scopes)}, not on {paths[0] if paths else 'them'}"
    if source != "project":
        return DIFFERS, f"Unbidden ran its own {tool}, whose version may differ from the CI's"
    defaults = [
        i for i in covering if i.config is None or PurePosixPath(i.config).name in DEFAULT_CONFIGS.get(tool, ())
    ]
    if not defaults:
        return DIFFERS, f"the team's CI runs {tool} with {covering[0].config}, not the configuration Unbidden used"
    return SAME, ""
