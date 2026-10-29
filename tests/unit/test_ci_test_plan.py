"""The project's own checks, as its CI runs them (stage 8): the job that runs its test runner, with its services.

Found on Conduit: the job chosen ran Postman against a server started in the background (it matched only by a
script's file name), the job that runs pytest through `./scripts/test` was not recognised, and its `services:`
PostgreSQL was ignored because the compose file names its database otherwise."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.lab.testsuite import test_plan as plan_for
from unbidden.observe.stack import detect_stack

pytestmark = pytest.mark.unit
SERVICES = """    services:
      postgres:
        image: postgres:11.5-alpine
        env:
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
"""
API_SPEC = f"""name: API spec
on: push
jobs:
  api-spec:
    runs-on: ubuntu-latest
{SERVICES}    steps:
      - run: poetry install
      - run: |
          poetry run alembic upgrade head
          poetry run uvicorn app.main:app &
          APIURL=http://localhost:8000/api ./postman/run-api-tests.sh
"""
TESTS = f"""name: Tests
on: push
jobs:
  lint:
    runs-on: ubuntu-latest
{SERVICES}    steps:
      - run: poetry install
      - env:
          DATABASE_URL: postgresql://postgres:postgres@localhost/postgres
        run: |
          poetry run alembic upgrade head
          poetry run ./scripts/test
"""


def repo(tmp_path: Path) -> Path:
    files = {
        "pyproject.toml": '[tool.poetry]\nname = "app"\n[tool.poetry.dependencies]\npython = "^3.9"\n',
        "poetry.lock": '[[package]]\nname = "pytest"\nversion = "7.1.2"\n\n[metadata]\npython-versions = "^3.9"\n',
        ".github/workflows/conduit.yml": API_SPEC,
        ".github/workflows/tests.yml": TESTS,
        "scripts/test": "#!/usr/bin/env bash\nset -e\npytest --cov=app ${@}\n",
        "postman/run-api-tests.sh": "#!/usr/bin/env bash\nnpx newman run collection.json\n",
        "docker-compose.yml": "services:\n  db:\n    image: postgres:11.5-alpine\n",
        "tests/test_x.py": "def test_x():\n    assert True\n",
    }  # fmt: skip
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return tmp_path


def test_the_job_that_runs_the_test_runner_with_its_own_database(tmp_path: Path) -> None:
    root = repo(tmp_path)
    plan = plan_for(root, "HEAD", detect_stack(root), "python")
    assert plan is not None and plan.source.startswith("CI tests.yml > lint")
    assert "./scripts/test" in plan.argv[-1] and "newman" not in plan.argv[-1] and "uvicorn" not in plan.argv[-1]
    assert [(s.name, s.image) for s in plan.services] == [("postgres", "postgres:11.5-alpine")]
    assert plan.env["DATABASE_URL"] == "postgresql://postgres:postgres@postgres/postgres"  # localhost -> the sidecar
