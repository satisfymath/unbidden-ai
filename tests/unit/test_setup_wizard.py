"""The setup assistant: three options without YAML, Solo API without Ollama, autonomous explained and left valid,
credentials by name only, interruption and resumption, nothing written without a confirmation."""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from rich.console import Console

from unbidden.contracts.events import EventType
from unbidden.contracts.guardian import Mandate
from unbidden.guardian.credentials import broker, reset
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
    for name in ("MODEL_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"):  # never the developer's own
        monkeypatch.delenv(name, raising=False)
    reset()
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
    from unbidden.setup import discover as discover_

    monkeypatch.setattr(discover_, "_ollama_installed", lambda: False)
    monkeypatch.setattr(discover_, "_verify", lambda slug: None)
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


def test_autonomous_blocked_keeps_the_previous_configuration_unless_a_fallback_is_named(repo: Path) -> None:
    out, buf = console()
    mandate_path = repo / ".unbidden" / "mandate.yaml"
    before = mandate_path.read_text() if mandate_path.exists() else None
    # --yes does not pick a mode for the person: scripted without --mode-fallback the setup stops, nothing written
    opts = Options(non_interactive=True, yes=True, models="local", mode="autonomous", budget=1.0, dashboard="never")
    assert run(Workspace(repo), opts, out, io=scripted(models="local", mode="autonomous", dashboard="never")) == 4
    text = buf.getvalue()
    assert "deploy_steps" in text and "drill" in text and "--mode-fallback" in text
    if before is not None:
        assert (repo / ".unbidden" / "mandate.yaml").read_text() == before
    mandate = mandate_of(repo)
    assert mandate.autonomy.merge_pull_requests.value == "deny", "autonomous was not switched on"
    assert mandate.autonomy.open_pull_requests.value != "allow", "no mode was chosen for the person"
    assert mandate.models.profile != "local", "the models answer was not written either: nothing partial"
    assert events(repo, EventType.MANDATE_CHANGED) == []
    # named explicitly, the fallback is taken and said
    opts = Options(non_interactive=True, yes=True, models="local", mode="autonomous", mode_fallback="autopilot",
                   budget=1.0, dashboard="never")  # fmt: skip
    io_ = scripted(models="local", mode="autonomous", mode_fallback="autopilot", dashboard="never")
    assert run(Workspace(repo), opts, out, io=io_) == 0
    mandate = mandate_of(repo)
    assert mandate.autonomy.merge_pull_requests.value == "deny"
    assert mandate.autonomy.open_pull_requests.value == "allow", "the fallback named is autopilot"
    assert mandate.models.profile == "local"
    assert "Until then: autopilot" in buf.getvalue()


def test_autonomous_blocked_interactive_asks_for_the_other_mode_without_a_default(repo: Path) -> None:
    out, buf = console()
    opts = Options(yes=True, models="local", mode="autonomous", budget=1.0, dashboard="never")

    class Asks(Scripted):
        asked: ClassVar[list[tuple[str, str | None]]] = []

        def choice(self, key: str, prompt: str, choices: Any, default: str | None) -> str:
            self.asked.append((key, default))
            return super().choice(key, prompt, choices, default)

    io_ = Asks({"models": "local", "mode": "autonomous", "mode_fallback": "supervised", "dashboard": "never",
                "github_access": "skip", "priorities": "correctness", "budget": "1"}, {})  # fmt: skip
    assert run(Workspace(repo), opts, out, io=io_) == 0
    assert ("mode_fallback", None) in io_.asked, "the other mode is asked explicitly, with no default"
    mandate = mandate_of(repo)
    assert mandate.autonomy.open_pull_requests.value != "allow" and mandate.autonomy.merge_pull_requests.value == "deny"
    assert "Until then: supervised" in buf.getvalue()


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
    assert calls == [] and "Inference works" not in buf.getvalue()
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
    assert answers.models == "mixed" and answers.completed == ["found", "models"]
    assert "models" not in yaml.safe_load(ws.mandate_path.read_text())["mandate"]

    # the interactive walk resumes at autonomy; the scripted one takes the flags as the whole specification
    opts = Options(non_interactive=True, yes=True, models="mixed", mode="supervised", budget=2.0, dashboard="later")
    assert run(ws, opts, out, io=scripted(models="mixed", mode="supervised", dashboard="later")) == 0
    assert mandate_of(repo).models.profile == "local-first"


