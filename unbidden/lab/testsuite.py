"""Run a repository's own test suite in the sandbox, several rounds, and report failing test names."""

from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.contracts.experiment import INFRA_FAILED, NOT_COLLECTED, RAN, SUITE, TestSummary
from unbidden.languages import adapter
from unbidden.observe.ci import ci_test_plan
from unbidden.observe.compose import Service, load_compose
from unbidden.observe.stack import Stack
from unbidden.sandbox.provision import DependencyImage, sandbox_spec
from unbidden.sandbox.runner import SandboxResult, SandboxRunner, SandboxSpec
from unbidden.sandbox.sidecars import data_services


@dataclass(frozen=True)
class TestPlan:
    """How to run a repository's tests: the command, the services it needs and the app's environment."""

    __test__ = False  # not a pytest test class

    argv: tuple[str, ...]
    source: str  # where the plan came from, shown in verdicts
    pytest: bool  # whether a JUnit report is expected (pytest honours PYTEST_ADDOPTS)
    services: tuple[Service, ...] = ()
    env: dict[str, str] = field(default_factory=dict[str, str])
    report: str = "junit"  # how failures are read: the language adapter's test_report
    # What the plan covers: the whole job, or one of the groups the CI splits it into (`partial`); a run of a part is
    # never reported as the suite.
    scope: str = "the whole job"
    partial: bool = False
    notes: tuple[str, ...] = ()


def test_plan(repo: Path, rev: str, stack: Stack, language: str) -> TestPlan | None:
    """The repository's own CI job when there is one, else the stack's default test command."""
    compose = load_compose(repo, rev)
    directory = "."
    if language == "python" and stack.python is not None and stack.python.members:
        directory = stack.python.members[0]
    app = compose.app_service_for(directory) if compose is not None else None
    env = {k: v for k, v in app.environment.items() if v} if app is not None else {}
    lang = adapter(language)
    # A language whose own test command names each failure (go test -json) uses it rather than a CI script that
    # only passes or fails as a whole.
    ci = ci_test_plan(repo, rev, language) if lang.test_report in ("junit", "exit") else None
    if ci is not None:
        named = [compose.services[n] for n in ci.services if n in compose.services] if compose is not None else []
        services = tuple(s for s in named if s.image and not s.build_context)
        # The job's own service containers, as the CI starts them; there they are reached at localhost on their
        # ports, here by their name on the sidecars' network: the job's environment is pointed at them.
        own = tuple(
            Service(name=n, image=image, build_context=None, dockerfile=None, environment=dict(e), depends_on=(),
                    ports=tuple(str(p) for p in ports))
            for n, image, e, ports in ci.containers
        )  # fmt: skip
        # Every container the job declares, not only databases (mealie, stage 10: an LDAP server its login tests
        # need, skipped in CI only where `GITHUB_ACTIONS` is unset).
        own = tuple(s for s in own if s.image)
        ci_env = dict(ci.env)
        if own:
            ci_env = {k: _to_sidecars(v, own, k) for k, v in ci_env.items()}
        # The job's own environment, with or without service containers (rag-api, stage 10: the test step's
        # OPENAI_API_KEY=test_key, without which importing the application fails). The compose file's environment
        # is the application container's, not the job's: CTFd's `UPLOAD_FOLDER=/var/uploads` and
        # `DATABASE_URL=...@db` reached its tests and failed them (stage 10, level A). A job that starts the
        # compose file's services runs its tests against them, with that environment (fst).
        env = {**(env if ci.services else {}), **ci_env}
        notes = list(ci.notes)
        if ci.interpreters and language == "python" and stack.python is not None:
            # The job's own interpreter install, resolved when the image was provisioned (no download in the run).
            have = stack.python.version
            wanted = [v for v in ci.interpreters if re.match(r"^3\.\d+", v)]
            if all(re.match(r"^3\.\d+", v).group(0) == have for v in wanted):  # type: ignore[union-attr]
                notes.append(f"the job's `uv python install {' '.join(ci.interpreters)}` is satisfied by the image's "
                             f"Python {have}, chosen when it was provisioned")  # fmt: skip
            else:
                notes.append(f"the job installs Python {' '.join(ci.interpreters)}; the image has {have}: not the "
                             "CI's interpreter (the image could not be provisioned with it)")  # fmt: skip
        return TestPlan(
            argv=("bash", "-c", ci.script()),
            source=f"CI {ci.workflow} > {ci.job}"
            + (f" (its services: {', '.join(s.name for s in own)})" if own else ""),
            pytest=language == "python",
            services=(*services, *own),
            env=env,
            scope=ci.scope,
            partial=ci.partial,
            notes=tuple(notes),
        )
    argv = _default_argv(stack, language)
    if argv is None:
        return None
    services = ()
    if compose is not None and app is not None:
        services = tuple(s for s in compose.data_services() if s.name in app.depends_on)
    return TestPlan(argv=tuple(argv), source=" ".join(argv), pytest=language == "python", services=services, env=env,
                    report=lang.test_report)  # fmt: skip


