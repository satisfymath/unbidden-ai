"""Stage 10, codex-lb: a CI whose test steps sit behind a `changes` job's output, with a skip branch that only echoes
"... pytest context satisfied". The plan must be the branch that runs the tests, say that the condition is unknown,
and never take a step that runs no test for the test run."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.observe.ci import ci_test_plan

pytestmark = pytest.mark.unit

CHANGES_JOB = """  changes:
    runs-on: ubuntu-latest
    outputs:
      backend: ${{ steps.filter.outputs.backend }}
    steps:
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            backend:
              - 'app/**'
"""


def _repo(tmp_path: Path, jobs: str, makefile: str = "") -> Path:
    files = {
        "pyproject.toml": '[project]\nname = "app"\nrequires-python = ">=3.10"\n',
        ".github/workflows/ci.yml": "on: [push, pull_request]\njobs:\n" + jobs,
        "tests/test_a.py": "def test_a(): ...\n",
    }
    if makefile:
        files["Makefile"] = makefile
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return tmp_path


def _commands(tmp_path: Path) -> tuple[list[str], tuple[str, ...]]:
    plan = ci_test_plan(tmp_path, "HEAD", "python")
    assert plan is not None
    return [s.command for s in plan.steps], plan.notes


def test_the_branch_that_runs_the_tests_is_taken_and_the_unknown_condition_said(tmp_path: Path) -> None:
    jobs = (
        CHANGES_JOB
        + """  test:
    runs-on: ubuntu-latest
    needs: changes
    steps:
      - name: Skip backend tests for unrelated changes
        if: needs.changes.outputs.backend != 'true'
        run: echo "Backend files unchanged; required pytest context satisfied."
      - uses: actions/checkout@v4
        if: needs.changes.outputs.backend == 'true'
      - name: Run tests
        if: needs.changes.outputs.backend == 'true'
        run: make test-unit
"""
    )
    makefile = "test-unit:\n\tuv run pytest tests\n"
    commands, notes = _commands(_repo(tmp_path, jobs, makefile))
    assert commands == ["(pytest tests)"]  # the recipe, as make runs it, without make
    assert any("not known outside GitHub" in n and "backend=='true'" in n for n in notes)


def test_a_message_that_mentions_the_runner_is_not_a_test_run(tmp_path: Path) -> None:
    jobs = """  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo "pytest; nothing to do"
"""
    assert ci_test_plan(_repo(tmp_path, jobs), "HEAD", "python") is None


def test_the_tests_after_a_message_are_not_cut_as_bookkeeping(tmp_path: Path) -> None:
    jobs = """  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo "running pytest now"
      - run: pytest tests
"""
    commands, _ = _commands(_repo(tmp_path, jobs))
    assert commands[-1] == "pytest tests"


def test_an_unknown_condition_without_another_branch_keeps_its_steps(tmp_path: Path) -> None:
    jobs = """  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run tests
        if: github.event_name == 'push'
        run: pytest tests
"""
    commands, notes = _commands(_repo(tmp_path, jobs))
    assert commands == ["pytest tests"] and not any("not known" in n for n in notes)


def test_a_make_target_runs_as_its_recipe_prerequisites_first_one_shell_a_line(tmp_path: Path) -> None:
    # codex-lb: `make test-unit` (the sandbox has no make) depends on a frontend build; its pytest line uses
    # $(PYTEST_ARGS); the frontend's `cd` must not reach the tests.
    makefile = (
        "PYTEST_ARGS := -q -ra\n"
        "frontend-install:\n\tcd frontend && bun install --frozen-lockfile\n"
        "frontend-build: frontend-install\n\tcd frontend && bun run build\n"
        "prepare:\n\t@mkdir -p .cache\n"
        "test-unit: frontend-build prepare\n\tuv sync --dev --frozen\n"
        "\tPYTHONFAULTHANDLER=1 uv run pytest $(PYTEST_ARGS) tests\n"
    )
    jobs = """  test:
    runs-on: ubuntu-latest
    steps:
      - run: make test-unit PYTEST_ARGS=-x
