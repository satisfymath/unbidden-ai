"""Delivery E's integration points: a complete read of zero rows is not missing data; an unreadable memory size is
unknown, not zero; doctor names the Docker plugins the engine needs; the egress listing includes a dashboard served
apart, with its origin."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.brain import hardware
from unbidden.brain.hardware import Machine, recommend
from unbidden.cli import docker_plugins, main
from unbidden.contracts.guardian import EgressAttempt, EgressVerdict
from unbidden.store import Store
from unbidden.web.contracts import DataRef
from unbidden.web.datasets import resolve
from unbidden.web.sources import apart_store_path, live
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "init"], check=True)  # fmt: skip
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    assert main(["init"]) == 0
    Workspace(tmp_path).store().close()
    return tmp_path


def test_zero_rows_from_a_whole_collection_is_complete_and_a_missing_entity_is_missing(repo: Path) -> None:
    src = live(repo)
    opps = resolve(src, DataRef(dataset="opportunities"))
    assert opps.rows == [] and opps.provenance.completeness == "complete"
    assert "zero rows" in (opps.provenance.note or "")
    samples = resolve(src, DataRef(dataset="experiment.samples", params={"experiment_id": "exp_nothing"}))
    assert samples.rows == [] and samples.provenance.completeness == "missing"


def test_an_unreadable_memory_size_is_unknown_and_sizes_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware, "_run", lambda *argv: "")
    monkeypatch.setattr(hardware.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "arm64")
    machine = hardware.detect()
    assert machine.known is False and machine.total_gb == 0.0
    assert "unknown" in machine.describe and "0 GB" not in machine.describe
    rec = recommend(machine, {"llama3.2:3b"})
    assert rec.fits is False and "memory unknown" in rec.reason and rec.profile_hint == "frontier"
    known = Machine(64.0, True, 0.0, "Apple")
    assert known.known and "64 GB" in known.describe


def test_doctor_names_the_docker_plugins_the_engine_needs() -> None:
    class Out:
        def __init__(self, code: int, out: str = "", err: str = "") -> None:
            self.returncode, self.stdout, self.stderr = code, out, err

    def legacy(argv: list[str], **_: Any) -> Out:
        if argv[1] == "buildx":
            return Out(125, "", "docker: 'buildx' is not a docker command.")
        return Out(0, "Docker Compose version v2.40.0")

    checks = dict((name, (ok, detail)) for name, ok, detail in docker_plugins(True, run=legacy))
    assert checks["docker buildx"][0] is False and "sandbox cannot build" in checks["docker buildx"][1]
    assert checks["docker compose"] == (True, "Docker Compose version v2.40.0")
    assert all(not ok for _, ok, _ in docker_plugins(False, run=legacy)), "without the daemon neither is usable"


def test_the_egress_listing_includes_a_dashboard_served_apart_with_its_origin(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def attempt(purpose: str) -> EgressAttempt:
        verdict = EgressVerdict(
            allowed=True, kind="synthetic_task", destination="api.meta.ai", reasons=[], payload_sha256="0" * 64,
            payload_bytes=1,
        )  # fmt: skip
        return EgressAttempt(
            status="allowed_sent", purpose=purpose, destination="api.meta.ai", provider="meta", model="m",
            payload="p", verdict=verdict,
        )  # fmt: skip

    engine = Workspace(repo).store()
    engine.put("egress", attempt("research.robustness"))
    engine.close()
    apart = Store(apart_store_path(f"live:{repo.name}"))  # what the standalone dashboard's chat writes
    apart.put("egress", attempt("chat.analyze"))
    apart.close()
    assert main(["egress", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {(r["purpose"], r["origin"]) for r in rows} == {
        ("research.robustness", "engine"),
        ("chat.analyze", "dashboard apart"),
    }
    assert main(["egress"]) == 0
    text = capsys.readouterr().out
    assert "chat.analyze" in text and "dashboard apart" in text and "research.robustness" in text