def _to_sidecars(value: str, services: tuple[Service, ...], key: str = "") -> str:
    """`localhost` (or 127.0.0.1) in a CI value, where the job reached its service containers, becomes the name of
    the service that listens on that port; without a port, the scheme's default port, then the engine the variable
    names (`POSTGRES_SERVER=localhost` beside an LDAP container: mealie, stage 10), then the only service."""

    def host(match: re.Match[str]) -> str:
        port = match.group("port")
        # A URL without a port uses its scheme's (stage 10, Prefect: `postgresql+asyncpg://...@localhost/prefect`
        # beside a Redis service).
        known = port.lstrip(":") if port else _DEFAULT_PORTS.get((match.group("scheme") or "").split("+")[0], "")
        named = [s for s in services if known and known in s.ports]
        hint = f"{key} {match.group('scheme') or ''}".lower()
        if not named and hint.strip():
            named = [s for s in services if (s.data_kind and s.data_kind in hint) or s.name.lower() in hint]
            named = named or [s for s in services if s.data_kind == "postgres" and ("pg" in hint or "db" in hint)]
        if not named and len(services) > 1:
            named = [s for s in services if s.data_kind] if sum(1 for s in services if s.data_kind) == 1 else []
        target = named[0].name if named else (services[0].name if len(services) == 1 else match.group("host"))
        return (match.group("prefix") or "") + target + (port or "")

    return re.sub(r"(?P<prefix>(?P<scheme>[a-z][a-z0-9.]*)(?:\+[a-z0-9]+)?://(?:[^@/\s]*@)?)?"
                  r"(?P<host>localhost|127\.0\.0\.1)(?P<port>:\d+)?", host, value)  # fmt: skip


_DEFAULT_PORTS = {"postgres": "5432", "postgresql": "5432", "mysql": "3306", "mariadb": "3306", "redis": "6379",
                  "mongodb": "27017", "amqp": "5672"}  # fmt: skip


JUNIT_DIR = ".unbidden-junit"
NETWORK_ERRORS = (
    "Temporary failure in name resolution",
    "Network is unreachable",
    "Name or service not known",
    "getaddrinfo failed",
    "Could not resolve host",
    "because the network was disabled",  # uv offline (UV_OFFLINE) missing a package in its cache
    "dns error",
    "NameResolutionError",
)


# Offline, pip and uv only read their caches: a package an isolated build or a tox rebuild needs and the job never
# cached is not found (oauthlib, campaign 13: `setuptools>=77.0.3` for tox's sdist build).
OFFLINE_MISSES = ("No matching distribution found", "Could not find a version that satisfies",
                  "because the network was disabled")  # fmt: skip


def offline_miss(output: str) -> bool:
    """In an environment the team's CI job prepared: a run that stopped for something the network would have given."""
    return needs_network(output) or any(marker in output for marker in OFFLINE_MISSES)


def needs_network(output: str) -> bool:
    """Tests that fail only because the sandbox is offline say nothing about the change under test."""
    return any(marker in output for marker in NETWORK_ERRORS)


def _default_argv(stack: Stack, language: str) -> list[str] | None:
    part = stack.part(language)
    return adapter(language).test_argv(part) if part is not None else None


