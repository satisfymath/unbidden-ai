"""Level A of the campaign (stage 10, product c840697, 20 repositories): four classes of block in the preparation,
each fixed generally and pinned here. CTFd: `sudo` lines that edit the CI runner's own system made the job
irreproducible. httpx: a repository script that only installs ran offline. sqlmodel: the matrix entry whose database
a `docker compose up` step starts came first. TimeTracker: a pyproject.toml of tool settings only was taken for the
manifest, and its requirements.txt never installed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.observe.ci import (  # pyright: ignore[reportPrivateUsage]
    _entries,
    _install_script,
    ci_test_plan,
    script_kind,
    tox_environments,
)
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


def test_a_tox_environment_is_expanded_to_its_commands_with_its_extras(tmp_path: Path) -> None:
    """humanize: the test job runs `uvx --with tox-uv tox -e py`; a benchmark job that spells `pytest` was taken."""
    repo = _repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "humanize"\nrequires-python = ">=3.11"\n'
                          '[project.optional-dependencies]\ntests = ["pytest", "pytest-cov"]\n',
        "tox.ini": "[testenv]\nextras =\n    tests\ncommands =\n    {envpython} -m pytest \\\n      --cov humanize \\\n"
                   "      {posargs}\n\n[testenv:lint]\ndeps = -r requirements-lint.txt\ncommands = ruff check .\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/benchmark.yml": WORKFLOW + """  benchmarks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/test_benchmarks.py --codspeed
""",
        ".github/workflows/test.yml": WORKFLOW + """  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uvx --python 3.12 --with tox-uv tox -e py
""",
    })  # fmt: skip
    envs = tox_environments(repo, "HEAD")
    assert envs["tox:*"][0] == "python -m pytest --cov humanize"
    assert envs["tox:lint"][-1] == '#env {"extras": ["tests"], "groups": [], "requirements": ["requirements-lint.txt"]}'
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None and plan.workflow == "test.yml", plan
    assert plan.steps[0].command == "(python -m pytest --cov humanize)"
    assert plan.sync_flags == ("--all-groups", "--extra tests")


def test_tox_in_pyproject_and_a_job_that_checks_out_another_repository(tmp_path: Path) -> None:
    """click: `uv run tox run` with the environment in `TOX_ENV`, `[tool.tox]` in pyproject.toml; its nightly job
    checks out Flask and runs Flask's suite, which is not click's checks."""
    repo = _repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "click"\nrequires-python = ">=3.10"\n[dependency-groups]\n'
                          'tests = ["pytest"]\n[tool.tox]\nenv_list = ["py3.14", "style"]\n[tool.tox.env_run_base]\n'
                          'dependency_groups = ["tests"]\ncommands = [["pytest", "-v", "--tb=short", '
                          '"--basetemp={env_tmp_dir}", {replace = "posargs", default = [], extend = true}]]\n'
                          '[tool.tox.env.style]\ncommands = [["ruff", "check"]]\n',
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/nightly.yaml": WORKFLOW + """  flask-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: pallets/flask
      - run: uv run --no-sync -- pytest
""",
        ".github/workflows/tests.yaml": WORKFLOW + """  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run --locked --no-default-groups --group dev tox run
        env:
          TOX_ENV: py3.14
""",
    })  # fmt: skip
    envs = tox_environments(repo, "HEAD")
    assert envs["tox:*"][0] == "pytest -v --tb=short --basetemp=/tmp/tox-tmp"
    assert envs["tox:style"][0] == "ruff check"
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None and plan.workflow == "tests.yaml", plan
    assert plan.steps[0].command == "(pytest -v --tb=short --basetemp=/tmp/tox-tmp)"
    assert plan.sync_flags is not None and "--group tests" in plan.sync_flags


def test_the_packages_the_job_installs_with_apt_go_into_the_image(tmp_path: Path) -> None:
    """humanize: `sudo apt install gettext` before a script that runs `msgfmt`; the image stood for the step without
    holding the package."""
    from unbidden.observe.stack import PythonStack
    from unbidden.sandbox.provision import python_dockerfile

    repo = _repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "humanize"\nrequires-python = ">=3.11"\n',
        "scripts/generate-translation-binaries.sh": "#!/bin/sh\nmsgfmt -o a.mo a.po\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/test.yml": WORKFLOW + """  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Linux dependencies
        run: |
          sudo apt install gettext
      - run: scripts/generate-translation-binaries.sh
      - run: python -m pytest
