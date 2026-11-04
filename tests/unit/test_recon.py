"""Reconnaissance: the stack started when down (with a yes), the map read, the database read inside its container,
GitHub written as a connection, the deploy procedure adopted, the drill run, the record kept; `start` warns when it
never ran and refuses an autonomous start on an incomplete one."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import Relation, Resource, WorldModel
from unbidden.guardian.credentials import reset
from unbidden.setup import recon
from unbidden.setup.github_access import Verified
from unbidden.setup.wizard import Options, Scripted, run
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit

COMPOSE = (
    "name: shop\n"
    "services:\n"
    "  db:\n    image: postgres:17-alpine\n    ports: ['5433:5432']\n    environment:\n      POSTGRES_DB: shop\n"
    "  app:\n    image: shop\n    ports: ['8000:8000']\n    environment:\n"
    "      DATABASE_URL: postgresql://u:p@db:5432/shop\n"
)
DEPLOY = (
    "name: Deploy\non: {push: {branches: [main]}}\njobs:\n  d:\n    steps:\n"
    "      - run: docker compose up -d --build --wait\n"
)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("MODEL_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    reset()
    repo = tmp_path / "shop"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "compose.yaml").write_text(COMPOSE)
    (repo / ".github" / "workflows" / "deploy.yml").write_text(DEPLOY)
    (repo / "requirements.txt").write_text("flask\n")
    git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)
    (repo / "README.md").write_text("two\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "two"], check=True)
    monkeypatch.chdir(repo)
    import unbidden.runtime as runtime
    from unbidden.brain import hardware
    from unbidden.setup import discover as discover_

    monkeypatch.setattr(runtime, "installed_models", lambda url: set())
    monkeypatch.setattr(discover_, "_ollama_installed", lambda: False)
    monkeypatch.setattr(hardware, "detect", lambda: hardware.Machine(total_gb=16.0, apple_silicon=True, chip="t",
                                                                      gpu_gb=0.0))  # fmt: skip
    return repo


def _world() -> WorldModel:
    world = WorldModel(rev="HEAD")
    ev = [EvidenceRef(kind="config", locator="docker")]
    world.add(Resource(id="service:db", kind="database", name="db", status=EpistemicStatus.OBSERVED, confidence=1.0,
                       evidence=ev))  # fmt: skip
    world.add(Resource(id="table:bill", kind="table", name="bill", status=EpistemicStatus.OBSERVED, confidence=1.0,
                       evidence=ev, source="postgres-readonly"))  # fmt: skip
    world.relate(Relation(src="service:db", dst="table:bill", predicate="defines", status=EpistemicStatus.OBSERVED,
                          confidence=1.0, evidence=ev, source="postgres-readonly"))  # fmt: skip
    world.add(Resource(id="endpoint:GET /healthcheck", kind="endpoint", name="GET /healthcheck",
                       status=EpistemicStatus.OBSERVED, confidence=1.0, evidence=ev,
                       attributes={"port": 8000}))  # fmt: skip
    return world


class Asks(Scripted):
    def __init__(self, answers: dict[str, Any], secrets: dict[str, str] | None = None) -> None:
        super().__init__(answers, secrets or {})
        self.asked: list[str] = []

    def choice(self, key: str, prompt: str, choices: Any, default: str | None) -> str:
        self.asked.append(key)
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


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=200, force_terminal=False, color_system=None), buf


def test_a_running_stack_is_mapped_the_database_read_github_granted_the_procedure_adopted_and_the_drill_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unbidden.setup import discover as discover_

    monkeypatch.setattr(discover_, "_verify", lambda slug: Verified("dave", True, "ok"))
    from unbidden.guardian.credentials import broker

    broker().hold("GITHUB_TOKEN", "ghp_fake_0123456789")
    drills: list[tuple[str, str]] = []

    def driller(ws: Any, mandate: Any, previous: str, url: str) -> dict[str, Any]:
        drills.append((previous[:4], url))
        assert mandate.operations.deploy_steps == [["docker", "compose", "up", "-d", "--build", "--wait"]]
        return {"passed": True, "back": "ok", "forth": "ok"}

    out, buf = _console()
    io_ = Asks({"github_access": "skip", "db_grant": False, "adopt_deploy": True, "run_drill": True,
                "mode": "supervised", "apply": True}, {"MODEL_API_KEY": ""})  # fmt: skip
    code = run(Workspace(repo), Options(), out, io=io_, mapper=lambda ws: _world(), driller=driller,
               containers=lambda r: [{"Name": "shop-db-1"}, {"Name": "shop-app-1"}])  # fmt: skip
    assert code == 0, buf.getvalue()
    text = buf.getvalue()
    assert "The stack runs: 2 container(s)" in text
    assert "db: 1 table(s) read inside its container" in text
    assert "GitHub: dave can push to acme/shop; written as the `github` connection" in text
    assert "Adopted: docker compose up -d --build --wait" in text
    assert "Rollback drill passed" in text and drills and drills[0][1] == "http://127.0.0.1:8000/healthcheck"
    assert "Reconnaissance complete." in text
    assert "start_stack" not in io_.asked and "db_grant" in io_.asked
    ws = Workspace(repo)
    mandate = ws.mandate()
    assert [c.kind for c in mandate.connections] == ["github"] and mandate.connections[0].location == "acme/shop"
    assert mandate.operations.deploy_steps == [["docker", "compose", "up", "-d", "--build", "--wait"]]
    record = recon.status(ws.store())
    assert record is not None and record["complete"] and record["databases"] == {"db": "container"}
    assert record["github"] == "connected" and record["deploy_steps"] == "adopted" and record["drill"] == "passed"
    from unbidden.setup.requirements import start_checks

    verdict = start_checks(ws, docker_timeout_s=0.1)
    assert "recon" not in [c.name for c in verdict.refused + verdict.warnings]


def test_a_down_stack_is_started_with_a_yes_in_the_persons_terminal(repo: Path) -> None:
    ran: list[list[str]] = []
    up: list[dict[str, Any]] = []

    def terminal(argv: list[str]) -> int:
        ran.append(argv)
        up.append({"Name": "shop-db-1"})
        return 0

    out, buf = _console()
    io_ = Asks({"github_access": "skip", "start_stack": True, "db_grant": False, "adopt_deploy": False,
                "mode": "supervised", "apply": True}, {"MODEL_API_KEY": ""})  # fmt: skip
    assert run(Workspace(repo), Options(), out, io=io_, containers=lambda r: list(up), terminal=terminal,
               mapper=lambda ws: _world()) == 0  # fmt: skip
    assert ran == [["docker", "compose", "up", "-d", "--wait"]]
    text = buf.getvalue()
    assert "The stack is up." in text and "Not adopted; deploys stay a person's." in text
    record = recon.status(Workspace(repo).store())
    assert record is not None and record["stack"] == "started" and record["deploy_steps"] == "skipped"
    assert record["drill"] == "not_possible: no deploy steps" and record["complete"]


def test_a_network_grant_is_checked_before_it_is_written_and_a_failed_one_is_not(repo: Path) -> None:
    checked: list[dict[str, Any]] = []

    def checker(grant: dict[str, Any]) -> tuple[str, str]:
        checked.append(grant)
        return (
            ("connected", "has_table_privilege SELECT as unbidden_ro")
            if grant["username"] == "unbidden_ro"
            else ("needs_authorization", "password authentication failed")
        )

    out, buf = _console()
    io_ = Asks({"github_access": "skip", "db_grant": True, "db_username": "unbidden_ro", "adopt_deploy": False,
                "mode": "supervised", "apply": True},
               {"MODEL_API_KEY": "", "DB_RO_PASSWORD": "s3cret-pw-0123"})  # fmt: skip
    assert run(Workspace(repo), Options(), out, io=io_, containers=lambda r: [{"Name": "x"}],
               mapper=lambda ws: _world(), checker=checker) == 0  # fmt: skip
    assert (
        checked and checked[0]["location"] == "127.0.0.1:5433/shop" and checked[0]["credential_ref"] == "DB_RO_PASSWORD"
    )
    text = buf.getvalue()
    assert "Grant db-ro connected" in text and "s3cret" not in text
    ws = Workspace(repo)
    assert [c.id for c in ws.mandate().connections] == ["db-ro"]
    assert (ws.dir / ".env").read_text().strip() == "DB_RO_PASSWORD=s3cret-pw-0123"
    assert recon.status(ws.store())["databases"] == {"db": "granted"}  # type: ignore[index]

    out, buf = _console()
    io_ = Asks({"github_access": "skip", "db_grant": True, "db_username": "wrong", "adopt_deploy": False,
                "mode": "supervised", "apply": True},
               {"MODEL_API_KEY": "", "DB_RO_PASSWORD": "nope-nope-0123"})  # fmt: skip
    assert run(Workspace(repo), Options(section="recon"), out, io=io_, containers=lambda r: [{"Name": "x"}],
               mapper=lambda ws: _world(), checker=checker) == 0  # fmt: skip
    assert "The grant did not connect (needs_authorization" in buf.getvalue()


def test_scripted_recon_records_what_it_could_not_do_and_start_says_so(repo: Path) -> None:
    out, buf = _console()
    opts = Options(non_interactive=True, yes=True, models="local", mode="supervised", budget=1.0, dashboard="never")
    assert (
        run(
            Workspace(repo), opts, out, io=Scripted({"models": "local", "mode": "supervised", "dashboard": "never"}, {})
        )
        == 0
    )
    text = buf.getvalue()
    assert "The stack is down" in text and "Deploy procedure found, not adopted (scripted run)" in text
    assert "Reconnaissance incomplete: stack down" in text
    ws = Workspace(repo)
    record = recon.status(ws.store())
    assert record is not None and not record["complete"] and record["stack"] == "down"
    from unbidden.setup.requirements import start_checks

    verdict = start_checks(ws, docker_timeout_s=0.1)
    warned = [c for c in verdict.warnings if c.name == "recon"]
    assert warned and "incomplete: stack down" in warned[0].detail and warned[0].fix == "unbidden setup recon"


def test_without_a_recon_start_warns_and_doctor_says_never_ran(repo: Path) -> None:
    from unbidden.cli import doctor_checks, main
    from unbidden.setup.requirements import start_checks

    assert main(["init", "--json"]) == 0
    ws = Workspace.find()
    verdict = start_checks(ws, docker_timeout_s=0.1)
    warned = [c for c in verdict.warnings if c.name == "recon"]
    assert warned and warned[0].detail.startswith("never ran")
    checks, _, _ = doctor_checks(ws)
    assert ("recon", False, "never ran: `unbidden setup recon`") in checks


def test_the_in_container_postgres_read_is_a_connection() -> None:
    from unbidden.connect.registry import _from_world  # pyright: ignore[reportPrivateUsage]

    found = {c.id: c for c, _ in _from_world(_world())}
    assert "postgres:container:db" in found and found["postgres:container:db"].state.value == "connected"


def test_a_grant_already_in_the_mandate_counts_in_a_scripted_recon(repo: Path) -> None:
    """Campaign 13, WS1: a scripted setup (`--connection … --credential …`, the campaign harness) left the database
    `unread`, so an autonomous start was refused although the grant connected."""
    out, _ = _console()
    io_ = Asks({"github_access": "skip", "db_grant": True, "db_username": "unbidden_ro", "adopt_deploy": False,
                "mode": "supervised", "apply": True},
               {"MODEL_API_KEY": "", "DB_RO_PASSWORD": "s3cret-pw-0123"})  # fmt: skip
    ok = lambda grant: ("connected", "has_table_privilege SELECT")  # noqa: E731
    assert run(Workspace(repo), Options(), out, io=io_, containers=lambda r: [{"Name": "x"}],
               mapper=lambda ws: _world(), checker=ok) == 0  # fmt: skip

    unread = WorldModel(rev="HEAD")  # the map read no table this time
    out, _ = _console()
    opts = Options(non_interactive=True, yes=True, section="recon")
    assert run(Workspace(repo), opts, out, io=Scripted({}, {}), containers=lambda r: [{"Name": "x"}],
               mapper=lambda ws: unread, checker=ok) == 0  # fmt: skip
    assert recon.status(Workspace(repo).store())["databases"] == {"db": "granted"}  # type: ignore[index]


def test_an_incomplete_recon_refuses_a_deploying_start_only(repo: Path) -> None:
    """Campaign 13: sqlmodel, a library with a compose file for its tests, was refused although its mandate allowed
    merges only; a merge on the team's green CI needs no running stack, a deploy does."""
    import yaml

    from unbidden.setup.requirements import start_checks

    out, _ = _console()
    opts = Options(non_interactive=True, yes=True, models="local", mode="supervised", budget=1.0, dashboard="never")
    scripted = Scripted({"models": "local", "mode": "supervised", "dashboard": "never"}, {})
    assert run(Workspace(repo), opts, out, io=scripted) == 0
    path = repo / ".unbidden" / "mandate.yaml"

    def autonomy(merge: str, deploy: str) -> tuple[bool, bool]:
        raw = yaml.safe_load(path.read_text())
        raw["mandate"].setdefault("autonomy", {}).update({"merge_pull_requests": merge, "deploy": deploy})
        path.write_text(yaml.safe_dump(raw, sort_keys=False))
        verdict = start_checks(Workspace(repo), docker_timeout_s=0.1)
        return (any(c.name == "recon" for c in verdict.refused), any(c.name == "recon" for c in verdict.warnings))

    assert autonomy("allow", "deny") == (False, True)
    assert autonomy("allow", "allow") == (True, False)
