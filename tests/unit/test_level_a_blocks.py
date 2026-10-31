"""Level A of the campaign (stage 10, product c840697, 20 repositories): four classes of block in the preparation,
each fixed generally and pinned here. CTFd: `sudo` lines that edit the CI runner's own system made the job
irreproducible. httpx: a repository script that only installs ran offline. sqlmodel: the matrix entry whose database
a `docker compose up` step starts came first. TimeTracker: a pyproject.toml of tool settings only was taken for the
manifest, and its requirements.txt never installed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.observe.ci import _entries, _install_script, ci_test_plan  # pyright: ignore[reportPrivateUsage]
from unbidden.observe.stack import detect_stack

pytestmark = pytest.mark.unit


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    return tmp_path


WORKFLOW = "on: [push]\njobs:\n"


def test_sudo_lines_that_edit_the_runner_are_left_out_and_the_job_still_runs_its_tests(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "requirements.txt": "flask\n",
        "development.txt": "-r requirements.txt\npytest\n",
        "Makefile": "test:\n\tpytest -rf tests/\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/sqlite.yml": WORKFLOW + """  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Install dependencies
        run: |
            python -m pip install -r development.txt
            sudo yarn install --non-interactive
      - name: Test
        run: |
            sudo rm -f /etc/boto.cfg
            make test
        env:
            TESTING_DATABASE_URL: 'sqlite://'
""",
    })  # fmt: skip
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None, "the job runs the tests; what it does to the runner under sudo is not the job"
    text = "\n".join(s.command for s in plan.steps)
    assert "sudo" not in text and "pytest -rf tests/" in text  # `make test`, expanded
    assert any("edits the CI runner's own system: sudo rm -f /etc/boto.cfg" in n for n in plan.notes)
    assert "development.txt" in plan.requirement_files


def test_a_script_that_only_installs_is_left_out_and_its_requirements_are_the_jobs(tmp_path: Path) -> None:
    install = (
        '#!/bin/sh -e\n[ "$1" = "-p" ] && PYTHON=$2 || PYTHON="python3"\nREQUIREMENTS="requirements.txt"\n'
        'VENV="venv"\nset -x\nif [ -z "$GITHUB_ACTIONS" ]; then\n    "$PYTHON" -m venv "$VENV"\n'
        '    PIP="$VENV/bin/pip"\n'
        'else\n    PIP="pip"\nfi\n"$PIP" install -U pip\n"$PIP" install -r "$REQUIREMENTS"\n'
    )
    assert _install_script(install) == ["requirements.txt"]
    assert _install_script("#!/bin/sh\npip install -r requirements.txt\npytest\n") is None
    repo = _repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "httpx"\nrequires-python = ">=3.9"\n',
        "requirements.txt": "-e .[cli]\npytest\n",
        "scripts/install": install,
        "scripts/test": "#!/bin/sh\nset -ex\npytest tests\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/test-suite.yml": WORKFLOW + """  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: scripts/install
      - run: scripts/test
""",
    })  # fmt: skip
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None
    text = "\n".join(s.command for s in plan.steps)
    assert "scripts/install" not in text and "scripts/test" in text
    assert "requirements.txt" in plan.requirement_files
    assert any("scripts/install only installs" in n for n in plan.notes)


def test_the_entry_whose_database_a_compose_step_starts_comes_after_the_one_that_needs_none() -> None:
    job = {
        "strategy": {"matrix": {
            "os": ["ubuntu-latest", "windows-latest"], "python-version": ["3.14"],
            "include": [
                {"os": "ubuntu-latest", "python-version": "3.14", "database": "postgres",
                 "database-url": "postgresql+psycopg://sqlmodel:sqlmodel@127.0.0.1:15432/sqlmodel_test"},
                {"os": "ubuntu-latest", "python-version": "3.11"},
            ],
        }},
        "steps": [
            {"run": "uv sync --group tests"},
            {"if": "matrix.database", "run": 'docker compose up --wait --wait-timeout 120 "$DATABASE"',
             "env": {"DATABASE": "${{ matrix.database }}"}},
            {"run": "uv run bash scripts/test.sh"},
        ],
    }  # fmt: skip
    labels = [label for label, _ in _entries(job)]
    assert "postgres" not in labels[0] and "windows" not in labels[0], labels  # Linux, and no engine to start
    assert any("postgres" in label for label in labels)  # kept, after the entries the sandbox can run


def test_a_pyproject_of_tool_settings_only_is_not_the_manifest(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "pyproject.toml": '[tool.black]\nline-length = 120\n\n[tool.coverage.run]\nsource = ["app"]\n',
        "requirements.txt": "Flask==3.0.0\n",
        "requirements-test.txt": "pytest\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/ci.yml": WORKFLOW + """  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt
      - run: pytest tests/
""",
    })  # fmt: skip
    stack = detect_stack(repo, "HEAD")
    assert stack.python is not None
    assert stack.python.manifest == "requirements.txt"
    assert "requirements-test.txt" in stack.python.extra_requirements
    declared = _repo(tmp_path / "declared", {
        "pyproject.toml": '[project]\nname = "app"\ndependencies = ["flask"]\n',
        "requirements.txt": "flask\n",
    })  # fmt: skip
    assert (declared_stack := detect_stack(declared, "HEAD").python) is not None
    assert declared_stack.manifest == "pyproject.toml"
