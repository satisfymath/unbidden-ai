"""Run a repository's own test suite in the sandbox, several rounds, and report failing test names."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from unbidden.contracts.experiment import TestSummary
from unbidden.observe.stack import Stack
from unbidden.sandbox.provision import DependencyImage
from unbidden.sandbox.runner import SandboxRunner, SandboxSpec

JUNIT_DIR = ".unbidden-junit"
SUITE = "<suite>"  # name used when a runner cannot tell which test failed


def test_argv(stack: Stack, language: str) -> list[str] | None:
    if language == "python" and stack.python is not None and stack.python.pytest:
        return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
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
    runner: SandboxRunner, work: Path, image: DependencyImage, argv: list[str], n: int, timeout_s: float
) -> tuple[list[str] | None, bool]:
    """One round: failing test names, and whether the result says anything about the code at all."""
    junit = work / JUNIT_DIR / f"round-{n}.xml"
    junit.parent.mkdir(exist_ok=True)
    junit.parent.chmod(0o777)
    run_argv = (
        [*argv, f"--junitxml=/work/{JUNIT_DIR}/round-{n}.xml"] if argv[:3] == ["python", "-m", "pytest"] else argv
    )
    result = runner.run(SandboxSpec(image=image.tag, argv=run_argv, env=image.env, timeout_s=timeout_s), work)
    names = _junit_failures(junit)
    if names is None and run_argv is not argv and not result.ok:
        # pytest crashed before writing its report: an environment problem, not a test result.
        return None, False
    if names is None:
        names = [] if result.ok else [SUITE]
    elif not names and not result.ok and result.exit_code != 5:  # pytest exit 5: no tests collected
        names = [SUITE]
    return sorted(names), True


def run_suite(
    runner: SandboxRunner, work: Path, image: DependencyImage, argv: list[str], *, rounds: int = 3,
    timeout_s: float = 900,
) -> TestSummary:  # fmt: skip
    failed_per_round: list[list[str]] = []
    n = 0
    for _ in range(rounds):
        names: list[str] | None = None
        for _attempt in range(2):  # a round that tells nothing about the code is run once more
            n += 1
            names, meaningful = _round(runner, work, image, argv, n, timeout_s)
            if meaningful:
                break
        failed_per_round.append(names if names is not None else [SUITE])
    shutil.rmtree(work / JUNIT_DIR, ignore_errors=True)
    return TestSummary(rounds=rounds, failed_per_round=failed_per_round)
