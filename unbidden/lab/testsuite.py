"""Run a repository's own test suite in the sandbox, several rounds, and report failing test names."""

from __future__ import annotations

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
from unbidden.sandbox.runner import SandboxRunner, SandboxSpec
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
        return TestPlan(
            argv=("bash", "-c", ci.script()),
            source=f"CI {ci.workflow} > {ci.job}",
            pytest=language == "python",
            services=services,
            env=env,
        )
    argv = _default_argv(stack, language)
    if argv is None:
        return None
    services = ()
    if compose is not None and app is not None:
        services = tuple(s for s in compose.data_services() if s.name in app.depends_on)
    return TestPlan(argv=tuple(argv), source=" ".join(argv), pytest=language == "python", services=services, env=env,
                    report=lang.test_report)  # fmt: skip


JUNIT_DIR = ".unbidden-junit"
NETWORK_ERRORS = (
    "Temporary failure in name resolution",
    "Network is unreachable",
    "Name or service not known",
    "getaddrinfo failed",
    "Could not resolve host",
)


def needs_network(output: str) -> bool:
    """Tests that fail only because the sandbox is offline say nothing about the change under test."""
    return any(marker in output for marker in NETWORK_ERRORS)


def _default_argv(stack: Stack, language: str) -> list[str] | None:
    part = stack.part(language)
    return adapter(language).test_argv(part) if part is not None else None


def _junit_failures(path: Path) -> list[str] | None:
    report = _junit(path)
    return report[0] if report is not None else None


def _junit(path: Path) -> tuple[list[str], int] | None:
    """Failing test names and how many test cases the report holds, or None without a report."""
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    failed: list[str] = []
    cases = 0
    for case in root.iter("testcase"):
        cases += 1
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(f"{case.get('classname', '')}::{case.get('name', '')}")
    return failed, cases


@dataclass(frozen=True)
class Round:
    failed: list[str] | None  # None: the run said nothing about the code
    status: str  # RAN, NOT_COLLECTED or INFRA_FAILED
    collected: int | None  # test cases the runner reported; None when it does not say

    @property
    def meaningful(self) -> bool:
        return self.status != INFRA_FAILED


def _round(
    runner: SandboxRunner, work: Path, image: DependencyImage, plan: TestPlan, n: int, timeout_s: float
) -> Round:
    """One round: failing test names, whether the suite ran and collected tests, and how many.

    Each round gets fresh services, so no round sees what an earlier one wrote.
    """
    junit = work / JUNIT_DIR / f"round-{n}.xml"
    junit.parent.mkdir(exist_ok=True)
    junit.parent.chmod(0o777)
    env = dict(plan.env)
    if plan.pytest:
        env["PYTEST_ADDOPTS"] = f"--junitxml=/work/{JUNIT_DIR}/round-{n}.xml -p no:cacheprovider"
        # `pytest -n auto` counts the host's CPUs, not the sandbox's: on a large machine it starts more workers than
        # the sandbox's memory holds, and the round dies of it (mealie, D-035). As many workers as the sandbox has CPUs.
        env.setdefault("PYTEST_XDIST_AUTO_NUM_WORKERS", str(int(SandboxSpec.cpus)))
    with data_services(list(plan.services)) as sidecars:
        spec = sandbox_spec(
            image,
            list(plan.argv),
            public_env=env,
            timeout_s=timeout_s,
            network=sidecars.network if sidecars else "none",
        )
        result = runner.run(spec, work)
    if plan.report == "go-test-json":
        from unbidden.languages.golang import go_test_count, go_test_failures

        names = go_test_failures(result.stdout)
        if names is None:
            return Round(None, INFRA_FAILED, None)  # no test event at all: retried once, then counted
        count = go_test_count(result.stdout)
        return Round(names, RAN if count else NOT_COLLECTED, count)
    report = _junit(junit)
    if plan.pytest and result.exit_code == 5:
        return Round([], NOT_COLLECTED, 0)  # pytest: no tests collected
    if report is None and plan.pytest and not result.ok:
        # Nothing reached pytest's report: setup failed or the run crashed. Retried once, then counted.
        return Round(None, INFRA_FAILED, None)
    names, collected = (report[0], report[1]) if report is not None else (None, None)
    if names and needs_network(result.stdout + result.stderr):
        names = [f"{n} (needs network)" for n in names]
    if names is None:
        names = [] if result.ok else [SUITE]
    elif not names and not result.ok:
        names = [SUITE]
    status = NOT_COLLECTED if collected == 0 else RAN
    return Round(sorted(names), status, collected)


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
    n = 0
    for _ in range(rounds):
        result = Round(None, INFRA_FAILED, None)
        for _attempt in range(2):  # a round that tells nothing about the code is run once more
            n += 1
            result = _round(runner, work, image, plan, n, timeout_s)
            if result.meaningful:
                break
        failed_per_round.append(result.failed if result.failed is not None else [SUITE])
        statuses.append(result.status)
        collected.append(result.collected)
    shutil.rmtree(work / JUNIT_DIR, ignore_errors=True)
    return TestSummary(
        rounds=rounds, failed_per_round=failed_per_round, round_status=statuses, collected_per_round=collected
    )