""",
    })  # fmt: skip
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None and plan.system_packages == ("gettext",)
    assert "apt" not in "\n".join(s.command for s in plan.steps)
    stack = detect_stack(repo, "HEAD")
    assert stack.python is not None and stack.python.system_packages == ("gettext",)
    bare = PythonStack(version="3.12", lockfile=None, manifest="pyproject.toml", ruff=False, pyright=False, pytest=True)
    assert "apt-get" not in python_dockerfile(bare)
    assert "apt-get install -y --no-install-recommends gettext &&" in python_dockerfile(bare, headers=("gettext",))


def test_sudo_on_the_repository_still_makes_the_job_irreproducible(tmp_path: Path) -> None:
    """lnbits' regtest job: `sudo chmod -R a+rwx .` (run 2 took it for the test job once sudo lines were relaxed)."""
    repo = _repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "lnbits"\nrequires-python = ">=3.10"\n',
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/regtest.yml": WORKFLOW + """  regtest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          sudo chmod -R a+rwx .
          docker compose up -d
      - run: pytest tests/regtest
""",
    })  # fmt: skip
    assert ci_test_plan(repo, "HEAD", "python") is None


def test_scripts_that_only_check_or_build_are_left_out_and_a_benchmark_job_comes_last(tmp_path: Path) -> None:
    """starlette and httpx: `scripts/check` lints, `scripts/build` builds the package and docs (no network offline),
    `scripts/test` runs the suite; starlette's benchmark job was taken before its test job."""
    check = (
        'export PREFIX=""\nexport SOURCE_FILES="httpx tests"\nset -x\n./scripts/sync-version\n'
        "${PREFIX}ruff format $SOURCE_FILES --diff\n${PREFIX}mypy $SOURCE_FILES\n"
    )
    scripts = {"scripts/check": check, "scripts/sync-version": "#!/bin/sh\nVERSION=1\nsed -i s/x/y/ a.py\n"}
    assert script_kind(check, scripts) is None  # sync-version edits a file: not only a check
    scripts["scripts/sync-version"] = 'V=$(grep -o x a.py)\necho "V: $V"\nif [ "$V" != "1" ]; then\n    exit 1\nfi\n'
    assert script_kind(check, scripts) == ("checks", [])
    assert script_kind("set -x\n${PREFIX}coverage report --fail-under=100\n") == ("reports", [])
    assert script_kind("set -ex\nuv build\nmkdocs build\n") == ("builds", [])
    assert script_kind("set -ex\nuv run coverage run -m pytest $@\n") is None
    repo = _repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "starlette"\nrequires-python = ">=3.10"\n',
        "scripts/install": "#!/bin/sh\nuv sync --frozen\n",
        "scripts/check": "#!/bin/sh\nset -ex\nuv run ruff check .\nuv run mypy .\n",
        "scripts/build": "#!/bin/sh\nset -ex\nuv build\nuv run mkdocs build\n",
        "scripts/test": "#!/bin/sh\nset -ex\nuv run coverage run -m pytest $@\n",
        "scripts/coverage": "#!/bin/sh\nset -x\nuv run coverage report --fail-under=100\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/benchmark.yml": WORKFLOW + """  benchmarks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest benchmarks/ --codspeed
""",
        ".github/workflows/main.yml": WORKFLOW + """  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: scripts/install
      - run: scripts/check
      - run: scripts/build
      - run: scripts/test
      - run: scripts/coverage
""",
    })  # fmt: skip
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None and plan.workflow == "main.yml", plan
    assert [s.command for s in plan.steps] == ["scripts/test"]
    assert any("scripts/coverage only reports" in n for n in plan.notes)
    assert any("scripts/check only checks" in n for n in plan.notes)
    assert any("scripts/build only builds" in n for n in plan.notes)


def test_the_report_message_of_each_failure_is_kept(tmp_path: Path) -> None:
    """Run 3: CTFd's 50 and TimeTracker's 50 failures were names with no cause; the JUnit report had the messages."""
    from unbidden.lab.testsuite import _junit  # pyright: ignore[reportPrivateUsage]

    xml = tmp_path / "r.xml"
    xml.write_text(
        '<testsuites><testsuite><testcase classname="tests.a" name="t1"><failure message="AssertionError: 1 != 2">'
        'long text</failure></testcase><testcase classname="tests.a" name="t2"/>'
        '<testcase classname="tests.b" name="t3"><error>ImportError: no module named x\nmore\nlines\n4\n5\n6</error>'
        "</testcase></testsuite></testsuites>"
    )
    report = _junit(xml)
    assert report is not None
    assert report[0] == ["tests.a::t1", "tests.b::t3"] and report[1] == 3
    assert report[2] == {
        "tests.a::t1": "AssertionError: 1 != 2",
        "tests.b::t3": "ImportError: no module named x\nmore\nlines\n4",
    }