def _junit_failures(path: Path) -> list[str] | None:
    report = _junit(path)
    return report[0] if report is not None else None


MESSAGES_KEPT = 20
TEXTS_KEPT = 10  # failures whose whole report is kept (a repair reads their tracebacks)
TEXT_CHARS = 6000
# A failure that is the environment's, not the code's: the test asked for an executable the sandbox image does not
# hold (a bare name: `git`, `msgfmt`; a CI runner has them, the dependency image only what the project installs).
MISSING_TOOL = re.compile(r"(?:FileNotFoundError|OSError): \[Errno 2\] No such file or directory: '(?P<tool>[\w.+-]+)'")


_MISSING_COMMAND = re.compile(
    r"(?:^|\n)[^\n]*?(?:line \d+: )?(?P<a>[\w.+-]+): command not found|command not found: (?P<b>[\w.+-]+)"
)
# Where a missing program would come from: Debian's archive (the mandate's package registries), or an installer the
# CI runs that no registry stands for.
PROVIDES = {
    "make": "Debian's `make`", "git": "Debian's `git`", "msgfmt": "Debian's `gettext`", "gettext": "Debian's `gettext`",
    "gcc": "Debian's `build-essential`", "cc": "Debian's `build-essential`", "g++": "Debian's `build-essential`",
    "pkg-config": "Debian's `pkg-config`", "cmake": "Debian's `cmake`",
    "task": "go-task, which its CI installs with an action (go-task/setup-task), not from a package registry",
    "just": "just, which its CI installs with an action, not from a package registry",
}  # fmt: skip


def environment_lacks(result: SandboxResult) -> str | None:
    """A test command that stopped at a program the image lacks (`task: command not found`, rdflib; `make`,
    graphtage; `msgfmt`, humanize: campaign 12), named with what would provide it; None when the run says otherwise."""
    text = result.stderr + "\n" + result.stdout
    if re.search(
        r"\bsu: (?:Authentication failure|must be run from a terminal)|\bsudo: .*(?:not found|password)", text
    ):
        # dinkydash, campaign 12: a CI step that switches user; the sandbox has no root to switch from.
        return "the test command switches user (`su`/`sudo`), which the sandbox never allows: no root, no password"
    if re.search(r"Temporary failure in name resolution|NameResolutionError|Could not resolve host|"
                 r"getaddrinfo failed|Network is unreachable", text):  # fmt: skip
        # pipx, campaign 12: a test installs from PyPI; the sandbox has no network by design.
        return "the tests reach the network (a name did not resolve), which the sandbox never has"
    found = _MISSING_COMMAND.search(text)
    if found is None:
        return None
    tool = (found.group("a") or found.group("b")).rsplit("/", 1)[-1]
    source = PROVIDES.get(tool)
    how = (
        f"{source}; it is installed when the mandate's package registries allow deb.debian.org"
        if source and source.startswith("Debian")
        else source or "not a package the sandbox knows how to install"
    )
    return f"the sandbox image lacks `{tool}`, which the test command needs ({how})"


def missing_tool(message: str) -> str | None:
    """The executable a failure's message says the environment lacks, or None when the failure says something else."""
    found = MISSING_TOOL.search(message)
    return found.group("tool") if found else None


def _junit(path: Path) -> tuple[list[str], int, dict[str, str], dict[str, str], dict[str, str]] | None:
    """Failing test names, how many test cases the report holds, each failure's message (its first lines, for the
    first `MESSAGES_KEPT`) and, over every failure, the executable the environment lacks when the message names one
    (test -> tool); or None without a report."""
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    failed: list[str] = []
    messages: dict[str, str] = {}
    lacking: dict[str, str] = {}
    texts: dict[str, str] = {}  # the whole report of the first failures (traceback included), for a repair
    cases = 0
    for case in root.iter("testcase"):
        cases += 1
        problem = case.find("failure") if case.find("failure") is not None else case.find("error")
        if problem is not None:
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            failed.append(name)
            text = (problem.get("message") or problem.text or "").strip()
            if len(messages) < MESSAGES_KEPT:
                messages[name] = "\n".join(text.splitlines()[:4])[:400]
            if len(texts) < TEXTS_KEPT:
                whole = f"{case.get('file') or ''}\n{problem.get('message') or ''}\n{problem.text or ''}"
                texts[name] = whole[-TEXT_CHARS:]
            tool = missing_tool(text) or missing_tool(problem.text or "")
            if tool:
                lacking[name] = tool
    return failed, cases, messages, lacking, texts


