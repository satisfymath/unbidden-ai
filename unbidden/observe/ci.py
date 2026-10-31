"""How the repository's own CI runs its tests, read from its GitHub Actions workflows.

Unbidden judges a change with the repository's checks run the way its team runs them: same working
directories, same setup scripts, same services. Steps that install tools, talk to Docker or publish reports
are dropped; the sandbox provides dependencies and services itself.
"""

from __future__ import annotations

import configparser
import functools
import json
import re
import shlex
import subprocess
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

# Commands the sandbox's image stands for, in command position (stage 10: `--exclude-service docker`, a pytest option
# of Prefect's, dropped its test command once continued lines were read whole).
_SKIP = re.compile(
    r"(?ix)(?:^|[;&|(]\s*|\b(?:sudo|then|do)\s+)(?:(?:uv|poetry|pipenv|pdm)\s+run\s+(?:--[\w-]+\s+)*)?(?:python3?\s+-m\s+)?"
    r"(docker|docker-compose|compose|pip3?\s+install|uv\s+sync|uv\s+lock|uv\s+pip|poetry\s+install|npm\s+(ci|install)"
    r"|pnpm\s+install|yarn\s+install|apt-get|brew|curl|wget|codecov|coverage\s+report|coverage\s+html|smokeshow|git)\b"
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
    # The job's own service containers (GitHub Actions `services:`): name, image, environment, container ports.
    containers: tuple[tuple[str, str, tuple[tuple[str, str], ...], tuple[int, ...]], ...] = ()
    env: tuple[tuple[str, str], ...] = ()  # the job's and its test steps' environment, as the team wrote it
    # What the job's `uv sync` installs (its own steps, and the local composite actions it uses); None: no `uv sync`.
    sync_flags: tuple[str, ...] | None = None
    # A job the CI runs as several groups (matrix entries, pytest-split groups): every group's label, which one this
    # plan runs, and what was left out (the group's share of the suite is all the plan claims).
    groups: tuple[str, ...] = ()
    scope: str = "the whole job"
    notes: tuple[str, ...] = ()

    @property
    def partial(self) -> bool:
        return len(self.groups) > 1

    def script(self) -> str:
        # Steps write to the runner's files (`>> "$GITHUB_OUTPUT"`); here they are scratch files, read by nothing.
        lines = ["set -e", "export GITHUB_OUTPUT=/tmp/github_output GITHUB_ENV=/tmp/github_env "
                 "GITHUB_STEP_SUMMARY=/tmp/github_step_summary GITHUB_PATH=/tmp/github_path"]  # fmt: skip
        for step in self.steps:
            target = "/work" if step.cwd in ("", ".") else f"/work/{step.cwd}"
            lines.append(f"cd {target}")
            lines.append(step.command)
        return "\n".join(lines)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def _clean(command: str) -> str | None:
    kept: list[str] = []
    for line in _EXPR.sub("", re.sub(r"\\\n\s*", " ", command)).splitlines():
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


_RUNNER_CALL = re.compile(r"\bpytest\b|-m (pytest|unittest)\b|\bgo test\b|\b(vitest|jest|mocha)\b")
_HTTP_TESTS = re.compile(r"\b(newman|postman)\b", re.I)


_ACTION_COMMAND = re.compile(r"^\s*(?:(?:uv|poetry|pipenv|pdm)\s+run\s+|python3?\s+-m\s+)?pytest\b")


def _as_run(step: dict[str, Any]) -> dict[str, Any]:
    """A step that calls an action whose inputs carry the test command (`pavelzw/pytest-action`'s `custom-pytest:
    uv run pytest tests/unit`) is read as that command (stage 9: LNbits' tests run this way)."""
    if isinstance(step.get("run"), str) or not step.get("uses"):
        return step
    command = next((str(v) for v in (step.get("with") or {}).values() if _ACTION_COMMAND.search(str(v))), None)
    return {**step, "run": command} if command else step


_SETUP_LINE = re.compile(
    r"^\s*(?:sudo\s+)?(?:apt(?:-get)?\s+(?:update|install|upgrade)|brew\s+install|yum\s+install|dnf\s+install|"
    r"apk\s+add|.*>>\s*\"?\$GITHUB_(?:PATH|ENV)\"?|.*\.sh\s+-y)\b.*$"
)


def _system_setup(command: str) -> bool:
    """A step that only installs system packages for the CI's runner (`sudo apt-get install postgresql-client-18`):
    the sandbox's image stands for it, so it is skipped like the runner's other preparation, not run and not held
    against the job."""
    lines = [ln for ln in command.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return bool(lines) and all(_SETUP_LINE.match(ln) for ln in lines)


def _reproducible(runs: list[dict[str, Any]], files: set[str] | None) -> bool:
    """Whether a job's steps can run in the sandbox: none raises privileges (`sudo`), and none works in a directory
    the repository does not have (one it downloads or generates while the job runs). Stage 9: LNbits' JMeter job,
    taken for its tests, ran `sudo update-java-alternatives` and `cd lnbits-extensions`."""
    for step in runs:
        text = "\n".join(ln for ln in str(step["run"]).splitlines() if not _SETUP_LINE.match(ln))
        if re.search(r"(^|[\s;&|])sudo\s", text):
            return False
        # A step that fetches from the network while the job runs (stage 9, Prefect: a compatibility job downloads a
        # schema with `curl https://...`) cannot run where tests have no network.
        if re.search(r"\b(?:curl|wget)\b[^\n]*\bhttps?://|\bgit\s+clone\b", text):
            return False
        if files is not None:
            for target in re.findall(r"(?:^|[\s;&|])cd\s+([\w./-]+)", text):
                target = target.strip("/").removeprefix("./")
                if target in ("", ".", "..", "/work") or target.startswith(("$", "~", "/")):
                    continue
                if not any(f == target or f.startswith(target + "/") for f in files):
                    return False
    return True


_WRITES_ENV = re.compile(
    r"""^\s*echo\s+["']?(?P<key>[A-Za-z_]\w*)=(?P<value>[^"'\n]*?)["']?\s*>>\s*"?\$\{?GITHUB_ENV\}?"?\s*$"""
)
_SPLIT_BOOKKEEPING = re.compile(
    r"\s--(?:durations-path|splitting-algorithm)(?:\s+|=)(?:\"[^\"]*\"|\S+)|\s--(?:store|clean)-durations\b"
)
_SPLITS = re.compile(r"--splits(?:\s+|=)[\"']?(?P<n>\d+)[\"']?\s+--group(?:\s+|=)[\"']?(?P<g>\d+)[\"']?")
_DATA_FILE = re.compile(r"(?<![\w$/.-])(?P<path>[\w./-]+\.(?:json|xml|txt|csv|ya?ml|tar|zip|gz))\b")


def _job_plan(
    workflow: str, job_name: str, job: dict[str, Any], language: str, tasks: dict[str, list[str]] | None = None,
    scripts: dict[str, str] | None = None, files: set[str] | None = None,
) -> CiPlan | None:  # fmt: skip
    defaults = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
    steps: list[CiStep] = []
    services: list[str] = []
    notes: list[str] = []
    all_steps = [s for s in job.get("steps") or [] if isinstance(s, dict)]
    downloads = any(str(s.get("uses", "")).startswith("actions/download-artifact") for s in all_steps)
    runs = [_as_run(s) for s in all_steps]
    # What a step writes to `$GITHUB_ENV` is the environment of the steps after it (stage 10, Prefect: the database
    # URL); kept as environment, and the line itself dropped.
    written: dict[str, str] = {}
    for step in runs:
        if isinstance(step.get("run"), str):
            lines = str(step["run"]).splitlines()
            for line in lines:
                if (m := _WRITES_ENV.match(line)) and "$" not in m.group("value"):
                    written[m.group("key")] = m.group("value")
            step["run"] = "\n".join(ln for ln in lines if not _WRITES_ENV.match(ln))
    runs = [s for s in runs if isinstance(s.get("run"), str) and str(s["run"]).strip()]
    runs = [s for s in runs if not _system_setup(str(s["run"]))]
    if any(_PUBLISHES.search(_expand_tasks(str(s["run"]), tasks or {})) for s in runs):
        return None  # a job that publishes is never a test plan, whatever comes after its tests
    # The job's tests end at its last step that runs the test runner: what follows uploads, validates or reports
    # (stage 10, Prefect: a `jq` check of the durations file was taken for a test step).
    last = max((i for i, s in enumerate(runs) if _RUNNER_CALL.search(_expand_tasks(str(s["run"]), tasks or {}))),
               default=None)  # fmt: skip
    if last is not None and last + 1 < len(runs):
        notes.append(f"{len(runs) - last - 1} step(s) after the tests left out (they run no tests)")
        runs = runs[: last + 1]
    if any(_PUBLISHES.search(_expand_tasks(str(s["run"]), tasks or {})) for s in runs):
        return None
    if not _reproducible(runs, files):
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
        if command and downloads and files is not None:
            # A line that reads a file the repository does not have, in a job that downloads another job's artifacts,
            # needs that artifact (stage 10, Prefect: `test-durations.json`): left out, and said.
            kept_lines = []
            for line in command.splitlines():
                missing = [m.group("path") for m in _DATA_FILE.finditer(line)
                           if m.group("path").lstrip("./") not in files and not _RUNNER_CALL.search(line)]  # fmt: skip
                if missing and not line.lstrip().startswith(("echo ", "exit ", "set ")):
                    notes.append(f"left out, it needs another job's artifact ({missing[0]}): {line.strip()[:120]}")
                    continue
                kept_lines.append(line)
            command = "\n".join(kept_lines)
        if command:
            command = _SPLIT_BOOKKEEPING.sub("", command)
        if command and _parses(command):
            steps.append(CiStep(cwd=str(step.get("working-directory") or defaults), command=command))
    text = " ".join(s.command for s in steps) + " " + " ".join((scripts or {}).values())
    runs_tests = _PY_TESTS.search(text) if language == "python" else re.search(r"\btest\b", text)
    if not steps or not runs_tests:
        return None
    containers = []
    for name, spec in (job.get("services") or {}).items():
        if not isinstance(spec, dict) or not spec.get("image"):
            continue
        own = tuple(sorted((str(k), str(v)) for k, v in (spec.get("env") or {}).items() if not _EXPR.search(str(v))))
        ports = tuple(int(str(p).split(":")[-1]) for p in spec.get("ports") or [] if str(p).split(":")[-1].isdigit())
        containers.append((str(name), str(spec["image"]), own, ports))
    env: dict[str, str] = {str(k): str(v) for k, v in (job.get("env") or {}).items() if not _EXPR.search(str(v))}
    for step in runs:
        env |= {str(k): str(v) for k, v in (step.get("env") or {}).items() if not _EXPR.search(str(v))}
    env |= written
    split = next((m for s in steps if (m := _SPLITS.search(s.command))), None)
    scope = f"pytest-split group {split.group('g')} of {split.group('n')}" if split else ""
    return CiPlan(workflow=workflow, job=job_name, steps=tuple(steps), services=tuple(dict.fromkeys(services)),
                  containers=tuple(containers), env=tuple(sorted(env.items())), scope=scope,
                  notes=tuple(dict.fromkeys(notes)))  # fmt: skip


def _entry_job(job: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """The job as one matrix entry runs it: its expressions resolved where known, steps whose `if:` is known to be
    false left out."""
    context = {"matrix": entry}
    steps = []
    for step in job.get("steps") or []:
        if isinstance(step, dict) and "if" in step:
            condition = re.sub(r"^\s*\$\{\{\s*(.*?)\s*\}\}\s*$", r"\1", str(step["if"]), flags=re.S)
            value = gh_expression(condition, context)
            if value is not None and value in (False, "", 0):
                continue
        steps.append(step)
    return _resolve({**job, "steps": steps}, context)


def _entries(job: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The job's matrix entries, each as it runs; those whose service containers all have an image first (an entry
    with its database is what the lab can measure on), then in the matrix's own order."""
    out = []
    for entry in _matrix(job):
        resolved = _entry_job(job, entry)
        images = [str((s or {}).get("image", "")) for s in (resolved.get("services") or {}).values()]
        complete = bool(images) and all(i and "${{" not in i for i in images)
        out.append((0 if complete else 1, _label(entry), resolved))
    out.sort(key=lambda x: x[0])
    return [(label, resolved) for _, label, resolved in out]


_TOKEN = re.compile(
    r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?\d+(?:\.\d+)?)|(?P<op>&&|\|\||==|!=|!|\(|\)|,)"
    r"|(?P<name>[A-Za-z_][\w-]*(?:\.[A-Za-z_*][\w-]*)*))"
)
_UNKNOWN = object()


def gh_expression(expr: str, context: dict[str, Any]) -> Any:
    """The value of a GitHub Actions expression where only literals and `context` (the matrix, a reusable
    workflow's inputs) are known; None when it depends on anything else (a secret, a step's output, the runner's
    state). A small parser over the documented grammar: nothing in the repository's text is ever run as code."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        if expr[pos:].strip() == "":
            break
        m = _TOKEN.match(expr, pos)
        if m is None:
            return None
        kind = str(m.lastgroup)
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    at = 0

    def peek() -> tuple[str, str] | None:
        return tokens[at] if at < len(tokens) else None

    def take() -> tuple[str, str]:
        nonlocal at
        at += 1
        return tokens[at - 1]

    def truthy(v: Any) -> bool:
        return v not in (None, False, "", 0) and v is not _UNKNOWN

    def primary() -> Any:
        tok = take()
        if tok == ("op", "!"):
            v = primary()
            return _UNKNOWN if v is _UNKNOWN else not truthy(v)
        if tok == ("op", "("):
            v = disjunction()
            take()
            return v
        kind, text = tok
        if kind == "str":
            return text[1:-1].replace("''", "'")
        if kind == "num":
            return float(text) if "." in text else int(text)
        if text in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[text]
        if peek() == ("op", "("):  # a function call
            take()
            args: list[Any] = []
            while peek() != ("op", ")"):
                args.append(disjunction())
                if peek() == ("op", ","):
                    take()
            take()
            if any(a is _UNKNOWN for a in args) or text not in ("startsWith", "endsWith", "contains", "format"):
                return _UNKNOWN
            a = [str(x) if not isinstance(x, (list, dict)) else x for x in args]
            if text == "format":
                return re.sub(r"\{(\d+)\}", lambda m: str(a[int(m.group(1)) + 1]), str(a[0]))
            if text == "contains":
                return str(a[1]).lower() in (a[0] if isinstance(a[0], list) else str(a[0]).lower())
            subject, part = str(a[0]).lower(), str(a[1]).lower()
            return subject.startswith(part) if text == "startsWith" else subject.endswith(part)
        value: Any = context
        for part in text.split("."):
            if not isinstance(value, dict) or part not in value:
                return _UNKNOWN
            value = value[part]
        return value

    def comparison() -> Any:
        left = primary()
        while peek() in (("op", "=="), ("op", "!=")):
            op = take()[1]
            right = primary()
            if left is _UNKNOWN or right is _UNKNOWN:
                left = _UNKNOWN
            else:
                same = str(left).lower() == str(right).lower()
                left = same if op == "==" else not same
        return left

    def conjunction() -> Any:
        left = comparison()
        while peek() == ("op", "&&"):
            take()
            right = comparison()
            if left is _UNKNOWN:
                left = _UNKNOWN if truthy(right) or right is _UNKNOWN else right
            else:
                left = right if truthy(left) else left
        return left

    def disjunction() -> Any:
        left = conjunction()
        while peek() == ("op", "||"):
            take()
            right = conjunction()
            left = _UNKNOWN if left is _UNKNOWN else left if truthy(left) else right
        return left

    try:
        value = disjunction()
    except IndexError:
        return None
    if at != len(tokens) or value is _UNKNOWN:
        return None
    return value


def _matrix(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Every entry of a job's matrix, as GitHub Actions expands it: the product of its lists, `exclude` removed,
    `include` added. One empty entry for a job without a matrix (or with a matrix built by an expression)."""
    matrix = (job.get("strategy") or {}).get("matrix")
    if not isinstance(matrix, dict):
        return [{}]
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude") and isinstance(v, list)}
    entries: list[dict[str, Any]] = [{}]
    for key, values in axes.items():
        entries = [{**e, key: v} for e in entries for v in values]

    def matches(entry: dict[str, Any], pattern: dict[str, Any]) -> bool:
        return all(entry.get(k) == v for k, v in pattern.items())

    excluded = [x for x in matrix.get("exclude") or [] if isinstance(x, dict)]
    entries = [e for e in entries if not any(matches(e, x) for x in excluded)]
    for extra in [x for x in matrix.get("include") or [] if isinstance(x, dict)]:
        hit = [e for e in entries if all(e.get(k) == v for k, v in extra.items() if k in axes)]
        if hit and any(k in axes for k in extra):
            for e in hit:
                e.update({k: v for k, v in extra.items() if k not in axes})
        else:
            entries.append(dict(extra))
    return entries or [{}]


def _label(entry: dict[str, Any]) -> str:
    def short(v: Any) -> str:
        return str(v.get("id") or v.get("name") or v) if isinstance(v, dict) else str(v)

    return ", ".join(f"{k}={short(v)}" for k, v in entry.items()) or "the job"


def _resolve(node: Any, context: dict[str, Any]) -> Any:
    """Every `${{ ... }}` whose value is known replaced by it; the others left for `_clean` to drop as before."""
    if isinstance(node, str):

        def one(m: re.Match[str]) -> str:
            value = gh_expression(m.group(1), context)
            if value is None:
                return m.group(0)
            return " ".join(str(v) for v in value) if isinstance(value, list) else str(value)

        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", one, node, flags=re.S)
    if isinstance(node, list):
        return [_resolve(x, context) for x in node]
    if isinstance(node, dict):
        return {k: _resolve(v, context) for k, v in node.items()}
    return node


def _fill(node: Any, values: dict[str, Any]) -> Any:
    """`${{ inputs.x }}` replaced by the caller's value; anything else left as it is."""
    if isinstance(node, str):
        return re.sub(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}", lambda m: str(values.get(m.group(1), m.group(0))), node)
    if isinstance(node, list):
        return [_fill(x, values) for x in node]
    if isinstance(node, dict):
        return {k: _fill(v, values) for k, v in node.items()}
    return node


def _called(repo: Path, rev: str, jobs: list[tuple[str, str, dict[str, Any]]]) -> list[tuple[str, str, dict[str, Any]]]:
    """Jobs of local reusable workflows (`uses: ./.github/workflows/tests.yml` with `with:` inputs), with each
    `${{ inputs.x }}` replaced by what the caller passes or the input's default; what stays an expression (a matrix
    value) is left out as before."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    for name, job_name, job in jobs:
        uses = str(job.get("uses", ""))
        if not uses.startswith("./.github/workflows/"):
            continue
        try:
            called = yaml.safe_load(_git(repo, "show", f"{rev}:{uses.removeprefix('./')}")) or {}
        except yaml.YAMLError:
            continue
        trigger = (called.get("on") or called.get(True) or {}) if isinstance(called, dict) else {}
        declared = ((trigger.get("workflow_call") or {}).get("inputs") or {}) if isinstance(trigger, dict) else {}
        values = {k: (v or {}).get("default") for k, v in declared.items() if isinstance(v, dict)}
        values |= {str(k): v for k, v in (job.get("with") or {}).items()}

        for inner_name, inner in (called.get("jobs") or {}).items():
            if isinstance(inner, dict):
                out.append((f"{name}:{job_name}", f"{inner_name} ({uses.rsplit('/', 1)[-1]})", _fill(inner, values)))
    return out


_SYNC_FLAG = re.compile(
    r"--(?:all-extras|all-groups|dev|no-dev|only-dev|no-default-groups)\b"
    r"|--(?:group|extra|only-group|no-group)[= ]+[\w.-]+"
)


def _sync_flags(repo: Path, rev: str, job: dict[str, Any]) -> tuple[str, ...] | None:
    """The dependency groups and extras the test job installs, read from the `uv sync` its steps run, and those of
    the local composite actions it uses (`uses: ./.github/actions/prepare`). Stage 9 evaluation, Prefect: its test job
    runs `uv sync --locked`; Unbidden installed every group, one of them a package from GitHub, and the image did
    not build. None when the job runs no `uv sync` (the previous rule, every group, stands)."""
    texts = [str(s.get("run", "")) for s in job.get("steps") or [] if isinstance(s, dict)]
    for step in job.get("steps") or []:
        uses = str(step.get("uses", "")) if isinstance(step, dict) else ""
        if uses.startswith("./"):
            for name in ("action.yml", "action.yaml"):
                text = _git(repo, "show", f"{rev}:{uses.removeprefix('./').rstrip('/')}/{name}")
                if text:
                    texts.append(text)
                    break
    lines = [ln for text in texts for ln in re.findall(r"\buv\s+sync\b([^\n]*)", text)]
    if not lines:
        return None
    return tuple(dict.fromkeys(m.group(0).replace("=", " ") for ln in lines for m in _SYNC_FLAG.finditer(ln)))


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
    jobs += _called(repo, rev, jobs)

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

    tasks = taskfile_tasks(repo, rev)
    files = set(_git(repo, "ls-tree", "-r", "--name-only", rev).splitlines())

    def scripts_of(job: dict[str, Any]) -> dict[str, str]:
        """Repository scripts the job's steps run (`./scripts/test`), so a job is judged by what they execute."""
        found: dict[str, str] = {}
        for step in job.get("steps") or []:
            for line in str(step.get("run", "") if isinstance(step, dict) else "").splitlines():
                head = _RUNNERS.sub("", line.strip()).split(" ")[0]
                if head.startswith("./") or (("/" in head) and not head.startswith(("/", "$", "-"))):
                    text = _git(repo, "show", f"{rev}:{head.removeprefix('./')}")
                    if text:
                        found[head] = text
        return found

    def executes(job: dict[str, Any]) -> str:
        runs = " ".join(str(_as_run(s).get("run", "")) for s in job.get("steps") or [] if isinstance(s, dict))
        return runs + " " + " ".join(scripts_of(job).values())

    def runner(item: tuple[str, str, dict[str, Any]]) -> tuple[int, int, int]:
        text = executes(item[2])
        explicit = _RUNNER_CALL.search(text) is not None
        # A job that starts the app in the background and tests it over HTTP needs ports and often the network.
        served = bool(re.search(r"&\s*$", text, re.M)) or bool(_HTTP_TESTS.search(text))
        # A job whose steps or environment need the repository's secrets (a profiling token) fails without them
        # (stage 9, Prefect); reports uploaded by an action (`uses:` with a token) do not count.
        job = item[2]
        own = [job.get("env") or {}, *[{"run": s.get("run"), "env": s.get("env")} for s in job.get("steps") or []
                                         if isinstance(s, dict) and not s.get("uses")]]  # fmt: skip
        secret = "secrets." in json.dumps(own, default=str)
        return (0 if explicit else 1, 1 if served else 0, 1 if secret else 0)

    jobs.sort(key=lambda item: (*runner(item), *rank(item)))
    for name, job_name, job in jobs:
        hint = " ".join(
            str(s.get("run", "")) + str(s.get("uses", "")) for s in job.get("steps") or [] if isinstance(s, dict)
        )
        hint = _expand_tasks(hint, tasks) if tasks else hint
        if language == "python" and not re.search(r"python|pytest|uv |poetry", hint):
            continue
        if language == "node" and not re.search(r"node|npm|pnpm|yarn|bun", hint):
            continue
        entries = _entries(job)
        label, resolved = entries[0]
        plan = _job_plan(name, job_name, resolved, language, tasks, scripts_of(resolved), files)
        if plan is not None:
            from dataclasses import replace

            groups = tuple(lbl for lbl, _ in entries)
            parts = [f"matrix entry 1 of {len(groups)} ({label})"] if len(groups) > 1 else []
            if plan.scope:
                parts.append(plan.scope)
                if len(groups) == 1:  # a split without a matrix: the groups are pytest-split's own
                    n = int(re.search(r"of (\d+)", plan.scope).group(1))  # type: ignore[union-attr]
                    groups = tuple(f"pytest-split group {i}" for i in range(1, n + 1))
            return replace(plan, sync_flags=_sync_flags(repo, rev, job), groups=groups if len(groups) > 1 else (),
                           scope="; ".join(parts) or plan.scope or "the whole job")  # fmt: skip
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
                               "--extend-select", "--cache-dir", "--outdir", "--out-dir", "-f", "--verifytypes",
                               "--level"}  # fmt: skip
# Flags that put a tool in a mode that reports on no source file: its run sets no scope for findings.
_NO_FILES_MODES = {"pyright": {"--verifytypes", "--createstub"}}
DEFAULT_CONFIGS = {
    "tsc": {"tsconfig.json"},
    "mypy": {"mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg"},
    "ruff": {"ruff.toml", ".ruff.toml", "pyproject.toml"},
    "pyright": {"pyrightconfig.json", "pyproject.toml"},
    "eslint": {"eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", ".eslintrc",
               ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml", ".eslintrc.yaml"},
    "biome": {"biome.json", "biome.jsonc"},
}  # fmt: skip


# Packages whose name is not the command they run, as `npx`/`bunx`/`pnpm dlx`/`uvx` name them.
PACKAGE_TOOLS = {"typescript": "tsc", "@biomejs/biome": "biome"}


def _tool_of(token: str, *, via_runner: bool) -> tuple[str, str | None]:
    """The tool a token runs and the version it pins: `tsc`, `./node_modules/.bin/tsc`, and, through a package
    runner, `typescript@7.0.2` or `ruff==0.6.0` (a pinned version, possibly not the project's)."""
    if not via_runner:
        return PurePosixPath(token).name.removesuffix(".exe"), None
    name, version = token, None
    if "==" in token:
        name, version = token.split("==", 1)
    elif "@" in token.lstrip("@"):
        at = token.rindex("@")
        name, version = token[:at], token[at + 1 :]
    name = name if name.startswith("@") else PurePosixPath(name).name.removesuffix(".exe")
    return PACKAGE_TOOLS.get(name, name), version or None


@dataclass(frozen=True)
class Invocation:
    subcommand: str | None
    paths: tuple[str, ...]  # where it runs, relative to the repository; empty: its whole working directory
    config: str | None  # an explicit configuration file
    cwd: str  # from a preceding `cd <dir> &&`
    version: str | None = None  # pinned by the step itself (`bunx typescript@7.0.2`), not by the project
    checks_files: bool = True  # False for a mode that checks no source files (`pyright --verifytypes <package>`)

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
    return list(_invocations(commands, tool))


@functools.lru_cache(maxsize=64)
def _invocations(commands: str, tool: str) -> tuple[Invocation, ...]:
    # Read once per CI text and tool: every sweep asks it for each opportunity, and tokenizing a large CI is slow
    # (stage 10: Prefect's, about 0.4 s a call, made each sweep of 229 opportunities last about 40 s).
    found: list[Invocation] = []
    for line in commands.splitlines():
        cwd = ""
        for segment in re.split(r"&&|\|\||;|\|", line):
            tokens = _tokens(segment)
            if len(tokens) >= 2 and tokens[0] == "cd":
                cwd = tokens[1]
                continue
            for i, token in enumerate(tokens):
                before = tokens[i - 1] if i else ""
                named, version = _tool_of(token, via_runner=before in _INVOKERS)
                if named != tool:
                    continue
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
                checks = not (set(args) & _NO_FILES_MODES.get(tool, set()))
                found.append(Invocation(subcommand, tuple(paths), config, cwd, version, checks))
    return tuple(found)


def tool_scope(
    read: Callable[[str], str | None], tracked: Iterable[str], commands: str | None, tool: str
) -> tuple[str, ...] | None:
    """The directories the team's CI checks with `tool`: the paths its steps name, or the `include` (pyright) or
    `files` (mypy) of the configuration file they pass. None when some step checks the whole tree, or the CI does not
    run the tool, or its scope cannot be read (stage 10: Prefect's pyright checks `src/` through pyrightconfig-ci.json,
    and Unbidden's own run fixed errors in `benches/`)."""
    if not commands or not tool:
        return None
    files = set(tracked)
    dirs = {str(d) for f in files for d in PurePosixPath(f).parents if str(d) != "."}

    def exists(path: str) -> bool:
        return path in files or path in dirs

    runs = [inv for inv in tool_invocations(commands, tool) if inv.checks_files]
    scope: list[str] = []
    for inv in runs:
        base = inv.cwd.strip("./")
        named = [str(PurePosixPath(base) / p).strip("/") if base else p.strip("/") for p in inv.paths]
        if named and not any(exists(p) for p in named):
            continue  # words that only look like paths (a sentence that mentions the tool): not a run of it
        paths = [p for p in named if exists(p)]
        if not paths and inv.config:
            paths = [str(PurePosixPath(base) / p).strip("/") if base else p for p in _config_scope(read, inv, tool)]
        if not paths:
            return None
        scope += paths
    return tuple(sorted(set(scope))) or None


def _config_scope(read: Callable[[str], str | None], inv: Invocation, tool: str) -> list[str]:
    assert inv.config is not None
    path = str(PurePosixPath(inv.cwd.strip("./")) / inv.config) if inv.cwd.strip("./") else inv.config
    text = read(path.removeprefix("./"))
    if not text:
        return []
    try:
        if path.endswith(".toml"):
            section = tomllib.loads(text).get("tool", {}).get(tool, {})
        elif path.endswith(".json"):
            section = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))  # pyright allows comments
        else:
            ini = configparser.ConfigParser()
            ini.read_string(text)
            section = {"files": ini.get(tool, "files", fallback="")}
    except (ValueError, configparser.Error):
        return []
    found = section.get("include" if tool == "pyright" else "files") if isinstance(section, dict) else None
    if isinstance(found, str):
        found = [f.strip() for f in found.split(",") if f.strip()]
    return [str(f).removeprefix("./").rstrip("/") for f in found or [] if isinstance(f, str)]


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
    pinned = [i for i in covering if i.version]
    if len(pinned) == len(covering):
        return DIFFERS, f"the team's CI runs {tool} {pinned[0].version}, a version it pins itself"
    defaults = [
        i for i in covering if i.config is None or PurePosixPath(i.config).name in DEFAULT_CONFIGS.get(tool, ())
    ]
    if not defaults:
        return DIFFERS, f"the team's CI runs {tool} with {covering[0].config}, not the configuration Unbidden used"
    return SAME, ""
