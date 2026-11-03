"""Campaign 12, phase 6 (P2-5): a candidate goes through the team's formatter before it is measured or published."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.lab.fixlab import Candidate, FixLab, unified_patch
from unbidden.observe.ci import team_formatter
from unbidden.sandbox.provision import DependencyImage
from unbidden.sandbox.runner import SandboxResult, SandboxSpec

pytestmark = pytest.mark.unit
IMAGE = DependencyImage(tag="deps", language="python", registries=[], env={}, links={})


def test_the_formatter_the_ci_checks_with_is_the_one_that_formats() -> None:
    assert team_formatter("black --check --diff .") == ("black",)
    assert team_formatter("uv run ruff format --check src tests") == ("ruff", "format")
    assert team_formatter("ruff check .\npytest") is None  # lint only: no formatting standard to keep
    assert team_formatter(None) is None


class Formatter:
    """`black <files>` normalises `x=1` to `x = 1`; anything else runs clean."""

    def __init__(self, present: bool = True) -> None:
        self.present, self.calls = present, []

    def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
        self.calls.append(list(spec.argv))
        if spec.argv[0] == "black":
            if not self.present:
                return SandboxResult(127, "", "sh: black: not found", False, 0.1, False, False)
            for path in spec.argv[1:]:
                target = work / path
                target.write_text(target.read_text().replace("x=1", "x = 1"))
        return SandboxResult(0, "", "", False, 0.1, False, False)


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "repo"
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "a.py").write_text("x = 2\n")
    (path / "b.py").write_text("y = 0\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    rev = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return path, rev


def _lab(repo: Path, runner: Formatter) -> FixLab:
    lab = FixLab.__new__(FixLab)
    lab.repo, lab.runner = repo, runner  # type: ignore[assignment]
    return lab


def test_a_candidate_is_formatted_the_teams_way_and_its_patch_rewritten(repo: tuple[Path, str]) -> None:
    path, rev = repo
    runner = Formatter()
    files = {"a.py": "x=1\n"}
    candidate = Candidate("model", files, unified_patch(path, files))
    notes: list[str] = []
    out = _lab(path, runner)._in_team_format(rev, candidate, IMAGE, ("black",), ".", notes)  # pyright: ignore[reportPrivateUsage]
    assert runner.calls == [["black", "a.py"]]
    assert out.files == {"a.py": "x = 1\n"} and "+x = 1" in out.patch and "x=1" not in out.patch
    assert notes == ["candidate formatted with the team's black: a.py"]
    # Already formatted: unchanged, nothing noted.
    again = _lab(path, runner)._in_team_format(rev, out, IMAGE, ("black",), ".", notes)  # pyright: ignore[reportPrivateUsage]
    assert again.files == out.files and len(notes) == 1


def test_a_formatter_the_environment_lacks_is_noted_and_the_candidate_kept(repo: tuple[Path, str]) -> None:
    path, rev = repo
    files = {"a.py": "x=1\n"}
    candidate = Candidate("model", files, unified_patch(path, files))
    notes: list[str] = []
    out = _lab(path, Formatter(present=False))._in_team_format(rev, candidate, IMAGE, ("black",), ".", notes)  # pyright: ignore[reportPrivateUsage]
    assert out is candidate and notes == ["black: not in the project's environment; the candidate was not formatted"]
