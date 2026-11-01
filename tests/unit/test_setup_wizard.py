"""The setup assistant: three options without YAML, Solo API without Ollama, autonomous explained and left valid,
credentials by name only, interruption and resumption, nothing written without a confirmation."""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from rich.console import Console

from unbidden.contracts.events import EventType
from unbidden.contracts.guardian import Mandate
from unbidden.guardian.credentials import broker
from unbidden.setup import machine
from unbidden.setup.requirements import doctor_requirements, explain
from unbidden.setup.wizard import Options, Scripted, SetupError, load_answers, run
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit

FAKE_KEY = "fake-key-0123456789abcdef"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "i",
        ],
        check=True,
    )
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Ollama, no Meta listing, no hardware surprises."""
    import unbidden.cli as cli
    import unbidden.runtime as runtime
    from unbidden.brain import hardware

    monkeypatch.setattr(runtime, "installed_models", lambda url: set())
    monkeypatch.setattr(
        cli, "meta_api_status", lambda key, get=None: (False, "the model listing refuses the key (401)")
    )
    monkeypatch.setattr(
        hardware,
        "detect",
        lambda: hardware.Machine(total_gb=16.0, apple_silicon=True, chip="test", gpu_gb=0.0),
    )


def console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=200, force_terminal=False, color_system=None), buf


def scripted(**answers: Any) -> Scripted:
    secrets = answers.pop("secrets", {})
    return Scripted(answers, secrets)


def mandate_of(repo: Path) -> Mandate:
    return Workspace(repo).mandate()


def events(repo: Path, type_: EventType) -> list[Any]:
    return [e for e in Workspace(repo).store().events() if e.type is type_]


def test_api_option_denies_local_inference_and_needs_no_ollama(repo: Path) -> None:
    out, buf = console()
    opts = Options(non_interactive=True, yes=True, models="api", mode="supervised", budget=5.0, dashboard="later")
    assert run(Workspace(repo), opts, out, io=scripted(models="api", mode="supervised", dashboard="later")) == 0
    mandate = mandate_of(repo)
    assert mandate.models.profile == "frontier"
    assert mandate.models.local_inference == "deny" and mandate.models.local_fallback == "deny"
    assert mandate.models.private_code_to_frontier == "deny"
    assert mandate.business_constraints.maximum_monthly_spend_usd == 5.0
    needs = doctor_requirements(mandate)
    assert needs["ollama"] == "optional" and needs["local model"] == "optional" and needs["meta api"] == "required"
    assert "optional" in explain(needs, mandate)
    assert "MANDATE_CHANGED" in buf.getvalue() or "written" in buf.getvalue()
    assert len(events(repo, EventType.MANDATE_CHANGED)) == 1
    assert not (repo / ".unbidden" / "setup.json").exists()


def test_local_and_mixed_options(repo: Path) -> None:
    out, _ = console()
    opts = Options(non_interactive=True, yes=True, models="local", mode="autopilot", budget=1.0, dashboard="never")
    assert run(Workspace(repo), opts, out, io=scripted(models="local", mode="autopilot", dashboard="never")) == 0
    mandate = mandate_of(repo)
    assert mandate.models.profile == "local" and mandate.models.local_inference == "allow"
    assert mandate.autonomy.open_pull_requests.value == "allow" and mandate.autonomy.merge_pull_requests.value == "deny"
    assert doctor_requirements(mandate)["ollama"] == "required"
    assert machine.load_prefs().dashboard == "never"

    opts = Options(non_interactive=True, yes=True, models="mixed", mode="supervised", budget=1.0, dashboard="later")
    assert run(Workspace(repo), opts, out, io=scripted(models="mixed", mode="supervised", dashboard="later")) == 0
    mandate = mandate_of(repo)
    assert mandate.models.profile == "local-first" and mandate.models.local_inference == "allow"
    assert doctor_requirements(mandate)["meta api"] == "optional"
    assert len(events(repo, EventType.MANDATE_CHANGED)) == 2


def test_autonomous_is_explained_and_the_configuration_stays_valid(repo: Path) -> None:
    out, buf = console()
    opts = Options(non_interactive=True, yes=True, models="local", mode="autonomous", budget=1.0, dashboard="never")
    assert run(Workspace(repo), opts, out, io=scripted(models="local", mode="autonomous", dashboard="never")) == 0
    text = buf.getvalue()
    assert "deploy_steps" in text and "drill" in text
    mandate = mandate_of(repo)
    assert mandate.autonomy.merge_pull_requests.value == "deny", "autonomous was not switched on"
    assert mandate.autonomy.open_pull_requests.value == "allow", "the fallback is autopilot"
    assert mandate.autonomy.act_on_connections.value == "deny"


def test_credentials_are_saved_by_name_and_never_shown(repo: Path) -> None:
    out, buf = console()
    env = machine.machine_env()
    env.parent.mkdir(parents=True)
    env.write_text("# shared\nOTHER_TOKEN=keep-me-please-1234\n")
    opts = Options(non_interactive=True, yes=True, models="api", mode="supervised", budget=1.0, dashboard="later",
                   model_key_stdin=True)  # fmt: skip
    io_ = scripted(models="api", mode="supervised", dashboard="later", secrets={"MODEL_API_KEY": FAKE_KEY})
    assert run(Workspace(repo), opts, out, io=io_) == 0
    values = machine.read_env(env)
    assert values["MODEL_API_KEY"] == FAKE_KEY and values["OTHER_TOKEN"] == "keep-me-please-1234"
    assert "# shared" in env.read_text()
    assert oct(env.stat().st_mode & 0o777) == "0o600"
    assert broker().has("MODEL_API_KEY")
    text = buf.getvalue()
    assert FAKE_KEY not in text and "MODEL_API_KEY saved" in text
    assert "refuses the key" in text and "does not mean inference fails" in text
    assert FAKE_KEY not in (repo / ".unbidden" / "mandate.yaml").read_text()
    for event in Workspace(repo).store().events():
        assert FAKE_KEY not in json.dumps(event.payload)
    changed = events(repo, EventType.MANDATE_CHANGED)[0]
    assert changed.payload["setup"]["credentials"] == ["MODEL_API_KEY"]


def test_probe_is_opt_in_and_refusing_it_still_saves(repo: Path) -> None:
    out, buf = console()
    calls: list[str] = []

    def probe(ws: Workspace) -> dict[str, Any]:
        calls.append(str(ws.repo))
        return {"ok": True, "model": "muse-spark-1.3", "usd": 0.0001}

    opts = Options(non_interactive=True, yes=True, models="api", mode="supervised", budget=1.0, dashboard="later",
                   model_key_stdin=True)  # fmt: skip
    io_ = scripted(models="api", mode="supervised", dashboard="later", secrets={"MODEL_API_KEY": FAKE_KEY})
    assert run(Workspace(repo), opts, out, io=io_, probe=probe) == 0
    assert calls == [] and "Skipped" in buf.getvalue()
    assert mandate_of(repo).models.profile == "frontier"

    out, buf = console()
    opts.probe = True
    assert run(Workspace(repo), opts, out, io=io_, probe=probe) == 0
    assert calls == [str(repo)] and "Inference works" in buf.getvalue()


def test_dry_run_writes_nothing_and_resume_keeps_answers(repo: Path) -> None:
    out, buf = console()
    ws = Workspace(repo)
    opts = Options(non_interactive=True, yes=False, models="api", mode="supervised", budget=7.0, dashboard="later")
    assert run(ws, opts, out, io=scripted(models="api", mode="supervised", dashboard="later")) == 3
    assert "+    profile: frontier" in buf.getvalue() and "Nothing written" in buf.getvalue()
    raw = yaml.safe_load(ws.mandate_path.read_text())
    assert "models" not in raw["mandate"] and raw["mandate"]["business_constraints"]["maximum_monthly_spend_usd"] == 10
    assert events(repo, EventType.MANDATE_CHANGED) == []
    answers = load_answers(ws)
    assert answers.models == "api" and answers.budget_usd == 7.0 and "budget" in answers.completed


def test_interrupted_setup_keeps_the_answers_so_far(repo: Path) -> None:
    out, _ = console()
    ws = Workspace(repo)

    class Quits(Scripted):
        def choice(self, key: str, prompt: str, choices: Sequence[str], default: str | None) -> str:
            if key == "mode":
                raise SetupError("interrupted")
            return super().choice(key, prompt, choices, default)

    opts = Options(non_interactive=True, yes=True, models="mixed", budget=2.0, dashboard="later")
    assert run(ws, opts, out, io=Quits({"models": "mixed", "dashboard": "later"}, {})) == 2
    answers = load_answers(ws)
    assert answers.models == "mixed" and answers.completed == ["project", "priorities", "models", "credentials"]
    assert "models" not in yaml.safe_load(ws.mandate_path.read_text())["mandate"]

    # the interactive walk resumes at autonomy; the scripted one takes the flags as the whole specification
    opts = Options(non_interactive=True, yes=True, models="mixed", mode="supervised", budget=2.0, dashboard="later")
    assert run(ws, opts, out, io=scripted(models="mixed", mode="supervised", dashboard="later")) == 0
    assert mandate_of(repo).models.profile == "local-first"


def test_scripted_setup_demands_the_choices(repo: Path) -> None:
    out, _ = console()
    opts = Options(non_interactive=True, yes=True, budget=1.0)
    assert run(Workspace(repo), opts, out, io=scripted()) == 2
    assert "models" not in yaml.safe_load(Workspace(repo).mandate_path.read_text())["mandate"]


def test_connections_land_in_the_mandate_with_credentials_in_the_project_env(repo: Path) -> None:
    out, _ = console()
    opts = Options(
        non_interactive=True, yes=True, models="local", mode="supervised", budget=1.0, dashboard="later",
        connections=["id=shop-db,kind=postgres,location=127.0.0.1:5432/shop,username=reader,credential_ref=SHOP_PW"],
        credentials_stdin=["SHOP_PW"],
    )  # fmt: skip
    io_ = scripted(models="local", mode="supervised", dashboard="later", secrets={"SHOP_PW": "reader-secret-123"})
    assert run(Workspace(repo), opts, out, io=io_) == 0
    mandate = mandate_of(repo)
    assert [c.id for c in mandate.connections] == ["shop-db"]
    assert mandate.connections[0].credential_ref == "SHOP_PW" and mandate.connections[0].permissions == ["read"]
    project_env = repo / ".unbidden" / ".env"
    assert machine.read_env(project_env)["SHOP_PW"] == "reader-secret-123"
    assert oct(project_env.stat().st_mode & 0o777) == "0o600"
    assert "reader-secret-123" not in (repo / ".unbidden" / "mandate.yaml").read_text()


def test_cli_without_a_command_runs_setup_then_home(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from unbidden.cli import main

    assert main(["setup", "--non-interactive", "--models", "api", "--mode", "supervised", "--budget", "1",
                 "--dashboard", "later", "--yes", "--json"]) == 0  # fmt: skip
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is True
    assert main(["--json"]) == 0
    home = json.loads(capsys.readouterr().out)
    assert home["profile"] == "frontier" and home["local_inference"] == "deny" and home["next"] == "unbidden scan"
    assert main(["doctor", "--json"]) in (0, 1)
    doctor = json.loads(capsys.readouterr().out)
    by_name = {c["check"]: c for c in doctor["checks"]}
    assert by_name["ollama"]["required"] is False and by_name["meta api"]["required"] is True
    assert "optional" in doctor["requirements"]
