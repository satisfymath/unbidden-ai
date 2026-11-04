"""The environment the team's own CI job prepares, used as the sandbox for everything measured offline.

Campaign 13 (2026-11-03): Unbidden used to *reconstruct* the CI job: read the workflow, drop every `uses:` action,
build its own slim image with a guessed toolset, strip lines, and run offline. Every repository broke a different
assumption (a missing `msgfmt`, a locale, `git`, a variable the job sets, a tool an action installs), and each fix
only showed the next one. Here the job itself runs, as GitHub runs it: in a runner-like image, with its actions, its
`env:`, its services, and the network, through `act` (nektos/act). Its container is then committed as the image
every later command runs in, offline, at the same workspace path (the virtualenvs it made record that path).

What never runs: jobs other than the test job the CI plan chose; steps that publish (coverage uploads, releases,
deploys, pushes, notifications); anything with the host's Docker socket (the job gets none); secrets (none are
passed). What the job installed into the workspace (virtualenvs, node_modules, .tox) is copied inside the image
and laid back under each snapshot before a command runs; the tracked files of the snapshot always win.

Without `act`, without a test job, with a `self-hosted` or non-Linux-only job, or when the job failed before its
test step, the caller falls back to Unbidden's own image (`sandbox/provision.py`), and the reason is recorded."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from unbidden.sandbox.provision import DependencyImage
from unbidden.sandbox.runner import snapshot, with_git

RUNNER_BASE = "catthehacker/ubuntu:act-22.04"
RUNNER_IMAGE = "unbidden-runner:22.04-3"
# What GitHub's hosted runner has and the act image lacks: the apt index, apt answering yes, en_US.UTF-8 (harlequin),
# git trusting any checkout (the workspace is mounted from the host, owned by another uid).
RUNNER_DOCKERFILE = (
    f"FROM {RUNNER_BASE}\n"
    "RUN echo 'APT::Get::Assume-Yes \"true\";' > /etc/apt/apt.conf.d/90assumeyes \\\n"
    " && apt-get update \\\n"
    " && (apt-get install -y --no-install-recommends locales >/dev/null || true) \\\n"
    " && sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen en_US.UTF-8 \\\n"
    " && git config --system --add safe.directory '*' \\\n"
    # GitHub's runner has the database clients (archery: `mysql -h127.0.0.1 -e "CREATE DATABASE ..."`); socat
    # gives localhost the job's services, as the runner's mapped ports do (`localhost_forwards`).
    " && (apt-get install -y --no-install-recommends socat default-mysql-client postgresql-client redis-tools "
    ">/dev/null || true)\n"
)


def localhost_forwards(pairs: list[tuple[str, str]]) -> str:
    """A shell line that makes each service's port answer on localhost, as on GitHub's runner, where a job reaches
    its service containers at 127.0.0.1 on their mapped ports (archery's settings: `mysql://root:@127.0.0.1:3306`).
    Here services are containers reached by name, so socat forwards; ports below 1024 are left (no privilege)."""
    lines = [f"(setsid nohup socat TCP-LISTEN:{port},fork,reuseaddr,bind=127.0.0.1 TCP:{host}:{port} >/dev/null 2>&1 &)"
             for host, port in pairs if port.isdigit() and int(port) >= 1024]  # fmt: skip
    return ("if command -v socat >/dev/null; then " + "; ".join(lines) + "; sleep 1; fi") if lines else ""


def service_ports(services: Any) -> list[tuple[str, str]]:
    """(service, container port) of a job's `services:` mapping."""
    pairs: list[tuple[str, str]] = []
    for name, service in (services or {}).items():
        if isinstance(service, dict):
            for port in service.get("ports") or []:
                pairs.append((str(name), str(port).split(":")[-1].split("/")[0]))
    return pairs


TOOLCACHE = "act-toolcache"  # act keeps setup-python/uv/node downloads in this shared volume, outside the commit
PREPARED = "/opt/unbidden-prepared"  # the job's workspace as it left it, inside the committed image
ENV_FILE = "/opt/unbidden-job.env"
WORKFLOW = ".unbidden-ci/job.yml"
JOB_TIMEOUT_S = 3600.0
RECORD_VERSION = "ci-env-11"  # part of the cache key: a record from an older layout is prepared again
Progress = Callable[[str], None]

# A step that would reach outside the copy: coverage and test reports uploaded, releases, deploys, pushes,
# notifications. Campaign 13: humanize's job carried a Codecov upload (it failed only because the copy had no remote).
PUBLISH_USES = re.compile(
    r"codecov|coveralls|upload-release|gh-release|release-action|semantic-release|deploy|pages|pypi-publish|"
    r"gh-action-pypi|docker/(?:build-push|login|metadata)|push|publish|slack|discord|notify|ssh-|scp-|rsync|"
    r"aws-actions|google-github-actions|azure/|create-pull-request|github-script|upload-artifact",
    re.IGNORECASE,
)
PUBLISH_RUN = re.compile(
    r"\b(?:twine\s+upload|gh\s+(?:release|pr|api)|npm\s+publish|yarn\s+publish|pnpm\s+publish|docker\s+(?:push|login)|"
    r"git\s+push|poetry\s+publish|uv\s+publish|flit\s+publish|hatch\s+publish|codecov|coveralls|curl\b[^\n]*"
    r"(?:hooks\.slack|discord|api\.github))",
    re.IGNORECASE,
)
TEST_WORDS = re.compile(
    r"\b(?:pytest|tox|nox|unittest|make\s+(?:test|check)|manage\.py\s+test|run\s+tests?)\b"
    # a task runner called with a test or validation target (rdflib: `task ... gha:validate`)
    r"|\b(?:task|just|make)\b[^\n]*?[\s:](?:[\w:-]*:)?(?:tests?|validate|check)\b",
    re.I,
)
SCRIPTS = "/opt/unbidden-scripts"  # each step as act ran it, its GitHub expressions already resolved
# act ends a step's line with its duration in any Go form (`[36.6ms]`, `[4m17.22s]`, `[1h2m3s]`).
_STEP = re.compile(r"(✅|❌)\s+(Success|Failure) - Main (?P<name>.+?)(?: \[[^\]]*\])?\s*$")


class NotPreparable(RuntimeError):
    """The team's CI job cannot prepare this environment here; the reason is the message."""


@dataclass
class CiEnvironment:
    image: DependencyImage
    workflow: str
    job: str
    matrix: dict[str, str]
    skipped: list[str]
    steps: list[tuple[str, bool]]
    job_ok: bool
    seconds: float
    log_tail: str = ""
    notes: list[str] = field(default_factory=list[str])


_INSTALL_LINE = re.compile(r"^\s*(?:sudo\s+)?(?:python3?\s+-m\s+)?(?:pip3?|uv\s+pip|uv\s+tool|pipx|poetry|npm|yarn|pnpm"
                           r"|apt(?:-get)?|brew|gem)\s+(?:install|add|ci)\b")  # fmt: skip


def publishes(run_text: str) -> bool:
    """A step whose commands send something out. A line that only installs a publishing tool does not
    (oauthlib, campaign 13: `pip install tox coveralls` was the step that installed tox)."""
    lines = [ln for ln in re.sub(r"\\\n\s*", " ", run_text).splitlines() if not _INSTALL_LINE.match(ln)]
    return bool(PUBLISH_RUN.search("\n".join(lines)))


# A command that drives the host's Docker (archery, campaign 13: `docker cp my.cnf mysql:/etc/...` and `docker restart
# mysql` to configure its service container). The job never gets the Docker socket, so the step cannot run; it is
# left out and said, like a publishing step, and the service keeps its image's defaults.
_DOCKER_RUN = re.compile(r"(?:^|[;&|(]\s*|\n\s*)(?:sudo\s+)?docker(?:-compose|\s+compose)?\s+\w", re.MULTILINE)


def drives_docker(run_text: str) -> bool:
    return bool(_DOCKER_RUN.search(run_text))


def act_path() -> str | None:
    return shutil.which("act")


def cache_root() -> Path:
    from unbidden.brain.spend import home

    return home() / "ci-env"


def ensure_runner_image(docker: str = "docker") -> str:
    """The runner image, built once from the act image (pulled with the network the build has)."""
    if subprocess.run([docker, "image", "inspect", RUNNER_IMAGE], capture_output=True).returncode == 0:
        return RUNNER_IMAGE
    import tempfile

    with tempfile.TemporaryDirectory(prefix="unbidden-runner-") as tmp:
        (Path(tmp) / "Dockerfile").write_text(RUNNER_DOCKERFILE)
        built = subprocess.run([docker, "build", "-q", "-t", RUNNER_IMAGE, tmp], capture_output=True, text=True)
    if built.returncode != 0:
        raise NotPreparable(f"the runner image could not be built: {built.stderr[-400:]}")
    return RUNNER_IMAGE


def _pick(values: list[Any], prefer: tuple[str, ...]) -> Any:
    for want in prefer:
        for value in values:
            if str(value) == want:
                return value
    plain = [v for v in values if not re.search(r"pypy|t$|dev|alpha|beta|rc|-", str(v))]
    return (plain or values)[-1]


def filtered_job(repo: Path, rev: str, workflow: str, job: str) -> tuple[str, dict[str, str], list[str]]:
    """The workflow reduced to the test job, without its publishing steps, its runner Linux, one matrix entry, and a
    last step that records the job's environment and keeps its workspace. Raises NotPreparable with the reason."""
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:.github/workflows/{workflow}"],
                           capture_output=True, text=True, check=False)  # fmt: skip
    if shown.returncode != 0:
        raise NotPreparable(f"no workflow {workflow} at {rev[:12]}")
    data = yaml.safe_load(shown.stdout) or {}
    definition = dict((data.get("jobs") or {}).get(job) or {})
    if not definition or "steps" not in definition:
        raise NotPreparable(f"no job {job} with steps in {workflow} (a reusable workflow call is not run here)")
    runs_on = json.dumps(definition.get("runs-on", ""))
    if "self-hosted" in runs_on:
        raise NotPreparable(f"{workflow}:{job} runs on the team's own (self-hosted) runner; its machine is not here")
    matrix_spec = ((definition.get("strategy") or {}).get("matrix") or {}) if isinstance(definition, dict) else {}
    matrix, chosen = _one_combination(matrix_spec, f"{workflow}:{job}")
    if chosen is not None:
        # One combination, written into the job itself (values may be objects: codex-lb's `slice: {name: unit}`),
        # so act runs exactly it; include/exclude lists are resolved here.
        definition["strategy"] = {"fail-fast": False, "matrix": chosen}
    if "${{" not in runs_on and not re.search(r"ubuntu|linux", runs_on, re.I):
        raise NotPreparable(f"{workflow}:{job} runs on {runs_on}, not Linux")
    skipped: list[str] = []
    steps: list[dict[str, Any]] = []
    for step in definition.get("steps") or []:
        if not isinstance(step, dict):
            continue
        label = str(step.get("name") or step.get("uses") or str(step.get("run", ""))[:60])
        run_text = str(step.get("run", ""))
        if PUBLISH_USES.search(str(step.get("uses", ""))) or publishes(run_text) or drives_docker(run_text):
            skipped.append(label)
            continue
        if "astral-sh/setup-uv" in str(step.get("uses", "")):
            # Its post step prunes uv's cache after the environment is kept: the offline measurement then lacks the
            # build backends a `uv run` rebuild needs (codex-lb, campaign 13: hatchling).
            step = {**step, "with": {**(step.get("with") or {}), "prune-cache": False}}
        if "needs." in str(step.get("if", "")):
            # A condition on another job's outputs (codex-lb: `needs.changes.outputs.backend == 'true'`): that job
            # does not run here, so the step runs as when the change touches it.
            step = {k: v for k, v in step.items() if k != "if"}
        steps.append(step)
    steps.append({
        "name": "unbidden: keep the prepared environment",
        "if": "always()",
        "shell": "bash",
        "run": f"env -0 > {ENV_FILE}; mkdir -p {PREPARED} {SCRIPTS}; cp -a . {PREPARED}/; "
               f"cp -a /var/run/act/workflow/. {SCRIPTS}/ 2>/dev/null || true",
    })  # fmt: skip
    forwards = localhost_forwards(service_ports(definition.get("services")))
    if forwards:
        steps.insert(0, {"name": "unbidden: the job's services on localhost", "run": forwards})
    definition["steps"] = steps
    definition["runs-on"] = "ubuntu-latest"
    for service in (definition.get("services") or {}).values():
        # A fixed host port (`5432:5432`) collides with whatever else this machine runs (timetracker, campaign 13:
        # the service never started); the container port stays, the host port is Docker's choice.
        if isinstance(service, dict) and isinstance(service.get("ports"), list):
            service["ports"] = [str(p).split(":")[-1] for p in service["ports"]]
        if isinstance(service, dict) and isinstance(service.get("options"), str):
            # A fixed container name (archery: `--name=mysql`, for a `docker cp` step left out above): act names its
            # service containers itself and refuses the flag; the service is still reached by its key.
            service["options"] = re.sub(r"--name(?:=|\s+)\S+\s*", "", service["options"]).strip()
    for key in ("needs", "if", "environment", "concurrency", "permissions"):
        definition.pop(key, None)
    out: dict[str, Any] = {"name": "unbidden-ci", "on": "push", "jobs": {job: definition}}
    for key in ("env", "defaults"):
        if data.get(key):
            out[key] = data[key]
    return yaml.safe_dump(out, sort_keys=False), matrix, skipped


