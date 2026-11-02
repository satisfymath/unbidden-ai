"""The app's actions are the CLI's operations: the kill switch files, the inbox's order, the record behind /why."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.cli import main
from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.opportunity import Opportunity
from unbidden.tui import actions
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    return tmp_path


def test_kill_and_resume_toggle_the_file_and_say_so(repo: Path) -> None:
    ws = Workspace.find()
    assert actions.kill(ws, "testing")[0].accent and (repo / ".unbidden" / "KILL").exists()
    assert actions.kill(ws, "")[0].text == "The kill switch is already engaged."
    assert actions.resume(ws)[0].text.startswith("Kill switch released")
    assert not (repo / ".unbidden" / "KILL").exists()
    assert actions.resume(ws)[0].text == "The kill switch was not engaged."


def _opp(id_: str, level: int, title: str) -> Opportunity:
    return Opportunity(
        id=id_, source="test", category="perf", title=title, summary=title, dedup_key=id_,
        evidence_level=EvidenceLevel(level), evidence=[EvidenceRef(kind="config", locator="x")],
    )  # fmt: skip


def test_inbox_sorts_by_evidence_and_why_reads_the_record(repo: Path) -> None:
    ws = Workspace.find()
    store = ws.store()
    store.put("opportunities", _opp("opp_a", 2, "reproduced"))
    store.put("opportunities", _opp("opp_b", 4, "validated"))
    rows = actions.inbox(store)
    assert [r[0] for r in rows] == ["opp_b", "opp_a"] and rows[0][1] == "L4 validated"
    lines = actions.why(store, "opp_b")
    assert lines[0].text.startswith("[bold]validated[/] · L4")
    assert actions.why(store, "opp_zz")[0].text == "No opportunity opp_zz."
    store.close()
