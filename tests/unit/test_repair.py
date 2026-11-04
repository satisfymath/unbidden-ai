"""Campaign 13 (David's rule): the team's own failing tests are repaired only when the team's CI fails them too, by
changing the code they test, never the tests; proven by 3 of 3 rounds and no regression."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.experiment import TestOutcome, TestSummary
from unbidden.contracts.opportunity import OpportunityStatus
from unbidden.lab import repair
from unbidden.lab.repair import (
    RepairLab,
    always_failing,
    ci_evidence,
    frames,
    repair_opportunities,
    weakening,
)
from unbidden.store import Store

pytestmark = pytest.mark.unit

TRACKED = ["src/calc/core.py", "src/calc/__init__.py", "tests/test_core.py", "tests/conftest.py"]
TRACEBACK = """def test_add():
>       assert add(2, 2) == 4
E       assert 5 == 4

tests/test_core.py:4: AssertionError
/home/runner/work/calc/calc/src/calc/core.py:2: in add
  File "/usr/lib/python3.12/site-packages/pytest/__init__.py", line 3"""


def test_only_a_failure_the_teams_ci_shares_is_the_repositorys() -> None:
    assert ci_evidence("green", True) is None  # GitHub passes it: the failure is our environment's
    assert ci_evidence(None, False) is None  # the team's job passed its tests here
    assert ci_evidence("red", False) is None  # red for another reason: the job's tests passed here
    assert ci_evidence(None, None) is None  # nothing shows it
    assert "test step" in (ci_evidence(None, True) or "")
    assert "red" in (ci_evidence("red", None) or "")


def test_paths_in_a_traceback_are_matched_to_the_repositorys_files() -> None:
    assert frames(TRACEBACK, TRACKED) == ["tests/test_core.py", "src/calc/core.py"]
    assert repair.test_file_of("tests.test_core::test_add", TRACKED) == "tests/test_core.py"
    assert repair.test_file_of("test_core.TestX::test_a", TRACKED) == "tests/test_core.py"


def test_one_opportunity_per_test_file_without_the_environments_failures() -> None:
    record = {"failed": ["tests.test_core::test_add", "tests.test_core::test_git", "<suite>"],
              "failure_texts": {"tests.test_core::test_add": TRACEBACK},
              "could_not_run": {"tests": 1, "lacks": ["git"], "by_test": ["tests.test_core::test_git"]}}  # fmt: skip
    (opp,) = repair_opportunities("a" * 40, record, TRACKED, "the team's CI on GitHub is red on this commit")
    assert opp.source == "repair" and opp.details["tests"] == ["tests.test_core::test_add"]
    assert opp.details["paths"] == ["src/calc/core.py"] and "red" in opp.summary


def test_a_failure_the_environment_causes_is_never_repaired() -> None:
    browser = ("E   playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist at "
               "/home/runner/.cache/ms-playwright/chromium")  # fmt: skip
    record = {
        "failed": ["tests.test_core::test_ui", "tests.test_core::test_add"],
        "failure_texts": {"tests.test_core::test_ui": browser, "tests.test_core::test_add": TRACEBACK},
    }
    (opp,) = repair_opportunities("c" * 40, record, TRACKED, "the team's CI on GitHub is red on this commit")
    assert opp.details["tests"] == ["tests.test_core::test_add"]
    only = {"failed": ["tests.test_core::test_ui"], "failure_texts": {"tests.test_core::test_ui": browser}}
    assert repair_opportunities("c" * 40, only, TRACKED, "red") == []


def test_a_repair_that_hides_the_failure_is_refused() -> None:
    assert weakening("+x = 1\n", {"tests/test_core.py": ""}) is not None
    assert weakening("+x = 1\n", {"src/calc/conftest.py": ""}) is not None
    assert "skips" in (weakening("+@pytest.mark.xfail\n", {"src/calc/core.py": ""}) or "")
    assert "exception" in (weakening("+    except Exception:\n", {"src/calc/core.py": ""}) or "")
    assert weakening("+    return a + b\n", {"src/calc/core.py": ""}) is None


def test_only_failures_of_every_round_are_targeted() -> None:
    s = TestSummary(rounds=3, failed_per_round=[["a", "b"], ["a"], ["a", "<suite>"]], round_status=["ran"] * 3)
    assert always_failing(s) == {"a"}


def _summary(failed: list[str]) -> TestSummary:
    return TestSummary(rounds=3, failed_per_round=[list(failed)] * 3, round_status=["ran"] * 3,
                       collected_per_round=[3] * 3,
                       failure_texts={n: TRACEBACK for n in failed})  # fmt: skip


class Brain:
    def __init__(self, answers: list[str]) -> None:
        self.answers, self.asked = answers, 0

    def where(self, _: str) -> str:
        return "the model"

    def author(self, _: str) -> str:
        return "model"

    async def complete(self, request: Any) -> Any:
        self.asked += 1
        return type("R", (), {"content": self.answers.pop(0)})()


async def test_the_lab_proves_a_repair_and_refuses_a_skip(tmp_path: Path, store: Store,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    repo = tmp_path / "calc"
    files = {"src/calc/__init__.py": "", "src/calc/core.py": "def add(a, b):\n    return a + b + 1\n",
             "tests/test_core.py": "from calc.core import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n",
             "tests/conftest.py": ""}  # fmt: skip
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    rev = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    (opp,) = repair_opportunities(rev, {"failed": ["tests.test_core::test_add"],
                                        "failure_texts": {"tests.test_core::test_add": TRACEBACK}},
                                  repair.tracked_files(repo, rev), "the team's CI on GitHub is red")  # fmt: skip
    store.put("opportunities", opp, key=opp.dedup_key)
    monkeypatch.setattr(repair, "test_plan", lambda *a: object())
    monkeypatch.setattr(repair, "provenance", lambda *a, **k: {})
    seen: list[dict[str, str]] = []

    def suite(self: RepairLab, rev: str, plan: Any, files: dict[str, str]) -> TestSummary:
        seen.append(files)
        fixed = "a + b + 1" not in files.get("src/calc/core.py", "a + b + 1")
        return _summary([] if fixed else ["tests.test_core::test_add"])

    monkeypatch.setattr(RepairLab, "_suite", suite)
    skip = ("# file: src/calc/core.py\n```python\nimport pytest\npytest.skip('x', allow_module_level=True)\n"
            "def add(a, b):\n    return a + b + 1\n```\n")  # fmt: skip
    good = "# file: src/calc/core.py\n```python\ndef add(a, b):\n    return a + b\n```\n"
    brain = Brain([skip, good])
    lab = RepairLab(repo, store, brain, object(), object(), attempts=2)  # type: ignore[arg-type]
    result = await lab.run(opp)
    assert brain.asked == 2 and "quarantined" in result.notes[0]
    assert result.verdict is not None and result.verdict.improved and result.verdict.tests is TestOutcome.PRE_EXISTING
    assert result.verdict.measurements[0].base == 1 and result.verdict.measurements[0].head == 0
    assert list(result.candidate.files) == ["src/calc/core.py"] if result.candidate else False
    assert opp.status is OpportunityStatus.EXPERIMENTING
    assert not any("before the change too" in c for c in result.verdict.caveats)
    assert len(seen) == 2  # the base once, the accepted candidate once (the skip never ran)


async def test_a_failure_that_does_not_reproduce_every_round_is_not_repaired(
    tmp_path: Path, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    (opp,) = repair_opportunities("b" * 40, {"failed": ["tests.test_core::test_add"]}, TRACKED, "red")
    monkeypatch.setattr(repair, "test_plan", lambda *a: object())
    flaky = TestSummary(rounds=3, failed_per_round=[["tests.test_core::test_add"], [], []], round_status=["ran"] * 3)
    monkeypatch.setattr(RepairLab, "_suite", lambda *a: flaky)
    brain = Brain([])
    result = await RepairLab(tmp_path, store, brain, object(), object()).run(opp)  # type: ignore[arg-type]
    assert brain.asked == 0 and result.verdict is None and "deterministic" in (result.absent or "")


def test_when_the_traceback_stops_in_the_test_the_called_code_is_found() -> None:
    from unbidden.lab.repair import defined_by

    test = (
        "import pytest\nfrom calc import add, mul\n\n@pytest.mark.parametrize('a', [1])\n"
        "def test_add(a):\n    assert add(a, 1) == 2\n"
    )
    code = {"src/calc/core.py": "def add(a, b):\n    return a - b\n", "src/calc/other.py": "def mul(a, b): ...\n",
            "tools/add.py": "def add(): ...\n"}  # fmt: skip
    found = defined_by(test, "tests.test_core::test_add[1]", [*TRACKED, *code], lambda p: code.get(p, ""))
    assert found == ["src/calc/core.py"]