@dataclass(frozen=True)
class Round:
    failed: list[str] | None  # None: the run said nothing about the code
    status: str  # RAN, NOT_COLLECTED or INFRA_FAILED
    collected: int | None  # test cases the runner reported; None when it does not say
    why: str | None = None  # for a round that told nothing about the code: how the run ended, and its last output
    messages: dict[str, str] = field(default_factory=dict[str, str])  # the report's message per failure (first ones)
    retry: bool = True  # whether running the round again could tell more (a tool the image lacks will still be missing)
    # Tests that could not run because the sandbox image lacks an executable (test -> tool): the environment's, not
    # the code's; kept apart from `failed` so a reader sees both counts.
    could_not_run: dict[str, str] = field(default_factory=dict[str, str])
    texts: dict[str, str] = field(default_factory=dict[str, str])  # whole reports of the first failures

    @property
    def meaningful(self) -> bool:
        return self.status != INFRA_FAILED


def _round(
    runner: SandboxRunner,
    work: Path,
    image: DependencyImage,
    plan: TestPlan,
    n: int,
    timeout_s: float,
    workers: int | None = None,
    network: str | None = None,
) -> Round:
    """One round: failing test names, whether the suite ran and collected tests, and how many.

    Each round gets fresh services, so no round sees what an earlier one wrote.
    """
    junit = work / JUNIT_DIR / f"round-{n}.xml"
    junit.parent.mkdir(exist_ok=True)
    junit.parent.chmod(0o777)
    env = dict(plan.env)
    # A repository script that says `uv run ...` (starlette's `scripts/test`) must not sync the project: the
    # dependency image is the environment, and /work's build backend is not fetchable offline.
    env.setdefault("UV_NO_SYNC", "1")
    if plan.pytest:
        env["PYTEST_ADDOPTS"] = f"--junitxml=/work/{JUNIT_DIR}/round-{n}.xml -p no:cacheprovider"
        # `pytest -n auto` counts the host's CPUs, not the sandbox's: on a large machine it starts more workers than
        # the sandbox's memory holds, and the round dies of it (mealie, D-035). As many workers as the sandbox has CPUs.
        env.setdefault("PYTEST_XDIST_AUTO_NUM_WORKERS", str(int(SandboxSpec.cpus)))
        if workers is not None:  # the retry of a round whose workers died: less parallelism, the same limits
            env["PYTEST_XDIST_AUTO_NUM_WORKERS"] = str(workers)
    with data_services(list(plan.services)) as sidecars:
        spec = sandbox_spec(
            image,
            list(plan.argv),
            public_env=env,
            timeout_s=timeout_s,
            network=network or (sidecars.network if sidecars else "none"),
        )
        if network == "bridge":
            # The rerun with the network: pip and uv may use it (the prepared image keeps them offline otherwise).
            from dataclasses import replace

            spec = replace(spec, env={**spec.env, "PIP_NO_INDEX": "0", "UV_OFFLINE": "false"})
        result = runner.run(spec, work)
    if plan.report == "go-test-json":
        from unbidden.languages.golang import go_test_count, go_test_failures

        names = go_test_failures(result.stdout)
        if names is None:
            return Round(None, INFRA_FAILED, None, _ended(result))  # no test event at all: retried once, then counted
        count = go_test_count(result.stdout)
        return Round(names, RAN if count else NOT_COLLECTED, count)
    report = _junit(junit)
    if plan.pytest and result.exit_code == 5:
        return Round([], NOT_COLLECTED, 0)  # pytest: no tests collected
    if report is None and not result.ok and (lacks := environment_lacks(result)) is not None:
        # The command needs a program the image does not have: the environment's, said with what would provide it,
        # and not run again (the program would still be missing).
        return Round(None, INFRA_FAILED, None, f"{lacks}; {_ended(result)}", retry=False)
    if report is None and plan.pytest and not result.ok:
        # Nothing reached pytest's report: setup failed or the run crashed. Retried once, then counted.
        return Round(None, INFRA_FAILED, None, _ended(result))
    if report is None and plan.pytest:
        # Exit 0 and no test report: the command ran no test (stage 10, codex-lb: a skip step's echo). An exit code
        # is not evidence that tests ran; the report is.
        return Round([], NOT_COLLECTED, 0, f"{_ended(result)} (no test report: no test ran)")
    names, collected = (report[0], report[1]) if report is not None else (None, None)
    messages = report[2] if report is not None else {}
    texts = report[4] if report is not None else {}
    lacking = report[3] if report is not None else {}  # test -> executable the environment lacks
    if names and any(n == "pytest::internal" for n in names):
        # pytest itself crashed (TimeTracker, stage 10: an xdist worker died at the sandbox's limits, `Broken pipe`
        # to execnet): the run told nothing about the code; retried once with one worker.
        return Round(None, INFRA_FAILED, None, _ended(result))
    # A failure whose message says the environment lacks an executable is the environment's, not the code's
    # (codex-lb, campaign 12, level A: 30 of 6,422 tests raised FileNotFoundError for `git`, which the dependency
    # image does not hold). Those tests could not run: they leave `failed` and are kept apart with the tool named,
    # so a reader sees both counts. When nothing else failed, the round is an environment failure and is not run
    # again (the tool would still be missing).
    could_not_run = {n: lacking[n] for n in names if n in lacking} if names else {}
    lacks = ", ".join(f"`{t}`" for t in sorted(set(could_not_run.values())))
    if could_not_run:
        names = [n for n in names or [] if n not in could_not_run]
        if not names:
            why = (f"the sandbox image lacks {lacks}: {len(could_not_run)} of {collected} tests could not run "
                   f"(FileNotFoundError); no test failed for another reason")  # fmt: skip
            return Round([], INFRA_FAILED, collected, why, messages, retry=False, could_not_run=could_not_run)
    if names and needs_network(result.stdout + result.stderr):
        names = [f"{n} (needs network)" for n in names]
    if names is None:
        names = [] if result.ok else [SUITE]
    elif not names and not result.ok:
        names = [SUITE]
    status = NOT_COLLECTED if collected == 0 else RAN
    # What the run printed last, kept when something failed: the record then says why (stage 10, level A:
    # TimeTracker's `pytest::internal` and CTFd's 50 failures were names without a cause).
    why = _ended(result) if names else None
    if could_not_run:
        note = f"{len(could_not_run)} test(s) could not run: the sandbox image lacks {lacks}"
        why = f"{why}; {note}" if why else note
    return Round(sorted(names), status, collected, why, messages, could_not_run=could_not_run, texts=texts)


