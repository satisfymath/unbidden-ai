"""Suites the CI splits into groups, read as the CI runs one of them (stage 10).

Found on Prefect (docs/bench/stage10-diagnosis.md): its test job runs one of 18 pytest-split groups per matrix entry;
read with the matrix expressions left empty (`--group ""`, a PostgreSQL image of `${{ ... }}`), the durations file a
downloaded artifact, `$GITHUB_OUTPUT` assumed, a bookkeeping step after the tests taken for a test step, and the
database URL it writes to `$GITHUB_ENV` lost; the base checks never started."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.lab.testsuite import test_plan as plan_for
from unbidden.observe.ci import ci_test_plan, gh_expression
from unbidden.observe.stack import detect_stack

pytestmark = pytest.mark.unit

SPLIT = """name: Python tests
on: push
jobs:
  run-canonical-tests:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:latest
        ports:
          - 6379:6379
      postgres:
        image: ${{ startsWith(matrix.database, 'postgres') && matrix.database || '' }}
        env:
          POSTGRES_USER: prefect
          POSTGRES_PASSWORD: prefect
          POSTGRES_DB: prefect
        ports:
          - 5432:5432
    strategy:
      matrix:
        group: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]
        database: ["postgres:14"]
        python-version: ["3.12"]
    steps:
      - uses: actions/checkout@v7
      - name: Install packages
        run: uv sync --locked
      - name: Download test duration baseline
        uses: actions/download-artifact@v8
        with:
          name: canonical-test-duration-baseline
      - name: Set database connection URL
        if: ${{ startsWith(matrix.database, 'postgres') }}
        run: echo "PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://prefect:prefect@localhost/prefect" \
          >> $GITHUB_ENV
      - name: Run tests
        id: canonical_tests
        run: |
          duration_path="test-durations-${{ matrix.group }}.json"
          jq '."__pytest_split_incomplete__" = -1' \\
            test-durations.json > "$duration_path"
          set +e
          uv run pytest tests --ignore=tests/typesafety \\
          -m "not windows" \\
          --exclude-service kubernetes \\
          --splits 18 \\
          --group "${{ matrix.group }}" \\
          --splitting-algorithm least_duration \\
          --durations-path "$duration_path" \\
          --store-durations \\
          --clean-durations
          pytest_exit_code=$?
          set -e
          echo "exit_code=${pytest_exit_code}" >> "$GITHUB_OUTPUT"
          exit "$pytest_exit_code"
      - name: Validate group test durations
        if: ${{ !cancelled() && steps.canonical_tests.outputs.exit_code == '0' }}
        run: |
          jq -e 'type == "object"' "test-durations-${{ matrix.group }}.json" > /dev/null
"""

MODULES = """name: Python tests
on: push
jobs:
  run-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        test-type:
          - id: server-models
            name: "Database & Models"
            modules: tests/server/models tests/server/database
          - id: client
            name: "Client"
            modules: tests/client
        database: ["postgres:14", "sqlite"]
        python-version: ["3.11", "3.12"]
        exclude:
          - database: "postgres:14"
            python-version: "3.11"
    services:
      postgres:
        image: ${{ startsWith(matrix.database, 'postgres') && matrix.database || '' }}
        env:
          POSTGRES_PASSWORD: prefect
    steps:
      - run: uv sync --locked
      - name: Run tests
        run: |
          uv run pytest ${{ matrix.test-type.modules }} -m "not windows"
"""


def _repo(tmp_path: Path, workflow: str) -> Path:
    files = {
        "pyproject.toml": '[project]\nname = "app"\nrequires-python = ">=3.10"\n',
        ".github/workflows/python-tests.yaml": workflow,
        "tests/server/models/test_m.py": "def test_m(): ...\n",
        "tests/client/test_c.py": "def test_c(): ...\n",
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return tmp_path


def _head(root: Path) -> str:
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_a_split_suite_runs_one_real_group_with_its_matrix_resolved(tmp_path: Path) -> None:
    root = _repo(tmp_path, SPLIT)
    plan = ci_test_plan(root, _head(root), "python")
    assert plan is not None
    script = plan.script()
    assert "${{" not in script
    assert "--splits 18" in script and '--group "1"' in script  # group 1 of 18, as the CI defines it
    assert "test-durations.json" not in script  # the artifact from another job is not assumed
    assert "--store-durations" not in script and "--durations-path" not in script
    assert "jq -e" not in script  # the bookkeeping step after the tests is not a test step
    assert "GITHUB_OUTPUT=" in script  # writes to the runner's files go somewhere
    assert dict(plan.env)["PREFECT_SERVER_DATABASE_CONNECTION_URL"].endswith("@localhost/prefect")
    images = {name: image for name, image, _, _ in plan.containers}
    assert images["postgres"] == "postgres:14"
    assert plan.partial and "group 1 of 18" in plan.scope
    assert len(plan.groups) == 18


def test_the_test_plan_points_the_written_environment_at_the_sidecars(tmp_path: Path) -> None:
    root = _repo(tmp_path, SPLIT)
    plan = plan_for(root, _head(root), detect_stack(root), "python")
    assert plan is not None and plan.partial
    assert plan.env["PREFECT_SERVER_DATABASE_CONNECTION_URL"] == "postgresql+asyncpg://prefect:prefect@postgres/prefect"
    assert {s.name for s in plan.services} == {"redis", "postgres"}
    assert "GITHUB_ENV" not in plan.argv[-1].split("export", 1)[-1].split("\n", 1)[1]


def test_a_matrix_of_modules_runs_one_entry_and_says_which(tmp_path: Path) -> None:
    root = _repo(tmp_path, MODULES)
    plan = ci_test_plan(root, _head(root), "python")
    assert plan is not None
    # 2 test types x 2 databases x 2 Pythons, minus the excluded pair (one per test type) = 6 entries.
    assert len(plan.groups) == 6
    assert "pytest tests/server/models tests/server/database" in plan.script()
    assert {image for _, image, _, _ in plan.containers} == {"postgres:14"}
    assert plan.partial and "1 of 6" in plan.scope


@pytest.mark.parametrize(
    ("expr", "context", "value"),
    [
        ("startsWith(matrix.database, 'postgres') && matrix.database || ''", {"matrix": {"database": "postgres:14"}},
         "postgres:14"),
        ("startsWith(matrix.database, 'postgres') && matrix.database || ''", {"matrix": {"database": "sqlite"}}, ""),
        ("matrix.test-type.modules", {"matrix": {"test-type": {"modules": "tests/a"}}}, "tests/a"),
        ("matrix.os == 'ubuntu-latest'", {"matrix": {"os": "ubuntu-latest"}}, True),
        ("!cancelled()", {"matrix": {}}, None),  # the runner's state is unknown here
        ("secrets.TOKEN", {"matrix": {}}, None),
        ("__import__('os')", {"matrix": {}}, None),  # never evaluated as Python
    ],
)  # fmt: skip
def test_expressions_are_evaluated_only_where_their_value_is_known(expr: str, context: dict[str, object],
                                                                    value: object) -> None:  # fmt: skip
    assert gh_expression(expr, context) == value
