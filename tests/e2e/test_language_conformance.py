"""Conformance of a language adapter, end to end in the real sandbox: what it declares, shown.

For each language: the project is detected, its dependency image builds from manifests only, its analyzer runs
offline and reports a planted finding at the right place, and its tests run offline and name the failing test (and
only it). An adapter's capabilities count only once this passes. Needs Docker and network for the image build;
marked slow, so it runs on demand: `uv run pytest -m slow tests/e2e/test_language_conformance.py`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from unbidden.lab.testsuite import run_suite
from unbidden.lab.testsuite import test_plan as plan_tests
from unbidden.observe.analyzers import run_tool
from unbidden.observe.stack import detect_stack
from unbidden.sandbox.provision import provision
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.sandbox.tools import tools_for

pytestmark = [pytest.mark.slow, pytest.mark.skipif(shutil.which("docker") is None, reason="needs Docker")]

GO_FIXTURE = {
    "go.mod": "module example.com/fixture\n\ngo 1.22\n",
    # The planted vet finding lives in a package without tests: `go test` runs part of vet first and would not
    # build the tests of a package that fails it, as the team's own CI would not.
    "report/report.go": 'package report\n\nimport "fmt"\n\nfunc Print() {\n\tfmt.Printf("%d\\n", "not a number")\n}\n',
    "calc.go": "package calc\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n",
    "calc_test.go": (
        'package calc\n\nimport "testing"\n\n'
        'func TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n\t\tt.Fatal("1+2")\n\t}\n}\n\n'
        'func TestPlantedFailure(t *testing.T) {\n\tt.Fatal("planted")\n}\n'
    ),
}


def _commit(repo: Path, files: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "fixture"], check=True)


def test_go_adapter_detects_provisions_analyzes_and_tests_offline(tmp_path: Path) -> None:
    _commit(tmp_path, GO_FIXTURE)
    stack = detect_stack(tmp_path, "HEAD")
    assert stack.languages == ["go"]
    go = stack.part("go")
    assert go.version == "1.22" and go.has_tests

    image = provision(tmp_path, "HEAD", go)
    assert image.language == "go" and image.env["GOPROXY"] == "off"

    runner = SandboxRunner()
    (vet,) = tools_for(stack)
    report = run_tool(runner, tmp_path, "HEAD", vet, image)
    assert report.completeness.value == "complete", report.error
    assert [(f.rule, f.path, f.line) for f in report.findings] == [("printf", "report/report.go", 6)]

    plan = plan_tests(tmp_path, "HEAD", stack, "go")
    assert plan is not None and plan.report == "go-test-json"
    work = snapshot(tmp_path, "HEAD")
    try:
        summary = run_suite(runner, work, image, plan, rounds=1)
    finally:
        discard(work)
    # The planted failure by name, and the package whose vet step fails under `go test`, as the team's CI would see it.
    assert summary.failed_per_round == [
        ["example.com/fixture/TestPlantedFailure", "example.com/fixture/report (package)"]
    ]
