from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.brain.providers.mock import MockProvider
from unbidden.brain.router import Brain
from unbidden.config import load_config
from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.experiment import TestOutcome
from unbidden.contracts.finding import AnalyzerReport, Completeness
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.llm import Tier
from unbidden.contracts.opportunity import Opportunity
from unbidden.lab.fixlab import FixLab, added_suppressions
from unbidden.observe.analyzers import record_report
from unbidden.observe.stack import NodeStack, Stack
from unbidden.sandbox.provision import DependencyImage
from unbidden.sandbox.runner import SandboxResult, SandboxSpec
from unbidden.sandbox.tools import TOOLS
from unbidden.store import Store

pytestmark = pytest.mark.unit

IMAGE = DependencyImage(tag="deps", language="node", registries=[], env={}, links={})
STACK = Stack(
    node=NodeStack(
        manager="npm", lockfile="package-lock.json", major=22, major_assumed=False, typescript=True,
        eslint=False, biome=False, prettier=False, test_script="node --test",
    )
)  # fmt: skip


class FakeRunner:
    """tsc reports one error per line containing 'bug'; the tests fail if any file contains 'boom'."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
        self.calls.append(spec.argv)
        files = {p.relative_to(work).as_posix(): p.read_text() for p in work.rglob("*.ts")}
        if spec.argv[0] == "tsc":
            lines = [
                f"{path}({i},1): error TS2322: bug here"
                for path, text in files.items()
                for i, line in enumerate(text.splitlines(), 1)
                if "bug" in line
            ]
            return SandboxResult(2 if lines else 0, "\n".join(lines), "", False, 0.1, False, False)
        failed = any("boom" in t for t in files.values())
        return SandboxResult(1 if failed else 0, "", "", False, 0.1, False, False)


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "repo"
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "a.ts").write_text("const x = 1;\nconst y = bug;\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    rev = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return path, rev


def setup(store: Store, mandate: Mandate, repo: tuple[Path, str], *answers: Any) -> tuple[FixLab, Opportunity]:
    path, rev = repo
    runner = FakeRunner()
    result = runner.run(SandboxSpec(image="deps", argv=["tsc"]), path)
    report: AnalyzerReport = TOOLS["tsc"].parse(result, ["tsc"])
    assert report.completeness is Completeness.COMPLETE and report.findings
    (opp,) = record_report(store, report, rev).opened
    config = load_config()
    config.routing[Tier.LOCAL].provider = "mock"
    mock = MockProvider()
    mock.script("lab.fix_candidate", *answers)
    brain = Brain(config, {"mock": mock}, store, mandate)
    lab = FixLab(path, store, brain, STACK, {"node": IMAGE}, runner=runner, rounds=2)  # type: ignore[arg-type]
    return lab, opp


async def test_model_fix_reaches_level_4(store: Store, mandate: Mandate, repo: tuple[Path, str]) -> None:
    lab, opp = setup(store, mandate, repo, "// file: a.ts\n```ts\nconst x = 1;\nconst y = 2;\n```")
    result = await lab.run(opp)
    assert result.verdict is not None and result.verdict.improved
    assert result.verdict.evidence_level is EvidenceLevel.FUNCTIONAL_VALIDATION
    assert result.verdict.tests is TestOutcome.PASSED
    assert "-const y = bug;" in result.candidate.patch  # type: ignore[union-attr]


async def test_suppression_is_quarantined_then_repaired(store: Store, mandate: Mandate, repo: tuple[Path, str]) -> None:
    lab, opp = setup(
        store, mandate, repo,
        "// file: a.ts\nconst x = 1;\n// @ts-ignore\nconst y = 3;\n",
        "// file: a.ts\nconst x = 1;\nconst y = 3;\n",
    )  # fmt: skip
    result = await lab.run(opp)
    assert result.verdict is not None and result.verdict.improved
    assert any("quarantined" in n for n in result.notes)


async def test_regression_is_not_an_improvement(store: Store, mandate: Mandate, repo: tuple[Path, str]) -> None:
    breaking = "// file: a.ts\nconst x = 1;\nconst y = boom;\n"
    lab, opp = setup(store, mandate, repo, breaking, breaking)
    result = await lab.run(opp)
    assert result.verdict is not None and not result.verdict.improved
    assert result.verdict.tests is TestOutcome.REGRESSION


def test_suppression_detection() -> None:
    patch = "+++ b/a.py\n+x = f()  # type: ignore\n-y = 1  # noqa\n+// eslint-disable-next-line\n"
    assert added_suppressions(patch) == ["x = f()  # type: ignore", "// eslint-disable-next-line"]
