"""Campaign 13: the environment the team's CI job prepares. The workflow is reduced to its test job without
publishing steps; the job's own test steps are what is measured; a job that cannot run here is said, not guessed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from unbidden.contracts.guardian import Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.sandbox.ci_env import NotPreparable, filtered_job, prepared_well, step_scripts
from unbidden.sandbox.ci_env import test_command as job_test_command
from unbidden.sandbox.provision import ci_environment_allowed

pytestmark = pytest.mark.unit

WORKFLOW = """
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ${{ matrix.os }}
    needs: lint
    strategy:
      matrix:
        python-version: ["pypy3.12", "3.15t", "3.13", "3.12", "3.11"]
        os: [windows-latest, macos-latest, ubuntu-latest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "${{ matrix.python-version }}"}
      - name: Install Linux dependencies
        run: sudo apt install gettext
      - name: Tox tests
        run: uvx --python ${{ matrix.python-version }} --with tox-uv tox -e py
      - name: Upload coverage
        uses: codecov/codecov-action@v5
      - name: Publish
        run: twine upload dist/*
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: git push origin HEAD:gh-pages
"""


def _repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    repo = tmp_path / "r"
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    rev = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return repo, rev


def test_the_workflow_is_reduced_to_the_test_job_on_linux_without_publishing(tmp_path: Path) -> None:
    repo, rev = _repo(tmp_path, {".github/workflows/test.yml": WORKFLOW})
    text, matrix, skipped = filtered_job(repo, rev, "test.yml", "test")
    data = yaml.safe_load(text)
    assert list(data["jobs"]) == ["test"]  # the deploy job never runs
    job = data["jobs"]["test"]
    assert job["runs-on"] == "ubuntu-latest" and "needs" not in job
    assert matrix == {"python-version": "3.12", "os": "ubuntu-latest"}
    assert skipped == ["Upload coverage", "Publish"]
    names = [s.get("name") or s.get("uses") for s in job["steps"]]
    assert "Upload coverage" not in names and "Publish" not in names
    assert names[-1] == "unbidden: keep the prepared environment"
    log = (
        "[Test/test] ⭐ Run Main Install Linux dependencies\n"
        "[Test/test]   🐳  docker exec cmd=[bash -e /var/run/act/workflow/3] user= workdir=\n"
        "[Test/test] ⭐ Run Main Tox tests\n"
        "[Test/test]   🐳  docker exec cmd=[bash -e /var/run/act/workflow/5] user= workdir=\n"
    )
    # The script act wrote, with `${{ matrix.python-version }}` resolved: run as it is, nothing reinterpreted.
    assert job_test_command(text, step_scripts(log)) == "bash -e /opt/unbidden-scripts/5"


def test_a_job_that_cannot_run_here_is_said(tmp_path: Path) -> None:
    hosted = WORKFLOW.replace("runs-on: ${{ matrix.os }}", "runs-on: [self-hosted, Linux, X64, team]")
    repo, rev = _repo(tmp_path, {".github/workflows/test.yml": hosted})
    with pytest.raises(NotPreparable, match="self-hosted"):
        filtered_job(repo, rev, "test.yml", "test")
    windows = WORKFLOW.replace("os: [windows-latest, macos-latest, ubuntu-latest]", "os: [windows-latest]")
    repo, rev = _repo(tmp_path / "w", {".github/workflows/test.yml": windows})
    with pytest.raises(NotPreparable, match="none of them Linux"):
        filtered_job(repo, rev, "test.yml", "test")


def test_the_environment_is_usable_unless_it_failed_before_the_tests() -> None:
    job = yaml.safe_dump({"jobs": {"t": {"steps": [{"name": "Run the suite", "run": "pytest -q"}]}}})
    assert prepared_well([("Set up Python", True), ("Install", True), ("Run the suite", False)], job) == (True, "")
    assert prepared_well([("Set up Python", True), ("Install deps", False)], job) == (False, "Install deps")
    assert prepared_well([("Tox tests", False)], job) == (True, "")  # named as tests


def test_the_mandate_decides_and_autonomous_allows_by_default() -> None:
    def policy(**autonomy: str) -> PolicyEngine:
        return PolicyEngine(Mandate.model_validate({"workspace": "w", "autonomy": autonomy}))

    assert not ci_environment_allowed(policy())
    assert ci_environment_allowed(policy(merge_pull_requests="allow"))
    allowed = Mandate.model_validate({"workspace": "w", "egress": {"ci_environment": "allow"}})
    denied = Mandate.model_validate({"workspace": "w", "egress": {"ci_environment": "deny"},
                                     "autonomy": {"merge_pull_requests": "allow"}})  # fmt: skip
    assert ci_environment_allowed(PolicyEngine(allowed)) and not ci_environment_allowed(PolicyEngine(denied))


def test_a_matrix_of_objects_is_one_combination_and_conditions_on_other_jobs_are_lifted(tmp_path: Path) -> None:
    # codex-lb (campaign 13): `slice: [{name: unit, ...}]` and test steps under `if: needs.changes.outputs...`.
    workflow = """
name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-24.04
    needs: changes
    strategy:
      matrix:
        slice:
          - {name: unit, path: tests/unit}
          - {name: e2e, path: tests/e2e}
    steps:
      - run: echo skipped
        if: needs.changes.outputs.backend != 'true'
      - name: Tests
        if: needs.changes.outputs.backend == 'true'
        run: pytest -q ${{ matrix.slice.path }}
"""
    repo, rev = _repo(tmp_path, {".github/workflows/ci.yml": workflow})
    text, matrix, _ = filtered_job(repo, rev, "ci.yml", "test")
    job = yaml.safe_load(text)["jobs"]["test"]
    assert job["strategy"]["matrix"] == {"slice": [{"name": "unit", "path": "tests/unit"}]}
    assert matrix == {"slice": "unit"}
    assert all("if" not in s or "needs." not in str(s["if"]) for s in job["steps"])
    log = (
        "[CI/test] ⭐ Run Main Tests\n"
        "[CI/test]   🐳  docker exec cmd=[bash --noprofile --norc -e -o pipefail /var/run/act/workflow/2.sh] "
        "user= workdir=backend\n"  # `shell: bash` (harlequin, campaign 13)
    )
    assert job_test_command(text, step_scripts(log)) == (
        "(cd backend && bash --noprofile --norc -e -o pipefail /opt/unbidden-scripts/2.sh)"
    )


def test_a_service_keeps_its_container_port_but_not_a_fixed_host_port(tmp_path: Path) -> None:
    workflow = """
on: push
jobs:
  quick-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        ports: ["5432:5432"]
        options: --name=pg --health-cmd pg_isready
    steps:
      - run: pytest -q
"""
    repo, rev = _repo(tmp_path, {".github/workflows/ci.yml": workflow})
    text, _, _ = filtered_job(repo, rev, "ci.yml", "quick-tests")
    job = yaml.safe_load(text)["jobs"]["quick-tests"]
    # localhost reaches the service, as on GitHub's runner
    assert job["steps"][0]["name"] == "unbidden: the job's services on localhost"
    assert "TCP-LISTEN:5432" in job["steps"][0]["run"] and "TCP:postgres:5432" in job["steps"][0]["run"]
    service = job["services"]["postgres"]
    assert service["ports"] == ["5432"] and service["options"] == "--health-cmd pg_isready"


def test_installing_a_publishing_tool_is_not_publishing() -> None:
    from unbidden.sandbox.ci_env import publishes

    assert not publishes("pip install tox coveralls")
    assert publishes("coveralls") and publishes("twine upload dist/*") and publishes("git push origin HEAD")
    assert publishes("pip install twine\ntwine upload dist/*")


def test_a_step_name_is_read_without_its_duration_in_any_form() -> None:
    from unbidden.sandbox.ci_env import _steps  # pyright: ignore[reportPrivateUsage]

    log = (
        "[unbidden-ci/validate]   ✅  Success - Main Set up Python [36.656ms]\n"
        "[unbidden-ci/validate]   ❌  Failure - Main Run validation [4m17.22195475s]\n"
    )
    assert _steps(log) == [("Set up Python", True), ("Run validation", False)]


def test_only_the_steps_that_run_tests_are_measured() -> None:
    from unbidden.sandbox.ci_env import runs_tests

    assert not runs_tests("📦 Install tox", 'uv tool install "tox>=4.45" --with tox-uv')
    assert not runs_tests("📦 Set up test suite", "tox run -vv --notest -e 3.12")
    assert not runs_tests("📦 Seed package cache", "tox exec -e 3.12 -- python scripts/update_package_cache.py")
    assert runs_tests("🧪 Run test suite", "tox run --skip-pkg-install -e 3.12")
    assert runs_tests("Run validation", "task \\\n  OS=ubuntu \\\n  gha:validate")
    assert not runs_tests("Install", "pip install pytest")


def test_a_round_that_missed_the_network_runs_again_with_it(tmp_path: Path) -> None:
    """In an environment the team's CI job prepared (and the mandate let use the network), an offline miss is rerun
    with the network and said; it is never counted as the code's failure."""
    from unbidden.lab.testsuite import TestPlan, run_suite
    from unbidden.sandbox.provision import DependencyImage
    from unbidden.sandbox.runner import SandboxResult, SandboxSpec

    image = DependencyImage(tag="ci", language="python", registries=[], env={}, links={}, runner_like=True,
                            test_command="tox -e py")  # fmt: skip
    seen: list[str] = []

    class Runner:
        def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
            seen.append(spec.network)
            if spec.network == "none":
                return SandboxResult(1, "ERROR: No matching distribution found for setuptools>=77", "", False, 1, False,
                                     False)  # fmt: skip
            junit = work / ".unbidden-junit" / f"round-{len(seen)}.xml"
            junit.write_text('<testsuite tests="2"><testcase classname="t" name="a"/><testcase classname="t" '
                             'name="b"/></testsuite>')  # fmt: skip
            return SandboxResult(0, "2 passed", "", False, 1, False, False)

    work = tmp_path / "w"
    work.mkdir()
    summary = run_suite(Runner(), work, image, TestPlan(argv=("pytest",), source="ci", pytest=True), rounds=1)  # type: ignore[arg-type]
    assert seen[:2] == ["none", "bridge"]
    assert summary.status(0) == "ran" and summary.collected_per_round == [2]
    assert "rerun with the network" in (summary.infra_why[0] or "")


def test_the_internet_is_refused_except_for_a_ci_prepared_rerun() -> None:
    from unbidden.sandbox.runner import SandboxError, SandboxSpec, docker_argv

    with pytest.raises(SandboxError):
        docker_argv(SandboxSpec(image="x", argv=["true"], network="bridge"), Path("/w"), "n")
    argv = docker_argv(SandboxSpec(image="x", argv=["true"], network="bridge", runner_like=True, mount="/ws"),
                       Path("/w"), "n")  # fmt: skip
    assert argv[argv.index("--network") + 1] == "bridge" and "--cap-drop" in argv and "-v" in argv


def test_a_step_that_drives_the_hosts_docker_is_left_out() -> None:
    from unbidden.sandbox.ci_env import drives_docker

    assert drives_docker("cat << EOF > my.cnf\nx\nEOF\ndocker cp my.cnf mysql:/etc/mysql/conf.d/\ndocker restart mysql")
    assert drives_docker("sudo docker compose up -d") and drives_docker("cd x && docker run --rm y")
    assert not drives_docker("pip install docker\npytest tests/test_docker.py") and not drives_docker("echo dockerfile")
