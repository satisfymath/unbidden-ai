"""`start` refuses a key the service refused and warns about one it could not prove; a proven key starts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.cli import main
from unbidden.guardian.credentials import reset
from unbidden.setup import keycheck, machine
from unbidden.setup.requirements import start_checks
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit

KEY = "LLM|1234567890|abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    reset()
    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    monkeypatch.chdir(repo)
    assert main(["init", "--json"]) == 0
    assert main(["models", "frontier"]) == 0
    return Workspace.find()


def _names(checks: list[Any]) -> list[str]:
    return [c.name for c in checks]


def test_without_a_key_the_api_option_is_refused_with_the_command_that_fixes_it(ws: Workspace) -> None:
    verdict = start_checks(ws, docker_timeout_s=0.1)
    refused = [c for c in verdict.refused if c.name == "meta api"]
    assert refused and refused[0].fix == "unbidden key set" and "no MODEL_API_KEY" in refused[0].detail


def test_a_refused_key_refuses_the_start_and_a_proven_one_does_not(ws: Workspace, monkeypatch: Any) -> None:
    from unbidden.setup import wizard

    machine.write_env(machine.machine_env(), {"MODEL_API_KEY": KEY})
    reset()
    monkeypatch.setattr(
        wizard, "probe_remote", lambda w, **kw: {"ok": False, "why": "ProviderUnauthorized: meta 401: refused"}
    )
    verdict = start_checks(ws, docker_timeout_s=0.1)
    refused = [c for c in verdict.refused if c.name == "meta api"]
    assert refused and "refused by the service" in refused[0].detail and refused[0].fix == "unbidden key set"

    keycheck.forget("MODEL_API_KEY")
    monkeypatch.setattr(wizard, "probe_remote", lambda w, **kw: {"ok": True, "model": "muse-spark-1.3", "usd": 0.0})
    verdict = start_checks(ws, docker_timeout_s=0.1)
    assert "meta api" not in _names(verdict.refused) + _names(verdict.warnings)
    assert keycheck.recall("MODEL_API_KEY", KEY) is not None, "remembered: the next start pays nothing"


def test_a_key_that_cannot_be_proven_now_only_warns(ws: Workspace, monkeypatch: Any) -> None:
    from unbidden.setup import wizard

    machine.write_env(machine.machine_env(), {"MODEL_API_KEY": KEY})
    reset()
    monkeypatch.setattr(wizard, "probe_remote", lambda w, **kw: {"ok": False, "why": "ProviderError: unreachable"})
    verdict = start_checks(ws, docker_timeout_s=0.1)
    assert "meta api" not in _names(verdict.refused)
    warned = [c for c in verdict.warnings if c.name == "meta api"]
    assert warned and "not proven" in warned[0].detail and warned[0].fix == "unbidden key"
