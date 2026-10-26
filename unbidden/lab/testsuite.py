"""Run a repository's own test suite in the sandbox, several rounds, and report failing test names."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.contracts.experiment import TestSummary
from unbidden.observe.ci import ci_test_plan
from unbidden.observe.compose import Service, load_compose
from unbidden.observe.stack import Stack
from unbidden.sandbox.provision import DependencyImage
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


def test_plan(repo: Path, rev: str, stack: Stack, language: str) -> TestPlan | None:
    """The repository's own CI job when there is one, else the stack's default test command."""
    compose = load_compose(repo, rev)
    directory = "."
    if language == "python" and stack.python is not None and stack.python.members:
        directory = stack.python.members[0]
    app = compose.app_service_for(directory) if compose is not None else None
    env = {k: v for k, v in app.environment.items() if v} if app is not None else {}
    ci = ci_test_plan(repo, rev, language)
    if ci is not None:
        named = [compose.services[n] for n in ci.services if n in compose.services] if compose is not None else []
        services = tuple(s for s in named if s.image and not s.build_context)
        return TestPlan(
            argv=("bash", "-c", ci.script()), source=f"CI {ci.workflow} > {ci.job}", pytest=language == "python",
            services=services, env=env,
        )  # fmt: skip
    argv = _default_argv(stack, language)
    if argv is None:
        return None
    services = ()
    if compose is not None and app is not None:
        services = tuple(s for s in compose.data_services() if s.name in app.depends_on)
    return TestPlan(argv=tuple(argv), source=" ".join(argv), pytest=language == "python", services=services, env=env)


JUNIT_DIR = ".unbidden-junit"
SUITE = "<suite>"  # name used when a runner cannot tell which test failed
NETWORK_ERRORS = ("Temporary failure in name resolution", "Network is unreachable", "Name or service not known",
                  "getaddrinfo failed", "Could not resolve host")  # fmt: skip


def needs_network(output: str) -> bool:
    """Tests that fail only because the sandbox is offline say nothing about the change under test."""
    return any(marker in output for marker in NETWORK_ERRORS)


def _default_argv(stack: Stack, language: str) -> list[str] | None:
    if language == "python" and stack.python is not None and stack.python.pytest:
        return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *stack.python.test_paths]
    if language == "node" and stack.node is not None and stack.node.test_script:
        return [stack.node.manager, "run", stack.node.test_script]
    return None


def _junit_failures(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    failed: list[str] = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(f"{case.get('classname', '')}::{case.get('name', '')}")
    return failed


def _round(
    runner: SandboxRunner, work: Path, image: DependencyImage, plan: TestPlan, n: int, timeout_s: float
) -> tuple[list[str] | None, bool]:
    """One round: failing test names, and whether the result says anything about the code at all.

    Each round gets fresh services, so no round sees what an earlier one wrote.
    """
    junit = work / JUNIT_DIR / f"round-{n}.xml"
    junit.parent.mkdir(exist_ok=True)
    junit.parent.chmod(0o777)
    env = dict(plan.env)
    if plan.pytest:
        env["PYTEST_ADDOPTS"] = f"--junitxml=/work/{JUNIT_DIR}/round-{n}.xml -p no:cacheprovider"
    with data_services(list(plan.services)) as sidecars:
        spec = SandboxSpec(
            image=image.tag,
            argv=list(plan.argv),
            env=image.env,
            public_env=env,
            timeout_s=timeout_s,
            network=sidecars.network if sidecars else "none",
        )
        result = runner.run(spec, work)
    names = _junit_failures(junit)
    if names and needs_network(result.stdout + result.stderr):
        names = [f"{n} (needs network)" for n in names]
    if names is None and plan.pytest and not result.ok:
        # Nothing reached pytest's report: setup failed or the run crashed. Retried once, then counted.
        return None, False
    if names is None:
        names = [] if result.ok else [SUITE]
    elif not names and not result.ok and result.exit_code != 5:  # pytest exit 5: no tests collected
        names = [SUITE]
    return sorted(names), True


def run_suite(
    runner: SandboxRunner, work: Path, image: DependencyImage, plan: TestPlan, *, rounds: int = 3,
    timeout_s: float = 900,
) -> TestSummary:  # fmt: skip
    failed_per_round: list[list[str]] = []
    n = 0
    for _ in range(rounds):
        names: list[str] | None = None
        for _attempt in range(2):  # a round that tells nothing about the code is run once more
            n += 1
            names, meaningful = _round(runner, work, image, plan, n, timeout_s)
            if meaningful:
                break
        failed_per_round.append(names if names is not None else [SUITE])
    shutil.rmtree(work / JUNIT_DIR, ignore_errors=True)
    return TestSummary(rounds=rounds, failed_per_round=failed_per_round)
