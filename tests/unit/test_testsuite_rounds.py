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

    def __init__(self, work: Path, outcomes: list[tuple[int, str | None]], stderr: str = "") -> None:
        self.work, self.outcomes, self.calls, self.stderr = work, outcomes, 0, stderr

    def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
        code, report = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if report is not None:
            (work / JUNIT_DIR / f"round-{self.calls}.xml").write_text(report)
        return SandboxResult(code, "", self.stderr, False, 1.0, False, False)


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


def test_a_suite_that_never_reports_says_how_it_ended(tmp_path: Path) -> None:
    runner = FakeRunner(tmp_path, [(2, None)], stderr="ImportError: libpq.so.5: cannot open shared object file")
    summary = run_suite(runner, tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert summary.round_status == ["infra_failed"]
    assert summary.infra_why == ["exit 2: ImportError: libpq.so.5: cannot open shared object file"]


def test_xdist_starts_as_many_workers_as_the_sandbox_has_cpus(tmp_path: Path) -> None:
    # mealie (D-035): `pytest -n auto` counted the host's CPUs and the round died at the sandbox's memory limit.
    seen: list[dict[str, str]] = []

    class Recording(FakeRunner):
        def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
            seen.append({**spec.public_env, **spec.env})
            return super().run(spec, work)

    run_suite(Recording(tmp_path, [(1, JUNIT)]), tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert seen[0]["PYTEST_XDIST_AUTO_NUM_WORKERS"] == str(int(SandboxSpec.cpus))


def test_exit_zero_without_a_test_report_is_no_test_run_not_a_pass(tmp_path: Path) -> None:
    # codex-lb, stage 10: the skip step's echo exited 0 and was recorded as checks "passed" with nothing collected.
    summary = run_suite(FakeRunner(tmp_path, [(0, None)]), tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert summary.round_status == ["not_collected"] and summary.collected_per_round == [0]
    assert "no test ran" in str(summary.infra_why[0])


MISSING_GIT = "FileNotFoundError: [Errno 2] No such file or directory: 'git'"
JUNIT_NO_GIT = f"""<testsuite tests="3"><testcase classname="t" name="a"/><testcase classname="t" name="b">
<failure message="{MISSING_GIT}">Traceback...\n{MISSING_GIT}</failure></testcase><testcase classname="t" name="c">
<error message="{MISSING_GIT}"/></testcase></testsuite>"""
JUNIT_MIXED = f"""<testsuite tests="3"><testcase classname="t" name="a"/><testcase classname="t" name="b">
<failure message="{MISSING_GIT}"/></testcase><testcase classname="t" name="c">
<failure message="AssertionError: assert 1 == 2"/></testcase></testsuite>"""


def test_failures_that_only_name_a_tool_the_image_lacks_are_the_environments_not_the_projects(tmp_path: Path) -> None:
    # codex-lb (campaign 12, level A): tests raised FileNotFoundError for `git`, absent from the dependency image,
    # and the record read "failed" as if the project's tests failed.
    runner = FakeRunner(tmp_path, [(1, JUNIT_NO_GIT)])
    summary = run_suite(runner, tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert summary.round_status == ["infra_failed"] and summary.failed_per_round == [[]]
    assert summary.could_not_run == {"t::b": "git", "t::c": "git"} and summary.collected_per_round == [3]
    assert "lacks `git`" in str(summary.infra_why[0]) and "2 of 3 tests could not run" in str(summary.infra_why[0])
    assert runner.calls == 1  # not retried: the tool would still be missing


def test_a_missing_tool_beside_a_real_failure_keeps_both_apart(tmp_path: Path) -> None:
    # codex-lb again: 30 tests could not run (git) and 4 failed for other reasons; the 4 are the project's, the 30
    # are the environment's, and the record says both.
    summary = run_suite(FakeRunner(tmp_path, [(1, JUNIT_MIXED)]), tmp_path, IMAGE, PYTEST, rounds=1)  # type: ignore[arg-type]
    assert summary.round_status == ["ran"] and summary.failed_per_round == [["t::c"]]
    assert summary.could_not_run == {"t::b": "git"}
    assert "1 test(s) could not run: the sandbox image lacks `git`" in str(summary.infra_why[0])


def test_each_round_of_the_teams_own_step_starts_from_the_measured_revision(tmp_path: Path) -> None:
    """sqlmodel, final pass 0.18.5: its CI step runs `mkdir coverage`; rounds 2 and 3 failed on "File exists" in the
    tree round 1 left, and every security bump was declined for an infrastructure failure."""
    import subprocess

    work = tmp_path / "w"
    work.mkdir()
    (work / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    ci = DependencyImage(tag="ci", language="python", registries=[], env={}, links={}, runner_like=True)

    class Runner(FakeRunner):
        def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
            if (work / "coverage").exists():
                return SandboxResult(1, "", "mkdir: cannot create directory 'coverage': File exists", False, 1.0,
                                     False, False)  # fmt: skip
            (work / "coverage").mkdir()
            return super().run(spec, work)

    summary = run_suite(Runner(work, [(1, JUNIT)]), work, ci, PYTEST, rounds=3)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    assert summary.round_status == ["ran", "ran", "ran"], summary