_RAN = re.compile(r"⭐ Run Main (?P<name>.+?)\s*$")
_EXEC = re.compile(
    r"docker exec cmd=\[(?P<cmd>[^\]]*?(?P<path>/var/run/act/workflow/[^\s\]]+)[^\]]*)\] user=\S* workdir=(?P<dir>\S*)"
)


def step_scripts(log: str) -> dict[str, tuple[str, str, str]]:
    """Step name -> (shell, script path, working directory) as act ran it, read from its log."""
    found: dict[str, tuple[str, str, str]] = {}
    current: str | None = None
    for line in log.splitlines():
        if (ran := _RAN.search(line)) is not None:
            current = ran.group("name").strip()
        elif current and (ex := _EXEC.search(line)) is not None:
            # The whole command act ran (`bash --noprofile --norc -e -o pipefail /var/run/act/workflow/5.sh` under
            # `shell: bash`; `bash -e /var/run/act/workflow/5` otherwise), its script path kept apart.
            found.setdefault(current, (ex.group("cmd"), ex.group("path"), ex.group("dir")))
            current = None
    return found


def test_command(job_text: str, scripts: dict[str, tuple[str, str, str]]) -> str | None:
    """The job's test steps as act ran them: the saved script of each step whose name or command runs tests, in
    order, in its working directory. Expressions such as `${{ matrix.os == 'x' && '--flag' || '' }}` were resolved by
    act when it wrote the script, so nothing is reinterpreted here (harlequin, campaign 13)."""
    data = yaml.safe_load(job_text) or {}
    lines: list[str] = []
    for definition in (data.get("jobs") or {}).values():
        for step in definition.get("steps") or []:
            name = str(step.get("name") or "")
            run_text = str(step.get("run") or "")
            if not run_text or name.startswith("unbidden:"):
                continue
            if not runs_tests(name, run_text):
                continue
            ran = scripts.get(name) or next((v for k, v in scripts.items() if k == run_text.strip()[:60]), None)
            if ran is None:
                continue
            cmd, path, directory = ran
            command = cmd.replace(path, f"{SCRIPTS}/{path.rsplit('/', 1)[-1]}")
            lines.append(f"(cd {directory} && {command})" if directory else command)
    return "\n".join(lines) or None


