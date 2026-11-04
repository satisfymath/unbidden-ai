"""Preparation as a capability of the product (campaign to v1.0, C1): from a repository to the checks record, with
provenance; the benchmark's checks and the daemon's observe.checks share this path."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.observe import prepare

pytestmark = pytest.mark.unit


def _repo(tmp_path: Path) -> Path:
    files = {
        "pyproject.toml": '[project]\nname = "app"\nrequires-python = ">=3.11"\n',
        ".python-version": "3.12\n",
        ".github/workflows/ci.yml": "on: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: pytest tests\n",
        "tests/test_a.py": "def test_a(): ...\n",
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return tmp_path


def test_prepare_copies_apart_reads_the_stack_with_provenance_and_records_the_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _repo(tmp_path / "src")
    mandate = Mandate(workspace="t")
    mandate.autonomy.provision_dependencies = Autonomy.ALLOW
    image = type("Img", (), {"tag": "img:1", "notes": ("no lockfile",), "links": {}})()
    monkeypatch.setattr(prepare, "provision", lambda *a, **k: image)
    monkeypatch.setattr(prepare, "link_dependencies", lambda *a, **k: None)
    monkeypatch.setattr(prepare, "snapshot", lambda repo, rev: tmp_path / "work")
    monkeypatch.setattr(prepare, "discard", lambda work: None)
    from unbidden.contracts.experiment import TestSummary

    monkeypatch.setattr(prepare, "run_suite", lambda *a, **k: TestSummary(
        rounds=1, failed_per_round=[["t::b"]], round_status=["ran"], collected_per_round=[12], infra_why=[None]
    ))  # fmt: skip
    record = prepare.prepare(str(source), tmp_path / "copy", mandate)
    assert (tmp_path / "copy" / ".git").exists() and record["copy"].endswith("copy")
    assert record["stack"]["python"] == "3.12" and any(".python-version" in w for w in record["stack"]["why"])
    assert record["plan"]["source"].startswith("CI ci.yml") and record["image"]["tag"] == "img:1"
    assert record["status"] == "failed" and record["collected"] == 12 and record["failed"] == ["t::b"]


def test_a_block_is_the_finding_never_an_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _repo(tmp_path / "src")

    def refuse(*a: object, **k: object) -> None:
        raise RuntimeError("registry pypi.org is not in the mandate's allowlist")

    monkeypatch.setattr(prepare, "provision", refuse)
    record = prepare.checks_record(source, "HEAD", Mandate(workspace="t"))
    assert record["status"] == "blocked" and "allowlist" in str(record["why"]) and "stack" in record


def test_the_scope_diagnosis_says_what_is_in_and_out_and_why(tmp_path: Path) -> None:
    from unbidden.observe.scope import diagnose

    checks = dict((n, (ok, why)) for n, ok, why in diagnose(_repo(tmp_path / "py")))
    assert checks["scope: stack"][0] and "Python 3.12" in checks["scope: stack"][1]
    assert checks["scope: tests"][0] and "ci.yml > test" in checks["scope: tests"][1]
    assert not checks["scope: database"][0] and "no database service" in checks["scope: database"][1]
    other = tmp_path / "go"
    other.mkdir()
    (other / "go.mod").write_text("module x\n")
    (other / "main.go").write_text("package main\n")
    git = ["git", "-C", str(other), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    out = diagnose(other)
    assert out[0][0] == "scope: stack" and not out[0][1] and "Python only" in out[0][2]


def test_a_long_error_keeps_its_cause_and_its_end() -> None:
    text = "error: No solution found: foo==1 depends on bar>2\n" + "x" * 5000 + "\nexit code: 1"
    kept = prepare.ends(text)
    assert kept.startswith("error: No solution found") and kept.endswith("exit code: 1") and len(kept) < 2000
