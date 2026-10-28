from __future__ import annotations

from pathlib import Path

import pytest

from unbidden.lab.testsuite import JUNIT_DIR, TestPlan, run_suite
from unbidden.sandbox.provision import DependencyImage
from unbidden.sandbox.runner import SandboxResult, SandboxSpec

pytestmark = pytest.mark.unit

IMAGE = DependencyImage(tag="img", language="python", registries=[], env={}, links={})
PYTEST = TestPlan(argv=("python", "-m", "pytest"), source="pytest", pytest=True)
JUNIT = """<testsuite tests="3"><testcase classname="t" name="a"/><testcase classname="t" name="b">
<failure/></testcase><testcase classname="t" name="c"/></testsuite>"""


class FakeRunner:
    """Answers each round with an exit code and, when given, the JUnit report pytest would have written."""

    def __init__(self, work: Path, outcomes: list[tuple[int, str | None]]) -> None:
        self.work, self.outcomes, self.calls = work, outcomes, 0

    def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
        code, report = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if report is not None:
            (work / JUNIT_DIR / f"round-{self.calls}.xml").write_text(report)
        return SandboxResult(code, "", "", False, 1.0, False, False)


def test_each_round_records_whether_the_suite_ran_and_how_many_tests_it_collected(tmp_path: Path) -> None:
    summary = run_suite(FakeRunner(tmp_path, [(1, JUNIT)]), tmp_path, IMAGE, PYTEST, rounds=2)  # type: ignore[arg-type]
    assert summary.failed_per_round == [["t::b"], ["t::b"]]
    assert summary.round_status == ["ran", "ran"] and summary.collected_per_round == [3, 3]


def test_no_tests_collected_is_not_a_pass(tmp_path: Path) -> None:
    summary = run_suite(FakeRunner(tmp_path, [(5, None)]), tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert summary.round_status == ["not_collected"] and summary.collected_per_round == [0]


def test_a_suite_that_never_reports_is_an_infrastructure_failure_after_one_retry(tmp_path: Path) -> None:
    runner = FakeRunner(tmp_path, [(2, None)])
    summary = run_suite(runner, tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert runner.calls == 2  # retried once
    assert summary.round_status == ["infra_failed"] and summary.failed_per_round == [["<suite>"]]


def test_xdist_starts_as_many_workers_as_the_sandbox_has_cpus(tmp_path: Path) -> None:
    # mealie (D-035): `pytest -n auto` counted the host's CPUs and the round died at the sandbox's memory limit.
    seen: list[dict[str, str]] = []

    class Recording(FakeRunner):
        def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
            seen.append({**spec.public_env, **spec.env})
            return super().run(spec, work)

    run_suite(Recording(tmp_path, [(1, JUNIT)]), tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert seen[0]["PYTEST_XDIST_AUTO_NUM_WORKERS"] == str(int(SandboxSpec.cpus))