def test_a_service_port_expression_in_the_job_env_is_the_containers_port(tmp_path: Path) -> None:
    """CTFd: `TESTING_DATABASE_URL: mysql+pymysql://...@localhost:${{ job.services.mariadb.ports[3306] }}/ctfd`
    was dropped as an expression and the tests ran on SQLite (50 failures about `max_overflow`)."""
    repo = _repo(tmp_path, {
        "requirements.txt": "flask\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/mariadb.yml": WORKFLOW + """  build:
    runs-on: ubuntu-latest
    services:
      mariadb:
        image: mariadb:10.11
        env:
          MYSQL_ROOT_PASSWORD: password
        ports:
          - 3306/tcp
    steps:
      - uses: actions/checkout@v5
      - run: python -m pytest
        env:
          TESTING_DATABASE_URL: mysql+pymysql://root:password@localhost:${{ job.services.mariadb.ports[3306] }}/ctfd
""",
    })  # fmt: skip
    plan = ci_test_plan(repo, "HEAD", "python")
    assert plan is not None
    assert dict(plan.env)["TESTING_DATABASE_URL"] == "mysql+pymysql://root:password@localhost:3306/ctfd"


def test_requirement_files_the_job_installs_are_installed_after_the_sync_without_the_project_itself(
    tmp_path: Path,
) -> None:
    """httpx: `scripts/install` runs `pip install -r requirements.txt` (`-e .[cli]`, then coverage, mypy); with a
    pyproject manifest the file was ignored and `coverage: not found` ended the job."""
    from unbidden.sandbox.provision import python_dockerfile

    repo = _repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "httpx"\nrequires-python = ">=3.9"\n',
        "requirements.txt": "-e .[cli]\ncoverage\nmypy\n",
        "scripts/install": "#!/bin/sh\npip install -r requirements.txt\n",
        "scripts/test": "#!/bin/sh\ncoverage run -m pytest\n",
        "tests/test_a.py": "def test_a(): ...\n",
        ".github/workflows/test-suite.yml": WORKFLOW + """  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: scripts/install
      - run: scripts/test
""",
    })  # fmt: skip
    stack = detect_stack(repo, "HEAD")
    assert stack.python is not None and stack.python.extra_requirements == ("requirements.txt",)
    assert stack.python.sync_flags == ("--all-groups", "--extra cli")  # `-e .[cli]`: the project's extra, synced
    docker = python_dockerfile(stack.python)
    # The filtered copy sits beside the file so its own `-r` includes resolve (campaign 12: tracklater, oauthlib).
    assert "/deps/requirements.txt > /deps/.unbidden-extra-0.txt" in docker
    assert "uv pip install --python /deps/.venv/bin/python -r /deps/.unbidden-extra-0.txt" in docker


def test_a_host_without_a_port_goes_to_the_service_the_variable_names() -> None:
    """mealie: `POSTGRES_SERVER: localhost` beside an LDAP container; with two services the host stayed `localhost`
    and the suite could not reach its database (run 5)."""
    from unbidden.lab.testsuite import _to_sidecars  # pyright: ignore[reportPrivateUsage]
    from unbidden.observe.compose import Service

    def service(name: str, image: str, *ports: str) -> Service:
        return Service(name=name, image=image, build_context=None, dockerfile=None, environment={}, depends_on=(),
                       ports=ports)  # fmt: skip

    both = (service("postgres", "postgres:15", "5432"), service("ldap", "rroemhild/test-openldap", "10389", "10636"))
    assert _to_sidecars("localhost", both, "POSTGRES_SERVER") == "postgres"
    assert _to_sidecars("ldap://localhost:10389", both, "LDAP_SERVER_URL") == "ldap://ldap:10389"
    assert _to_sidecars("localhost", both, "LDAP_HOST") == "ldap"
    assert _to_sidecars("localhost", both, "SOME_HOST") == "postgres"  # the only database
    two = (*both, service("redis", "redis:7", "6379"))
    assert _to_sidecars("localhost", two, "SOME_HOST") == "localhost"  # two databases, nothing to say which
    assert _to_sidecars("redis://localhost/0", two, "CACHE_URL") == "redis://redis/0"