def _ended(result: SandboxResult) -> str:
    """How a run that reached no test report ended: its exit, and the last lines it printed."""
    how = "timed out" if result.timed_out else f"exit {result.exit_code}"
    text = result.stderr.strip() or result.stdout.strip()
    # pytest's own crash is reported where it happened, not at the end (TimeTracker, stage 10: 1500 characters of
    # Alembic's log after an `internal error`): the first INTERNALERROR block is what explains the run.
    internal = re.search(r"(?:^INTERNALERROR>.*\n?){1,40}", result.stdout, re.M)
    tail = (internal.group(0)[:1500] + "\n...\n" if internal else "") + text[-1500:]
    return f"{how}: {tail}" if tail else f"{how}, nothing printed"


def without_coverage(plan: TestPlan) -> TestPlan | None:
    """The plan with pytest's coverage flags removed from its command; None when it has none."""
    from dataclasses import replace

    from unbidden.observe.ci import _COV_FLAG  # pyright: ignore[reportPrivateUsage]

    argv = tuple(_COV_FLAG.sub("", a) if "pytest" in a or a.startswith("--cov") else a for a in plan.argv)
    argv = tuple(a for a in argv if a and not a.startswith(("--cov", "--no-cov")))
    return replace(plan, argv=argv) if argv != plan.argv else None


