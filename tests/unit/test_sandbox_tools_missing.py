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
    assert system_packages_wanted(stack, allowed=True) == ("git", "make", "gettext")
    assert system_packages_wanted(stack, allowed=False) == ()
    node = NodeStack(manager="npm", lockfile="package-lock.json", major=22, major_assumed=False, typescript=True,
                     eslint=False, biome=False, prettier=False, test_script="node --test")  # fmt: skip
    assert system_packages_wanted(node, allowed=True) == ()
    docker = python_dockerfile(stack, headers=system_packages_wanted(stack, allowed=True))
    assert "apt-get install -y --no-install-recommends git make gettext" in docker


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
