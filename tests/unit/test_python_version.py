"""Which Python reproduces a project (stage 8): chosen from its declarations, never the host's or a silent default.

Found on Conduit (frozen run 9ef6a60): the project declares Python ^3.9 in Poetry's section and runs its CI and its
image on 3.9; Unbidden read only PEP 621's requires-python and built on 3.12, where its 2022 pins have no wheels."""

from __future__ import annotations

import pytest

from unbidden.observe.python_version import DEFAULT, admits, choose
from unbidden.sandbox.provision import missing_packages, needs_system_build

pytestmark = pytest.mark.unit
CI = "jobs:\n  t:\n    strategy:\n      matrix:\n        python-version: [{versions}]\n"


def project(files: dict[str, str]):  # type: ignore[no-untyped-def]
    return choose(lambda p: files[p], set(files))


def test_conduit_poetry_ci_and_dockerfile_agree_on_3_9() -> None:
    choice = project({
        "pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.9"\n',
        "poetry.lock": '[[package]]\nname = "x"\n\n[metadata]\npython-versions = "^3.9"\n',
        ".github/workflows/tests.yml": CI.format(versions="3.9"),
        "Dockerfile": "FROM python:3.9.10-slim\n",
    })  # fmt: skip
    assert choice.version == "3.9" and "CI" in choice.rule and not choice.conflicts


def test_an_incompatible_concrete_version_is_not_chosen_and_is_a_conflict() -> None:
    choice = project({
        "pyproject.toml": '[project]\nrequires-python = ">=3.10,<3.12"\n',
        ".github/workflows/ci.yml": CI.format(versions="3.9, 3.11, 3.12"),
    })  # fmt: skip
    assert choice.version == "3.11"  # 3.9 and 3.12 are excluded by the constraint; the oldest admitted CI version
    assert any("3.9" in c and "requires-python" in c for c in choice.conflicts)


def test_conflicting_concrete_sources_follow_the_written_order_and_say_so() -> None:
    choice = project({
        "pyproject.toml": '[project]\nrequires-python = ">=3.9"\n',
        ".github/workflows/ci.yml": CI.format(versions='"3.11"'),
        "Dockerfile": "FROM python:3.10-slim\n",
        ".python-version": "3.12.1\n",
    })  # fmt: skip
    assert choice.version == "3.11" and "CI" in choice.rule
    assert any("disagree" in c for c in choice.conflicts)


def test_a_range_alone_is_a_choice_and_nothing_declared_is_the_default_said() -> None:
    ranged = project({"pyproject.toml": '[project]\nrequires-python = ">=3.10"\n'})
    assert ranged.version == "3.10" and "a choice" in ranged.rule
    nothing = project({"requirements.txt": "flask\n"})
    assert nothing.version == DEFAULT and "declares no Python version" in nothing.rule
    impossible = project({"pyproject.toml": '[project]\nrequires-python = "<3.6"\n'})
    assert "no supported version" in " ".join(impossible.conflicts)


@pytest.mark.parametrize(
    ("spec", "yes", "no"),
    [("^3.9", "3.11", "3.8"), ("~3.9", "3.9", "3.10"), (">=3.8,<3.11", "3.10", "3.11"), ("3.9.*", "3.9", "3.10"),
     (">=3.8 <3.10", "3.9", "3.10"), ("^3.8 || ^3.11", "3.11", None), ("!=3.10", "3.11", "3.10")],
)  # fmt: skip
def test_constraint_forms(spec: str, yes: str, no: str | None) -> None:
    assert admits(spec, yes)
    if no is not None:
        assert not admits(spec, no)


def test_build_failures_that_need_the_system_are_recognised() -> None:
    pg = "Error: pg_config executable not found.\npg_config is required to build psycopg2 from source."
    gcc = "error: [Errno 2] No such file or directory: 'gcc'"
    header = "src/x.c:1:10: fatal error: libpq-fe.h: No such file or directory"
    assert needs_system_build(pg) and needs_system_build(gcc) and needs_system_build(header)
    assert not needs_system_build("ERROR: No matching distribution found for nothing-like-this==9")
    assert missing_packages(pg) == ["libpq-dev"]


def test_stack_detection_uses_the_projects_python(tmp_path: object) -> None:
    import subprocess
    from pathlib import Path

    from unbidden.observe.stack import detect_stack

    repo = Path(str(tmp_path))
    (repo / "pyproject.toml").write_text('[tool.poetry]\nname = "app"\n[tool.poetry.dependencies]\npython = "^3.9"\n')
    (repo / "poetry.lock").write_text('[[package]]\nname = "fastapi"\nversion = "0.79.1"\n\n[metadata]\n'
                                      'python-versions = "^3.9"\ncontent-hash = "x"\n')  # fmt: skip
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "tests.yml").write_text(CI.format(versions="3.9"))
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    python = detect_stack(repo).python
    assert python is not None and python.version == "3.9"  # c804aaf..9ef6a60: 3.12, the default


def test_environments_before_3_12_are_seeded_as_they_were() -> None:
    from unbidden.observe.stack import PythonStack
    from unbidden.sandbox.provision import python_dockerfile

    old = PythonStack(version="3.9", lockfile="poetry.lock", manifest="poetry.lock", ruff=False, pyright=False,
                      pytest=True, lock_date="2022-08-21T12:00:00+00:00")  # fmt: skip
    new = PythonStack(version="3.12", lockfile="poetry.lock", manifest="poetry.lock", ruff=False, pyright=False,
                      pytest=True)  # fmt: skip
    # Conduit: aiosql imports pkg_resources; today's setuptools lacks it or warns, which its suite makes an error.
    assert "--exclude-newer 2022-08-21T12:00:00+00:00 setuptools pip" in python_dockerfile(old)
    assert "setuptools" not in python_dockerfile(new).split("uv venv /deps/.venv")[1].split("-r ")[0]


def test_the_projects_own_package_is_registered_as_uv_sync_would_install_it() -> None:
    """Found on LNbits (stage 8 independent run, 6bbf3a1): only its dependencies were installed, and importing it
    failed on `importlib.metadata.version("lnbits")`. The image now registers the project itself, editable."""
    from unbidden.observe.stack import PythonStack, own_package
    from unbidden.sandbox.provision import python_dockerfile

    package = {"project": {"name": "my-app", "version": "1.2.0"}, "build-system": {"requires": ["hatchling"]}}
    assert own_package(package) == ("my-app", "1.2.0")
    assert own_package({"project": {"name": "my-app", "dynamic": ["version"]}, "build-system": {}}) == (
        "my-app",
        "0.0.0",
    )
    assert own_package({"project": {"name": "scripts-only"}}) is None  # not a package: uv sync installs nothing
    stack = PythonStack(version="3.12", lockfile="uv.lock", manifest="pyproject.toml", ruff=False, pyright=False,
                        pytest=True, own=("my-app", "1.2.0"))  # fmt: skip
    built = python_dockerfile(stack)
    assert "my_app-1.2.0.dist-info" in built and "Name: my-app" in built and "_unbidden_my_app.pth" in built
    assert "dist-info" not in python_dockerfile(PythonStack(version="3.12", lockfile="uv.lock",
                                                            manifest="pyproject.toml", ruff=False, pyright=False,
                                                            pytest=True))  # fmt: skip