def _one_combination(spec: Any, where: str) -> tuple[dict[str, str], dict[str, list[Any]] | None]:
    """A single Linux combination of a job's matrix: (its values as text, for the record; the matrix to write)."""
    if isinstance(spec, str):
        raise NotPreparable(f"{where}: its matrix is computed by an expression ({spec[:80]})")
    if not isinstance(spec, dict) or not spec:
        return {}, None
    chosen: dict[str, Any] = {}
    for key, values in spec.items():
        if key in ("include", "exclude") or not isinstance(values, list) or not values:
            continue
        if key in ("os", "platform", "runs-on"):
            linux = [v for v in values if "ubuntu" in str(v) or "linux" in str(v)]
            if not linux:
                raise NotPreparable(f"{where} runs on {values}, none of them Linux")
            chosen[key] = linux[-1]
        elif "python" in key or key in ("py", "python"):
            chosen[key] = (
                _pick(values, ("3.12", "3.11", "3.13")) if all(not isinstance(v, dict) for v in values) else values[0]
            )
        else:
            chosen[key] = values[0]
    includes = [i for i in spec.get("include") or [] if isinstance(i, dict)]
    if not chosen and includes:
        linux = [i for i in includes if not any(k in i for k in ("os", "runs-on"))
                 or re.search(r"ubuntu|linux", str(i.get("os", i.get("runs-on", ""))))]  # fmt: skip
        if not linux:
            raise NotPreparable(f"{where}: no Linux entry in its matrix")
        chosen = dict(linux[0])
    else:
        for extra in includes:  # include entries that extend the chosen combination with more keys
            if all(chosen.get(k) == v for k, v in extra.items() if k in chosen):
                chosen.update({k: v for k, v in extra.items() if k not in chosen})
    readable = {k: (v.get("name") if isinstance(v, dict) and "name" in v else str(v)) for k, v in chosen.items()}
    return {k: str(v) for k, v in readable.items()}, {k: [v] for k, v in chosen.items()}


