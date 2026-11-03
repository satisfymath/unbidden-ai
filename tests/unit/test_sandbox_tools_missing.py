"""Campaign 12, phase 6 (P1-3): the programs a CI runner has and a slim image lacks, and what the record says when
the test command needs one the image does not have."""

from __future__ import annotations

import pytest

from unbidden.lab.testsuite import environment_lacks
from unbidden.observe.ci import apt_packages
from unbidden.observe.stack import NodeStack, PythonStack
from unbidden.sandbox.provision import python_dockerfile, system_packages_wanted
from unbidden.sandbox.runner import SandboxResult

pytestmark = pytest.mark.unit


def test_an_apt_install_after_an_update_on_the_same_line_is_read() -> None:
    # humanize's CI: one line, the update first.
    assert apt_packages("sudo apt-get update && sudo apt-get install -y gettext") == ("gettext",)
    assert apt_packages("sudo apt update; sudo apt install -y --no-install-recommends make libpq-dev") == (
        "make",
        "libpq-dev",
    )
    assert apt_packages("sudo apt-get install gettext\n") == ("gettext",)
    assert apt_packages("echo apt-get install nothing-here-no") == ()


def test_the_runners_baseline_goes_into_the_image_only_when_debian_is_allowed() -> None:
    stack = PythonStack(version="3.12", lockfile=None, manifest="pyproject.toml", ruff=True, pyright=False, pytest=True,
                        system_packages=("gettext",))  # fmt: skip
    assert system_packages_wanted(stack, allowed=True) == ("git", "make", "locales", "gettext")
    assert system_packages_wanted(stack, allowed=False) == ()
    node = NodeStack(manager="npm", lockfile="package-lock.json", major=22, major_assumed=False, typescript=True,
                     eslint=False, biome=False, prettier=False, test_script="node --test")  # fmt: skip
    assert system_packages_wanted(node, allowed=True) == ()
    docker = python_dockerfile(stack, headers=system_packages_wanted(stack, allowed=True))
    assert "apt-get install -y --no-install-recommends git make locales gettext" in docker
    assert "locale-gen en_US.UTF-8" in docker and "useradd -u 1000" in docker and "LANG=C.UTF-8" in docker


def _result(stderr: str, stdout: str = "", code: int = 127) -> SandboxResult:
    return SandboxResult(code, stdout, stderr, False, 0.1, False, False)


def test_a_missing_program_is_named_with_what_would_provide_it() -> None:
    assert environment_lacks(_result("bash: line 4: task: command not found")) == (
        "the sandbox image lacks `task`, which the test command needs (go-task, which its CI installs with an action "
        "(go-task/setup-task), not from a package registry)"
    )
    make = environment_lacks(_result("bash: line 4: make: command not found"))
    assert make is not None and make.startswith("the sandbox image lacks `make`") and "deb.debian.org" in make
    msgfmt = environment_lacks(_result("scripts/generate-translation-binaries.sh: line 7: msgfmt: command not found"))
    assert msgfmt is not None and "Debian's `gettext`" in msgfmt
    assert environment_lacks(_result("zsh: command not found: just")) is not None
    unknown = environment_lacks(_result("sh: 1: frobnicate: command not found"))
    assert unknown is not None and "not a package the sandbox knows" in unknown
    assert environment_lacks(_result("E   ImportError: no module named x", code=1)) is None


def test_the_snapshot_gets_a_repository_and_the_test_plan_drops_docs_builds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    from unbidden.observe.ci import _DOCS_BUILD  # pyright: ignore[reportPrivateUsage]
    from unbidden.sandbox.runner import with_git

    work = tmp_path / "w"
    (work / "pkg").mkdir(parents=True)
    (work / "pkg" / "a.py").write_text("x = 1\n")
    (work / ".venv").symlink_to(tmp_path)
    with_git(work, "abc123", exclude=[".venv"])
    listed = subprocess.run(["git", "-C", str(work), "ls-files"], capture_output=True, text=True).stdout.split()
    assert listed == ["pkg/a.py"]  # the dependency link is not part of the checkout
    with_git(work, "abc123")  # idempotent
    assert _DOCS_BUILD.search('uv run --frozen --extra dev make -C docs html SPHINXOPTS="-W"')
    assert _DOCS_BUILD.search("sphinx-build -b html docs out") and _DOCS_BUILD.search("mkdocs build --strict")
    assert not _DOCS_BUILD.search("make test") and not _DOCS_BUILD.search("pytest docs/")


def test_the_base_suite_is_run_once_per_commit_plan_and_image(tmp_path, store) -> None:  # type: ignore[no-untyped-def]
    from unbidden.lab.fixlab import FixLab
    from unbidden.lab.testsuite import TestPlan
    from unbidden.sandbox.provision import DependencyImage

    calls: list[int] = []
    lab = FixLab.__new__(FixLab)
    lab.store, lab.rounds, lab.progress, lab.runner = store, 1, lambda *_: None, None  # type: ignore[assignment]

    def fake(runner, work, image, plan, rounds):  # type: ignore[no-untyped-def]
        from unbidden.contracts.experiment import TestSummary

        calls.append(1)
        return TestSummary(rounds=1, failed_per_round=[[]], round_status=["ran"], collected_per_round=[3])

    import unbidden.lab.fixlab as fixlab

    original = fixlab.run_suite
    fixlab.run_suite = fake  # type: ignore[assignment]
    try:
        image = DependencyImage(tag="deps:1", language="python", registries=[], env={}, links={})
        plan = TestPlan(argv=("pytest",), source="ci", pytest=True)
        first = lab._baseline("a" * 40, tmp_path, image, plan)  # pyright: ignore[reportPrivateUsage]
        again = lab._baseline("a" * 40, tmp_path, image, plan)  # pyright: ignore[reportPrivateUsage]
        other = lab._baseline("b" * 40, tmp_path, image, plan)  # pyright: ignore[reportPrivateUsage]
    finally:
        fixlab.run_suite = original  # type: ignore[assignment]
    assert len(calls) == 2 and first == again and other.rounds == 1


def test_coverage_flags_and_named_environment_causes() -> None:
    from unbidden.observe.ci import _COV_FLAG  # pyright: ignore[reportPrivateUsage]

    strip = lambda line: _COV_FLAG.sub("", line)  # noqa: E731
    assert strip("python -m pytest --cov=mss --cov-report=xml -v") == "python -m pytest -v"
    assert strip("pytest --cov src --cov-report term tests/") == "pytest tests/"
    assert strip("pytest --cov tests/unit") == "pytest tests/unit"  # a test path is never taken as the flag's value
    assert strip("pytest -x") == "pytest -x"
    from unbidden.lab.testsuite import TestPlan, without_coverage

    plan = TestPlan(argv=("bash", "-c", "python -m pytest --cov=mss --cov-report=xml -v"), source="ci", pytest=True)
    stripped = without_coverage(plan)
    assert stripped is not None and stripped.argv == ("bash", "-c", "python -m pytest -v")
    assert without_coverage(stripped) is None
    su = environment_lacks(_result("Password: su: Authentication failure", code=1))
    assert su is not None and "switches user" in su
    net = environment_lacks(_result("Failed to resolve 'pypi.org' ([Errno -3] Temporary failure in name resolution)",
                                    code=1))  # fmt: skip
    assert net is not None and "network" in net
