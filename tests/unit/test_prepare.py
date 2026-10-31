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