_PREPARES = re.compile(r"\b(?:install|set\s*up|setup|seed|prepare|cache|build|download|lint|type)\b", re.I)


def runs_tests(name: str, run_text: str) -> bool:
    """A step that runs the tests, not one that installs or prepares for them (pipx, campaign 13: "Install tox",
    "Set up test suite" (`tox run --notest`) and "Seed package cache" (`tox exec … update_package_cache.py`, which
    downloads) all name tox; only "Run test suite" runs tests)."""
    commands = "\n".join(ln for ln in _joined(run_text).splitlines() if not _INSTALL_LINE.match(ln))
    if not commands.strip() or "--notest" in commands or _PREPARES.search(name):
        return False
    return bool(TEST_WORDS.search(commands) or TEST_WORDS.search(name))


def _joined(run_text: str) -> str:
    """A step's command with its backslash continuations joined (rdflib: `task \\` then `gha:validate`)."""
    return re.sub(r"\\\n\s*", " ", run_text)


def test_job(repo: Path, rev: str, fallback: tuple[str, str] | None) -> tuple[str, str] | None:
    """The job that runs the project's tests, as the team named it: a workflow called test(s)/ci/check whose job has
    a step that runs tests on Linux (pipx, campaign 13: `tests.yml` job `test` through tox, where the reconstruction's
    ranking took a job that only lists packages); else `fallback` (the CI plan's choice)."""
    listed = subprocess.run(["git", "-C", str(repo), "ls-tree", "--name-only", f"{rev}:.github/workflows"],
                            capture_output=True, text=True, check=False).stdout.split()  # fmt: skip
    found: list[tuple[int, str, str]] = []
    for name in (n for n in listed if n.endswith((".yml", ".yaml"))):
        shown = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:.github/workflows/{name}"],
                               capture_output=True, text=True, check=False).stdout  # fmt: skip
        try:
            data = yaml.safe_load(shown) or {}
        except yaml.YAMLError:
            continue
        triggers = json.dumps(data.get("on", data.get(True, "")))
        if not re.search(r"push|pull_request", triggers):
            continue  # a scheduled or manual workflow is not what checks a change
        for job, definition in (data.get("jobs") or {}).items():
            if not isinstance(definition, dict) or "self-hosted" in json.dumps(definition.get("runs-on", "")):
                continue
            steps = [st for st in definition.get("steps") or [] if isinstance(st, dict)]
            if not any(TEST_WORDS.search(_joined(str(st.get("run", "")))) for st in steps):
                continue
            canonical = name.rsplit(".", 1)[0].lower() in ("test", "tests", "ci", "check", "checks", "validate")
            named = job.lower() in ("test", "tests", "pytest", "unit", "validate", "unittests")
            found.append(((0 if named else 2) + (0 if canonical else 1), name, job))
    if found:
        _, name, job = sorted(found)[0]
        return name, job
    return fallback