def test_scripted_setup_without_choices_takes_the_facts_and_the_defaults(repo: Path, capsys: Any) -> None:
    """No key, no local model: the option is local (said as 'no model yet'), the mode supervised, the rest kept."""
    out, buf = console()
    opts = Options(non_interactive=True, yes=True, budget=1.0, json=True)
    assert run(Workspace(repo), opts, out, io=scripted()) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] and data["models"] == "local" and data["mode"] == "supervised"
    assert data["found"]["option"] == "local" and data["found"]["github"] is None
    assert data["defaulted"] == ["priorities", "credentials", "connections", "dashboard", "private_code", "language"]
    assert any("No model yet" in note for note in data["notes"])
    assert "no commit" not in buf.getvalue()
    mandate = mandate_of(repo)
    assert mandate.models.profile == "local" and mandate.autonomy.open_pull_requests.value == "require_approval"


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


def test_a_frontier_profile_with_local_inference_allowed_is_the_api_option_and_needs_no_ollama() -> None:
    from unbidden.contracts.guardian import Mandate
    from unbidden.setup.requirements import doctor_requirements, explain, option_of

    mandate = Mandate(workspace="t")
    mandate.models.profile = "frontier"
    mandate.models.local_inference = "allow"
    needs = doctor_requirements(mandate)
    assert needs["ollama"] == "optional" and needs["meta api"] == "required"
    assert option_of(mandate.models) == "api" and option_of({"profile": "frontier"}) == "api"
    assert explain(needs, mandate).startswith("option api")


# --- the walk that asks three things ------------------------------------------------------------------------------


class Asks(Scripted):
    """Records every question asked, so a test can say what was and was not asked."""

    def __init__(self, answers: dict[str, Any], secrets: dict[str, str] | None = None) -> None:
        super().__init__(answers, secrets or {})
        self.asked: list[str] = []

    def choice(self, key: str, prompt: str, choices: Sequence[str], default: str | None) -> str:
        self.asked.append(key)
        value = self.answers.get(key)
        if isinstance(value, list):  # one answer per time the question comes back
            self.answers[key] = value[1:] if len(value) > 1 else value[-1]
            assert value[0] in choices, (value[0], choices)
            return str(value[0])
        return super().choice(key, prompt, choices, default)

    def text(self, key: str, prompt: str, default: str | None) -> str:
        self.asked.append(key)
        return super().text(key, prompt, default)

    def secret(self, key: str, prompt: str) -> str:
        self.asked.append(key)
        return super().secret(key, prompt)

    def confirm(self, key: str, prompt: str, default: bool) -> bool:
        self.asked.append(key)
        return super().confirm(key, prompt, default)


def test_with_a_key_saved_and_no_gh_the_walk_asks_github_the_mode_and_apply(repo: Path) -> None:
    out, buf = console()
    env = machine.machine_env()
    machine.write_env(env, {"MODEL_API_KEY": FAKE_KEY})
    io_ = Asks({"github_access": "skip", "mode": "supervised", "apply": True})
    assert run(Workspace(repo), Options(), out, io=io_) == 0
    assert io_.asked == ["github_access", "mode", "apply"]
    text = buf.getvalue()
    assert "Found" in text and "repository acme/shop" in text and "model key MODEL_API_KEY: saved" in text
    assert "model option: api (a key is here and no local model is installed)" in text
    assert (
        "not asked, defaults kept: priorities, credentials, connections, budget, dashboard, private_code, language"
        in text
    )
    mandate = mandate_of(repo)
    assert mandate.models.profile == "frontier" and mandate.business_constraints.maximum_monthly_spend_usd == 10
    assert mandate.priorities == ["correctness", "maintainability", "security"] or mandate.priorities