def run_suite(
    runner: SandboxRunner,
    work: Path,
    image: DependencyImage,
    plan: TestPlan,
    *,
    rounds: int = 3,
    timeout_s: float = 900,
) -> TestSummary:
    failed_per_round: list[list[str]] = []
    statuses: list[str] = []
    collected: list[int | None] = []
    why: list[str | None] = []
    messages: dict[str, str] = {}
    could_not_run: dict[str, str] = {}
    texts: dict[str, str] = {}
    from unbidden.sandbox.runner import with_git

    command = getattr(image, "test_command", None)
    if command:
        # An environment the team's CI job prepared: its own test steps run, verbatim, in it (offline). tox keeps
        # its environments clean, so it is told to pass pytest's report option through.
        from dataclasses import replace

        from unbidden.sandbox.ci_env import localhost_forwards

        env = {**dict(plan.env), "TOX_OVERRIDE": "testenv.pass_env+=PYTEST_ADDOPTS"}
        # The job's services answer on localhost, as in its CI (they run as sidecars, reached by name).
        forwards = localhost_forwards([(s.name, str(p).split(":")[-1].split("/")[0]) for s in plan.services
                                       for p in s.ports])  # fmt: skip
        script = f"{forwards}\n{command}" if forwards else command
        plan = replace(plan, argv=("bash", "-c", f"set -e\n{script}"), pytest=True, env=env,
                       source=f"the team's CI job, verbatim: {command[:200]}")  # fmt: skip

    with_git(work, "the measured revision", exclude=list(getattr(image, "links", None) or {}))
    n = 0
    for _ in range(rounds):
        result = Round(None, INFRA_FAILED, None)
        first_why = None
        for attempt in range(2):  # a round that tells nothing about the code is run once more, with one worker
            n += 1
            result = _round(runner, work, image, plan, n, timeout_s, workers=1 if attempt else None)
            if (
                not result.meaningful
                and "unrecognized arguments: --cov" in (result.why or "")
                and (uncovered := without_coverage(plan)) is not None
            ):
                # The team's coverage plugin is not installed here (python-mss, campaign 12: pytest's usage error,
                # exit 4): coverage is their report, not what is measured; the round runs without its flags.
                plan = uncovered
                n += 1
                result = _round(runner, work, image, plan, n, timeout_s)
                note = "coverage flags left out: pytest-cov is not installed here"
                told = "; ".join(filter(None, [result.why, note]))
                result = Round(result.failed, result.status, result.collected, told, result.messages,
                               retry=result.retry, could_not_run=result.could_not_run)  # fmt: skip
            if not result.meaningful and getattr(image, "runner_like", False) and offline_miss(result.why or ""):
                # The team's CI job prepared this environment and the mandate let it use the network: a step that
                # still needs it (a rebuild resolving its backend) runs again with the network, said in the record.
                n += 1
                again = _round(runner, work, image, plan, n, timeout_s, network="bridge")
                note = "rerun with the network: the offline run needed it"
                result = Round(again.failed, again.status, again.collected,
                               "; ".join(filter(None, [again.why, note])), again.messages, retry=again.retry,
                               could_not_run=again.could_not_run)  # fmt: skip
            if result.meaningful:
                if first_why:
                    result = Round(result.failed, result.status, result.collected,
                                   f"first attempt told nothing ({first_why[:300]}); retried with one xdist worker",
                                   result.messages)  # fmt: skip
                break
            if not result.retry:
                break
            first_why = result.why
        failed_per_round.append(result.failed if result.failed is not None else [SUITE])
        statuses.append(result.status)
        collected.append(result.collected)
        why.append(result.why)
        messages = messages or dict(result.messages)
        texts = texts or dict(result.texts)
        could_not_run = could_not_run or dict(result.could_not_run)
    shutil.rmtree(work / JUNIT_DIR, ignore_errors=True)
    return TestSummary(
        rounds=rounds,
        failed_per_round=failed_per_round,
        round_status=statuses,
        collected_per_round=collected,
        infra_why=why,
        failure_messages=messages,
        failure_texts=texts,
        could_not_run=could_not_run,
    )