def _steps(log: str) -> list[tuple[str, bool]]:
    found: list[tuple[str, bool]] = []
    for line in log.splitlines():
        if (m := _STEP.search(line)) is not None:
            found.append((m.group("name").strip(), m.group(2) == "Success"))
    return found


def prepared_well(steps: list[tuple[str, bool]], job_text: str) -> tuple[bool, str]:
    """Whether the environment is usable: no step failed, or the first failure is a test step (the project's own
    tests failing say nothing against the environment). Returns the first failing step otherwise."""
    for name, ok in steps:
        if ok or name.startswith("unbidden:"):
            continue
        if _runs_tests(job_text, name) or (TEST_WORDS.search(name) and not _PREPARES.search(name)):
            return True, ""
        return False, name
    return True, ""


def _runs_tests(job_text: str, name: str) -> bool:
    """Whether the step called `name` in the job is one that runs tests (the same rule as the measured command)."""
    data = yaml.safe_load(job_text) or {}
    for definition in (data.get("jobs") or {}).values():
        for step in definition.get("steps") or []:
            if str(step.get("name") or "") == name and runs_tests(name, str(step.get("run", ""))):
                return True
    return False


def _container_for(workspace: Path, docker: str) -> str | None:
    """The act job container whose workspace is this directory (act names them after the workflow and job)."""
    listed = subprocess.run([docker, "ps", "-a", "--filter", "name=act-", "--format", "{{.Names}}"],
                            capture_output=True, text=True).stdout.split()  # fmt: skip
    for name in listed:
        mounts = subprocess.run([docker, "inspect", name, "--format", "{{range .Mounts}}{{.Source}}\n{{end}}"],
                                capture_output=True, text=True).stdout.split()  # fmt: skip
        if any(Path(m).resolve() == workspace.resolve() for m in mounts):
            return name
    return None