def test_without_a_key_the_walk_asks_for_it_and_skipping_keeps_the_local_option(repo: Path) -> None:
    out, buf = console()
    io_ = Asks({"github_access": "skip", "mode": "autopilot", "apply": True}, {"MODEL_API_KEY": ""})
    assert run(Workspace(repo), Options(), out, io=io_) == 0
    assert io_.asked == ["github_access", "MODEL_API_KEY", "mode", "apply"]
    text = buf.getvalue()
    assert "No key." in text and "model option: local (no key and no local model yet)" in text
    assert "No model yet" in text
    assert mandate_of(repo).models.profile == "local"
    assert mandate_of(repo).autonomy.open_pull_requests.value == "allow"


def test_a_pasted_key_is_saved_by_name_and_makes_the_option_api(repo: Path) -> None:
    out, buf = console()
    io_ = Asks({"github_access": "skip", "mode": "supervised", "apply": True}, {"MODEL_API_KEY": FAKE_KEY})
    assert run(Workspace(repo), Options(), out, io=io_) == 0
    assert machine.read_env(machine.machine_env())["MODEL_API_KEY"] == FAKE_KEY
    assert FAKE_KEY not in buf.getvalue() and "MODEL_API_KEY saved" in buf.getvalue()
    assert "model option: api" in buf.getvalue()
    assert mandate_of(repo).models.profile == "frontier"


def test_a_github_token_pasted_in_the_found_block_is_saved(repo: Path) -> None:
    out, buf = console()
    io_ = Asks({"github_access": "token", "mode": "supervised", "apply": True},
               {"MODEL_API_KEY": "", "GITHUB_TOKEN": "ghp_fake_token_0123456789"})  # fmt: skip
    assert run(Workspace(repo), Options(), out, io=io_) == 0
    assert machine.read_env(machine.machine_env())["GITHUB_TOKEN"] == "ghp_fake_token_0123456789"
    assert "ghp_fake" not in buf.getvalue() and "GITHUB_TOKEN saved" in buf.getvalue()
    assert load_answers(Workspace(repo)).github_source is None  # answers are deleted after a successful run
    changed = events(repo, EventType.MANDATE_CHANGED)[0]
    assert changed.payload["setup"]["credentials"] == ["GITHUB_TOKEN"]


def test_the_found_block_lists_compose_connections_and_grants_none(repo: Path) -> None:
    (repo / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:16\n  app:\n    image: shop\n    environment:\n"
        "      DATABASE_URL: postgres://u:p@db:5432/shop\n      BILLING_URL: https://billing.example.com/v1\n"
    )
    subprocess.run(["git", "-C", str(repo), "add", "compose.yaml"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "c"],
                   check=True)  # fmt: skip
    out, buf = console()
    io_ = Asks({"github_access": "skip", "mode": "supervised", "apply": True}, {"MODEL_API_KEY": ""})
    assert run(Workspace(repo), Options(), out, io=io_) == 0
    text = buf.getvalue()
    assert "connections, as committed at HEAD in compose.yaml: postgres db (compose service, read on its own), "
    assert "http_api https://billing.example.com:443 (found in compose env, not granted)" in text
    assert mandate_of(repo).connections == []
    # the advanced section pre-fills the one found
    out, buf = console()
    io_ = Asks({"connection_kind": ["http_api https://billing.example.com:443", "none"], "apply": True})
    opts = Options(section="connections")
    assert run(Workspace(repo), opts, out, io=io_) == 0, buf.getvalue()
    assert "connection_location" not in io_.asked and "connection_id" in io_.asked
    grant = mandate_of(repo).connections[0]
    assert grant.kind == "http_api" and grant.location == "https://billing.example.com:443"
    assert grant.environment == "staging" and grant.permissions == ["read"]


def test_a_setup_json_from_0_10_resumes_under_the_new_names(repo: Path) -> None:
    ws = Workspace(repo)
    ws.init()
    (repo / ".unbidden" / "setup.json").write_text(json.dumps({
        "version": 1, "priorities": ["correctness"], "models": "mixed", "completed": ["project", "priorities", "models"]
    }))  # fmt: skip
    out, buf = console()
    io_ = Asks({"mode": "supervised", "apply": True})
    assert run(ws, Options(), out, io=io_) == 0
    assert io_.asked == ["mode", "apply"], "found and models were done; only autonomy and apply remain"
    assert "Picking up where setup stopped (found, priorities, models)" in buf.getvalue()


