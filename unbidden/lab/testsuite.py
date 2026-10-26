"""Run a repository's own test suite in the sandbox, several rounds, and report failing test names."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from unbidden.contracts.experiment import TestSummary
from unbidden.observe.stack import Stack
from unbidden.sandbox.provision import DependencyImage
from unbidden.sandbox.runner import SandboxRunner, SandboxSpec

JUNIT = ".unbidden-junit.xml"
SUITE = "<suite>"  # name used when a runner cannot tell which test failed


def test_argv(stack: Stack, language: str) -> list[str] | None:
    if language == "python" and stack.python is not None and stack.python.pytest:
        return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml=/work/{JUNIT}"]
    if language == "node" and stack.node is not None and stack.node.test_script:
        return [stack.node.manager, "test"]
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


def run_suite(
    runner: SandboxRunner, work: Path, image: DependencyImage, argv: list[str], *, rounds: int = 3,
    timeout_s: float = 900,
) -> TestSummary:  # fmt: skip
    failed_per_round: list[list[str]] = []
    for _ in range(rounds):
        (work / JUNIT).unlink(missing_ok=True)
        result = runner.run(SandboxSpec(image=image.tag, argv=argv, env=image.env, timeout_s=timeout_s), work)
        names = _junit_failures(work / JUNIT)
        if names is None:
            names = [] if result.ok else [SUITE]
        elif not names and not result.ok and result.exit_code != 5:  # pytest exit 5: no tests collected
            names = [SUITE]
        failed_per_round.append(sorted(names))
    (work / JUNIT).unlink(missing_ok=True)
    return TestSummary(rounds=rounds, failed_per_round=failed_per_round)
