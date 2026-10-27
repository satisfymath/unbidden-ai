from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.lab.testsuite import test_plan as build_test_plan
from unbidden.observe.ci import ci_test_plan
from unbidden.observe.stack import detect_stack

pytestmark = pytest.mark.unit

WORKFLOW = """
name: Test Backend
jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: docker compose up -d --wait db mailpit
      - name: Migrate
        run: uv run bash scripts/prestart.sh
        working-directory: backend
      - run: uv run bash scripts/tests-start.sh "Coverage for ${{ github.sha }}"
        working-directory: backend
      - run: uv run coverage report --fail-under=90
        working-directory: backend
"""
COMPOSE = """
services:
  db:
    image: postgres:18
  mailpit:
    image: axllent/mailpit
  backend:
    build: {context: ., dockerfile: backend/Dockerfile}
    depends_on: [db]
    environment:
      DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/app
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    files = {
        ".github/workflows/test-backend.yml": WORKFLOW,
        "compose.yml": COMPOSE,
        ".env": "POSTGRES_PASSWORD=changethis\n",
        "pyproject.toml": '[project]\nname="r"\n[tool.uv.workspace]\nmembers=["backend"]\n',
        "uv.lock": "",
        "backend/pyproject.toml": '[project]\nname="app"\n[dependency-groups]\ndev=["pytest"]\n',
        "backend/tests/test_a.py": "def test_a(): pass\n",
    }
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return tmp_path


def test_ci_steps_keep_the_teams_scripts_and_drop_tooling(repo: Path) -> None:
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None
    assert plan.services == ("db", "mailpit")
    assert [(s.cwd, s.command) for s in plan.steps] == [
        ("backend", "bash scripts/prestart.sh"),
        ("backend", 'bash scripts/tests-start.sh "Coverage for "'),
    ]
    assert "cd /work/backend" in plan.script() and "docker" not in plan.script()


def test_test_plan_brings_the_services_and_the_app_environment(repo: Path) -> None:
    plan = build_test_plan(repo, "HEAD", detect_stack(repo), "python")
    assert plan is not None and plan.source.startswith("CI test-backend.yml")
    assert [s.name for s in plan.services] == ["db", "mailpit"]
    assert plan.env["DATABASE_URL"] == "postgresql://postgres:changethis@db:5432/app"


def test_lint_scope_comes_from_the_workflows_commands(tmp_path: Path) -> None:
    from unbidden.observe.ci import ci_lint_packages

    workflow = (
        "jobs:\n  check:\n    steps:\n      - run: pnpm install\n      - run: pnpm --filter @shop/web lint\n"
        "      - run: pnpm typecheck\n"
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(workflow)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    packages = {"@shop/web": "apps/web", "api": "backend/api"}
    assert ci_lint_packages(tmp_path, "HEAD", packages, {}) == {"apps/web"}
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        workflow.replace("pnpm --filter @shop/web lint", "pnpm lint")
    )
    subprocess.run([*git, "commit", "-qam", "y"], check=True)
    root = {"lint": "pnpm --filter @shop/web lint && pnpm --filter api lint"}
    assert ci_lint_packages(tmp_path, "HEAD", packages, root) == {"apps/web", "backend/api"}


def test_a_test_job_is_found_by_what_it_runs_and_jobs_needing_more_come_last(tmp_path: Path) -> None:
    workflows = {
        "e2e.yml": "jobs:\n  e2e-tests:\n    steps:\n      - run: pytest -m e2e\n",
        "pythonpackage.yml": (
            "jobs:\n  build:\n    steps:\n      - run: poetry install\n"
            "      - run: |\n          source $VENV\n          pytest tests -v\n"
        ),
    }
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".github/workflows").mkdir(parents=True)
    for name, text in workflows.items():
        (tmp_path / ".github/workflows" / name).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    plan = ci_test_plan(tmp_path, "HEAD", "python")
    assert plan is not None and (plan.workflow, plan.job) == ("pythonpackage.yml", "build")
    assert [s.command for s in plan.steps] == ["pytest tests -v"]


def test_a_tool_is_green_when_the_jobs_that_run_it_are_whatever_else_failed(tmp_path: Path) -> None:
    from unbidden.observe.ci import tool_status

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/fe.yml").write_text(
        "jobs:\n  test:\n    name: frontend\n    steps:\n      - run: pnpm run eslint\n"
        "  e2e:\n    steps:\n      - run: pnpm e2e\n"
    )
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    runs = {"frontend (18)": "success", "frontend (20)": "success", "e2e": "failure"}
    assert tool_status(tmp_path, "HEAD", "eslint", runs) == "green"
    assert tool_status(tmp_path, "HEAD", "eslint", {**runs, "frontend (20)": "failure"}) == "red"
    assert tool_status(tmp_path, "HEAD", "ruff", runs) is None


TASK_WORKFLOWS = {
    ".github/workflows/locale-sync.yml": """
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - run: echo "import fastapi" > test.py && uv run python test.py
      - run: gh pr create --title sync
""",
    ".github/workflows/test-backend.yml": """
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "import fastapi" > test.py && uv run python test.py
        continue-on-error: true
      - run: |
          sudo apt-get install libldap2-dev
          if [ "${{ matrix.Database }}" = "postgres" ]; then
            uv sync --group dev --extra pgsql
          else
            uv sync --group dev
          fi
      - run: uv run pre-commit run --all-files
      - run: task py:mypy
      - run: task py:test -- -x
""",
    "Taskfile.yml": """
tasks:
  py:mypy:
    cmds: [uv run mypy mealie]
  py:test:
    cmds:
      - uv run pytest -n auto {{ .CLI_ARGS }}
""",
}


def _commit(root: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return root


def test_taskfile_calls_are_expanded_and_publishing_optional_check_and_broken_steps_dropped(tmp_path: Path) -> None:
    plan = ci_test_plan(_commit(tmp_path, TASK_WORKFLOWS), "HEAD", "python")
    assert plan is not None and (plan.workflow, plan.job) == ("test-backend.yml", "tests")
    assert [s.command for s in plan.steps] == ["pytest -n auto -x"]


def test_a_job_that_publishes_is_never_a_test_plan(tmp_path: Path) -> None:
    files = {
        ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: pytest\n      - run: git push origin x\n"
    }
    assert ci_test_plan(_commit(tmp_path, files), "HEAD", "python") is None