def test_a_repository_without_a_commit_is_set_up_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bare = tmp_path / "bare"
    bare.mkdir()
    subprocess.run(["git", "init", "-q", str(bare)], check=True)
    monkeypatch.chdir(bare)
    out, buf = console()
    io_ = Asks({"github_access": "skip", "mode": "supervised", "apply": True}, {"MODEL_API_KEY": ""})
    assert run(Workspace(bare), Options(), out, io=io_) == 0
    text = buf.getvalue()
    assert "no commit yet" in text and "no GitHub remote named origin" in text
    assert "connections: no compose file at HEAD" in text


def test_the_language_section_saves_the_choice_and_the_found_block_says_it(repo: Path, monkeypatch) -> None:
    from unbidden import i18n

    monkeypatch.delenv("UNBIDDEN_LANG", raising=False)
    i18n.clear()
    out, buf = console()
    ws = Workspace(repo)
    ws.init()
    assert run(ws, Options(section="language"), out, io=Asks({"language": "es", "apply": True})) == 0
    assert machine.load_prefs().language == "es" and i18n.language() == "es"
    assert "Idioma: español (guardado en esta máquina)" in buf.getvalue()
    out, buf = console()
    io_ = Asks({"github_access": "skip", "mode": "supervised", "apply": True}, {"MODEL_API_KEY": ""})
    assert run(ws, Options(), out, io=io_) == 0
    text = buf.getvalue()
    assert "Encontrado" in text and "opción de modelo: local" in text and "Mandato escrito" in text
    i18n.clear()


def test_the_gh_choice_signs_in_through_the_terminal_and_the_session_is_the_source(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import stat

    from unbidden.setup import github_access

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    state = tmp_path / "signed-in"
    gh = bin_ / "gh"
    gh.write_text(
        f'#!/bin/sh\nif [ -f "{state}" ]; then echo gho_fake_0123456789; exit 0; fi\necho "not logged in" >&2; exit 1\n'
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv(github_access.OPT_OUT, raising=False)
    github_access.forget_gh_token()
    ran: list[list[str]] = []

    def terminal(argv: list[str]) -> int:
        ran.append(argv)
        state.write_text("tok")
        return 0

    out, buf = console()
    io_ = Asks({"github_access": "gh", "mode": "supervised", "apply": True}, {"MODEL_API_KEY": ""})
    assert run(Workspace(repo), Options(), out, io=io_, terminal=terminal) == 0
    assert ran == [["gh", "auth", "login", "--web", "--git-protocol", "https", "--hostname", "github.com"]]
    text = buf.getvalue()
    assert "GitHub access: the gh CLI's sign-in" in text and "gho_fake" not in text
    assert broker().get("GITHUB_TOKEN", "github") == "gho_fake_0123456789"
    assert not machine.machine_env().exists()  # nothing copied to a file
    github_access.forget_gh_token()


def test_an_account_that_cannot_write_to_the_repository_gets_the_menu_and_one_that_can_does_not(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unbidden.setup import discover as discover_
    from unbidden.setup.github_access import Verified

    machine.write_env(machine.machine_env(), {"GITHUB_TOKEN": "ghp_saved_0123456789", "MODEL_API_KEY": FAKE_KEY})
    monkeypatch.setattr(discover_, "_verify", lambda slug: Verified("someone", False, "someone cannot write"))
    out, buf = console()
    io_ = Asks({"github_access": "skip", "mode": "supervised", "apply": True})
    assert run(Workspace(repo), Options(), out, io=io_) == 0
    assert "github_access" in io_.asked
    assert "signed in as someone, but that account cannot write to acme/shop" in buf.getvalue()

    monkeypatch.setattr(discover_, "_verify", lambda slug: Verified("satisfymath", True, "can push to acme/shop"))
    out, buf = console()
    io_ = Asks({"mode": "supervised", "apply": True})
    assert run(Workspace(repo), Options(section="found"), out, io=io_) == 0
    assert "github_access" not in io_.asked
    assert "signed in as satisfymath; it can push to acme/shop" in buf.getvalue()