def _cleanup(container: str, docker: str) -> None:
    """The job's container, its service containers, per-job volumes and network; the shared tool cache stays."""
    prefix = container.split("-", 1)[0] + "-" + container.split("-", 1)[1][:60]
    for name in subprocess.run([docker, "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
                               capture_output=True, text=True).stdout.split():  # fmt: skip
        subprocess.run([docker, "rm", "-f", name], capture_output=True)
    for volume in subprocess.run([docker, "volume", "ls", "--filter", f"name={prefix}", "--format", "{{.Name}}"],
                                 capture_output=True, text=True).stdout.split():  # fmt: skip
        if volume != TOOLCACHE:
            subprocess.run([docker, "volume", "rm", "-f", volume], capture_output=True)
    for network in subprocess.run([docker, "network", "ls", "--filter", f"name={prefix}", "--format", "{{.Name}}"],
                                  capture_output=True, text=True).stdout.split():  # fmt: skip
        subprocess.run([docker, "network", "rm", network], capture_output=True)


def _job_env(raw: str) -> dict[str, str]:
    """The job's environment at its end, without the runner's tokens and per-run plumbing."""
    env: dict[str, str] = {}
    for item in raw.split("\0"):
        key, sep, value = item.partition("=")
        if not sep or not key or re.match(r"^(ACTIONS_|INPUT_|GITHUB_TOKEN|RUNNER_TEMP|HOSTNAME$|ImageOS$)", key):
            continue
        env[key] = value
    return env


def with_unbidden_tools(tag: str, docker: str, run: Callable[..., Any] = subprocess.run) -> str:
    """Unbidden's pinned analyzers (ruff, pytest; pyright on the runner's Node) in a layer over the prepared image,
    in /opt/tools, last on PATH: the scan and the labs run them as in Unbidden's own images."""
    import tempfile

    from unbidden.sandbox.provision import PYRIGHT_VERSION, PYTEST_VERSION, RUFF_VERSION

    final = f"{tag}-tools"
    dockerfile = (
        f"FROM {tag}\n"
        "RUN (python3 -m venv /opt/tools || (apt-get install -y python3-venv && python3 -m venv /opt/tools)) \\\n"
        f" && /opt/tools/bin/pip install --no-cache-dir ruff=={RUFF_VERSION} pytest=={PYTEST_VERSION} \\\n"
        f" && (command -v npm >/dev/null && npm install -g pyright@{PYRIGHT_VERSION} >/dev/null || true)\n"
    )
    with tempfile.TemporaryDirectory(prefix="unbidden-ci-tools-") as tmp:
        (Path(tmp) / "Dockerfile").write_text(dockerfile)
        built = run([docker, "build", "-q", "-t", final, tmp], capture_output=True, text=True)
    if built.returncode != 0:
        raise NotPreparable(f"Unbidden's analyzers could not be added to the prepared image: {built.stderr[-300:]}")
    return final


def prepare(
    repo: Path,
    rev: str,
    workflow: str,
    job: str,
    *,
    act: str | None = None,
    docker: str = "docker",
    progress: Progress = lambda _: None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CiEnvironment:
    """Run the team's test job once with the network and keep what it prepared as an image (cached per commit, job
    and filtered workflow). Raises NotPreparable when it cannot, with the reason."""
    act = act or act_path()
    if act is None:
        raise NotPreparable("act is not installed (the team's CI job cannot run here; `brew install act`)")
    text, matrix, skipped = filtered_job(repo, rev, workflow, job)
    runner = ensure_runner_image(docker)
    key = hashlib.sha256(f"{RECORD_VERSION}|{rev}|{text}|{runner}".encode()).hexdigest()[:16]
    root = cache_root() / key
    record_path = root / "environment.json"
    tag = f"unbidden-ci:{key}"
    if record_path.exists() and run([docker, "image", "inspect", tag], capture_output=True).returncode == 0:
        known = json.loads(record_path.read_text())
        known["image"] = DependencyImage(**{**known["image"], "volumes": tuple(known["image"]["volumes"]),
                                            "setup": tuple(known["image"]["setup"]),
                                            "notes": tuple(known["image"]["notes"])})  # fmt: skip
        known["steps"] = [tuple(s) for s in known["steps"]]
        return CiEnvironment(**known)
    workspace = (root / "ws").resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    snapshot(repo, rev, workspace)
    with_git(workspace, rev)
    (workspace / WORKFLOW).parent.mkdir(parents=True, exist_ok=True)
    (workspace / WORKFLOW).write_text(text)
    argv = [act, "push", "-j", job, "-W", WORKFLOW, "-P", f"ubuntu-latest={runner}", "--pull=false",
            "--container-daemon-socket", "-", "--bind", "--reuse"]  # fmt: skip
    progress(f"running the team's CI job {workflow}:{job} to prepare the environment (with the network)")
    started = time.monotonic()
    try:
        done = run(argv, cwd=workspace, capture_output=True, text=True, timeout=JOB_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise NotPreparable(f"the CI job did not finish within {JOB_TIMEOUT_S:.0f} s") from exc
    seconds = round(time.monotonic() - started, 1)
    log = (done.stdout or "") + (done.stderr or "")
    steps = _steps(log)
    container = _container_for(workspace, docker)
    if container is None:
        raise NotPreparable(f"the CI job left no container (act exit {done.returncode}): {log[-600:]}")
    try:
        dumped = run([docker, "exec", container, "cat", ENV_FILE], capture_output=True, text=True)
        if dumped.returncode != 0:
            raise NotPreparable(f"the CI job ended before its environment was kept: {log[-600:]}")
        usable, failed_at = prepared_well(steps, text)
        if not usable:
            raise NotPreparable(f"the CI job failed at `{failed_at}` before its tests: {_tail(log)}")
        committed = run([docker, "commit", container, tag], capture_output=True, text=True)
        if committed.returncode != 0:
            raise NotPreparable(f"the prepared container could not be kept: {committed.stderr[-300:]}")
    finally:
        _cleanup(container, docker)
    tag = with_unbidden_tools(tag, docker, run)
    env = {**_job_env(dumped.stdout), "UV_OFFLINE": "1", "PIP_NO_INDEX": "1", "CI": "true", "GITHUB_ACTIONS": "true"}
    env["PATH"] = f"{env.get('PATH', '/usr/local/bin:/usr/bin:/bin')}:/opt/tools/bin"  # the team's tools first
    # The runner's per-step files (a step appends to its summary or outputs): scratch files here, read by nothing
    # (traefik-manager, campaign 13: `>> $GITHUB_STEP_SUMMARY` failed the measured step).
    for name in ("GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT", "GITHUB_ENV", "GITHUB_PATH", "GITHUB_STATE"):
        env[name] = f"/tmp/{name.lower()}"
    mount = str(workspace)
    image = DependencyImage(
        tag=tag, language="python", registries=[], env=env, links={},
        setup=(f"cp -an {PREPARED}/. {mount}/ 2>/dev/null || true", f"ln -sfn {mount} /work 2>/dev/null || true",
               "mkdir -p /var/run/act/workflow"),
        notes=(f"environment prepared by the team's CI job {workflow}:{job}"
               + (f" ({', '.join(f'{k}={v}' for k, v in matrix.items())})" if matrix else "")
               + (f"; publishing steps left out: {', '.join(skipped)}" if skipped else ""),),
        mount=mount, volumes=(f"{TOOLCACHE}:/opt/hostedtoolcache",), runner_like=True,
        test_command=test_command(text, step_scripts(log)),
        ci_tests_failed=any(not ok and _runs_tests(text, name) for name, ok in steps),
    )  # fmt: skip
    environment = CiEnvironment(image=image, workflow=workflow, job=job, matrix=matrix, skipped=skipped, steps=steps,
                                job_ok=done.returncode == 0, seconds=seconds, log_tail=_tail(log))  # fmt: skip
    record_path.write_text(json.dumps(asdict(environment), default=list))
    return environment


def _tail(log: str, keep: int = 1200) -> str:
    lines = [ln for ln in log.splitlines() if "unable to get git ref" not in ln]
    return "\n".join(lines)[-keep:]