"""
    commands, notes = _commands(_repo(tmp_path, jobs, makefile))
    # The override wins; the install is left out; uv run goes, the assignment stays.
    assert commands == ["(mkdir -p .cache)\n(PYTHONFAULTHANDLER=1 pytest -x tests)"]
    assert any("JavaScript build" in n for n in notes)


def test_the_jobs_interpreter_install_is_resolved_at_provisioning_not_run_offline(tmp_path: Path) -> None:
    # Aegra, stage 10: `uv python install 3.12` ran in the sandbox ("Python downloads are not allowed"), and
    # `uv run --package aegra-api pytest` left `aegra-api pytest`.
    from unbidden.observe.ci import ci_python_versions

    jobs = """  test:
    runs-on: ubuntu-latest
    steps:
      - run: uv python install 3.12
      - run: uv sync --all-packages
      - run: uv run --package aegra-api pytest libs/aegra-api/tests
"""
    repo = _repo(tmp_path, jobs)
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None
    assert [s.command for s in plan.steps] == ["pytest libs/aegra-api/tests"]
    assert plan.interpreters == ("3.12",)
    assert "3.12" in ci_python_versions(repo, "HEAD")  # the provisioning chooses it


def _rag_like(tmp_path: Path, steps: str) -> Path:
    jobs = f"""  test:
    runs-on: ubuntu-latest
    steps:
      - run: |
          pip install -r requirements.txt
          pip install -r test_requirements.txt
{steps}"""
    repo = _repo(tmp_path, jobs)
    files = {
        "requirements.txt": "fastapi\n",
        "test_requirements.txt": "pytest\ntestcontainers[postgres]\n",
        "tests/integration/__init__.py": "",
        "tests/integration/conftest.py": "from testcontainers.postgres import PostgresContainer\n",
        "tests/integration/test_db.py": "import pytest\n\n@pytest.mark.integration\ndef test_db(): ...\n",
    }
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "y"], check=True)
    return repo


def test_the_jobs_test_requirements_are_found_and_container_runtime_tests_left_out(tmp_path: Path) -> None:
    # rag-api, stage 10: test_requirements.txt (testcontainers) was not installed, and its integration step starts a
    # pgvector container; the sandbox has no container runtime and never gets the host's Docker socket.
    repo = _rag_like(tmp_path, "      - run: pytest --maxfail=1\n      - run: pytest -m integration --maxfail=3\n")
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None
    assert plan.requirement_files == ("requirements.txt", "test_requirements.txt")
    assert [s.command for s in plan.steps] == ["pytest --maxfail=1"]
    assert any("container runtime" in n and "testcontainers" in n for n in plan.notes)
    assert "container runtime" in plan.scope


def test_excluding_the_container_tests_by_marker_or_selecting_their_directory_is_read_as_such(tmp_path: Path) -> None:
    repo = _rag_like(tmp_path, '      - run: pytest -m "not integration"\n      - run: pytest tests/integration\n')
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None and [s.command for s in plan.steps] == ['pytest -m "not integration"']


def test_the_image_installs_the_ci_test_requirements_after_the_manifest(tmp_path: Path) -> None:
    from unbidden.observe.stack import detect_stack
    from unbidden.sandbox.provision import python_dockerfile

    repo = _rag_like(tmp_path, "      - run: pytest\n")
    (repo / "pyproject.toml").unlink()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "commit", "-qam", "no pyproject"], check=True)
    py = detect_stack(repo).python
    assert py is not None and py.manifest == "requirements.txt" and py.extra_requirements == ("test_requirements.txt",)
    assert (
        "-r /deps/requirements.txt && uv pip install --python /deps/.venv/bin/python -r /deps/test_requirements.txt"
        in (python_dockerfile(py))
    )