def test_a_pytest_internal_error_is_reported_where_it_happened() -> None:
    """TimeTracker: `pytest::internal` with 1500 characters of Alembic's log as the only explanation."""
    from unbidden.lab.testsuite import _ended  # pyright: ignore[reportPrivateUsage]
    from unbidden.sandbox.runner import SandboxResult

    out = "collected 112 items\nINTERNALERROR> Traceback (most recent call last):\nINTERNALERROR>   File x\n" + (
        "INFO  [alembic.runtime.migration] Running upgrade\n" * 60
    )
    result = SandboxResult(exit_code=3, stdout=out, stderr="", timed_out=False, duration_s=1.0,
                           stdout_truncated=False, stderr_truncated=False)  # fmt: skip
    why = _ended(result)
    assert why.startswith("exit 3: INTERNALERROR> Traceback") and "File x" in why and "alembic" in why


def test_a_crashed_pytest_is_a_round_that_told_nothing_and_is_retried_with_one_worker(tmp_path: Path) -> None:
    """TimeTracker: the JUnit report names `pytest::internal` when pytest itself crashed (an xdist worker died)."""
    from unittest.mock import patch

    from unbidden.lab import testsuite
    from unbidden.sandbox.runner import SandboxResult

    xml = tmp_path / "r.xml"
    xml.write_text(
        '<testsuites><testsuite><testcase classname="pytest" name="internal"><error message="internal error"/>'
        "</testcase></testsuite></testsuites>"
    )
    good = '<testsuites><testsuite><testcase classname="tests.a" name="t1"/></testsuite></testsuites>'
    calls: list[dict[str, str]] = []

    class Runner:
        def run(self, spec, work):  # type: ignore[no-untyped-def]
            calls.append(dict(spec.public_env))
            (work / testsuite.JUNIT_DIR / f"round-{len(calls)}.xml").write_text(
                xml.read_text() if len(calls) == 1 else good
            )
            return SandboxResult(exit_code=3 if len(calls) == 1 else 0, stdout="INTERNALERROR> Broken pipe\n",
                                 stderr="", timed_out=False, duration_s=1.0, stdout_truncated=False,
                                 stderr_truncated=False)  # fmt: skip

    plan = testsuite.TestPlan(argv=("pytest",), source="x", pytest=True)
    with (
        patch.object(testsuite, "data_services", lambda *_a, **_k: __import__("contextlib").nullcontext(None)),
        patch.object(
            testsuite,
            "sandbox_spec",
            lambda image, argv, public_env, timeout_s, network: type("S", (), {"public_env": public_env})(),
        ),
    ):
        summary = testsuite.run_suite(Runner(), tmp_path, None, plan, rounds=1)  # type: ignore[arg-type]
    assert summary.failed_per_round == [[]] and summary.round_status == ["ran"]
    assert calls[0]["PYTEST_XDIST_AUTO_NUM_WORKERS"] != "1" and calls[1]["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "1"
    assert summary.infra_why[0] is not None and "retried with one xdist worker" in summary.infra_why[0]


def test_the_compose_environment_is_not_the_ci_jobs(tmp_path: Path) -> None:
    """CTFd: docker-compose.yml's `UPLOAD_FOLDER=/var/uploads` and `DATABASE_URL=...@db` are the application
    container's; the CI job's tests run without them (11 failures on a read-only `/var/uploads`)."""
    from unbidden.lab.testsuite import test_plan

    repo = _repo(tmp_path, {
        "requirements.txt": "flask\n",
        "tests/test_a.py": "def test_a(): ...\n",
        "Dockerfile": "FROM python:3.11\n",
        "docker-compose.yml": "services:\n  ctfd:\n    build: .\n    environment:\n      - UPLOAD_FOLDER=/var/uploads\n"
                              "      - DATABASE_URL=mysql+pymysql://ctfd:ctfd@db/ctfd\n    depends_on:\n      - db\n"
                              "  db:\n    image: mariadb:10.11\n",
        ".github/workflows/ci.yml": WORKFLOW + """  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: python -m pytest
        env:
          TESTING_DATABASE_URL: 'sqlite://'
""",
    })  # fmt: skip
    plan = test_plan(repo, "HEAD", detect_stack(repo, "HEAD"), "python")
    assert plan is not None and plan.source.startswith("CI ci.yml")
    assert plan.env.get("TESTING_DATABASE_URL") == "sqlite://"
    assert "UPLOAD_FOLDER" not in plan.env and "DATABASE_URL" not in plan.env
