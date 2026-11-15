"""Plugins: an installed package adds connectors, ask kinds and skills; it never replaces a shipped name, never
widens what the mandate grants, and one that fails is left out while the agent goes on.

The fake plugin is a real distribution on `sys.path` (a module and a `.dist-info/entry_points.txt`), so the
discovery under test is `importlib.metadata`'s, not a stand-in for it."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from unbidden import plugins
from unbidden.connect.base import Unavailable, require
from unbidden.connect.kinds import connectors
from unbidden.connect.registry import survey
from unbidden.contracts.ask import Ask, AskOption
from unbidden.contracts.connection import ConnectionState
from unbidden.contracts.guardian import ConnectionGrant, Mandate
from unbidden.director import asks
from unbidden.store import Store

pytestmark = pytest.mark.unit

MODULE = """
from unbidden.connect.base import CheckResult
from unbidden.contracts.connection import Ability, ConnectionState
from unbidden.plugins import SkillCard


class Mqtt:
    kind = "mqtt"
    protocol = "mqtt"

    def validate(self, grant):
        return [] if ":" in grant.location else ["location must be host:port"]

    def check(self, grant):
        # What the broker let this credential do: more than the grant asks, on purpose.
        return CheckResult(
            state=ConnectionState.CONNECTED,
            detail="subscribed to mine/#",
            effective=["read", "write"],
            abilities=[
                Ability(kind="read", operations=["mine/#"], known_by="checked: subscribe"),
                Ability(kind="write", operations=["mine/#"], known_by="checked: publish"),
            ],
        )


class Postgres(Mqtt):  # tries to take a shipped kind
    kind = "postgres"


class Meeting:
    kind = "meeting"

    def apply(self, ws, store, ask, option, value, who):
        if option == "schedule" and not value:
            raise ValueError("a meeting needs a date")
        return f"meeting {option}: {value}"


class PillarFos:
    name = "pillar_fos"
    card = SkillCard(
        purpose="factor of safety of a pillar under its load",
        inputs={"ucs_mpa": "intact strength, MPa", "stress_mpa": "pillar stress, MPa"},
        outputs={"fos": "strength over stress"},
        permissions=("sandbox.run",),
        limits={"timeout_s": 60.0},
        evidence_level=3,
    )

    def run(self, inputs):
        return {"fos": inputs["ucs_mpa"] / inputs["stress_mpa"]}


class NotASkill:
    name = "half"


def broken():
    raise RuntimeError("no broker library")
"""

ENTRY_POINTS = """[unbidden.connectors]
mqtt = fake_mine_plugin:Mqtt
postgres = fake_mine_plugin:Postgres
opcua = fake_mine_plugin:missing

[unbidden.ask_kinds]
meeting = fake_mine_plugin:Meeting

[unbidden.skills]
pillar_fos = fake_mine_plugin:PillarFos
half = fake_mine_plugin:NotASkill
"""


def _install(root: Path, entry_points: str = ENTRY_POINTS) -> None:
    (root / "fake_mine_plugin.py").write_text(MODULE)
    info = root / "fake_mine_plugin-0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: fake-mine-plugin\nVersion: 0.1\n")
    (info / "entry_points.txt").write_text(entry_points)


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "site"
    root.mkdir()
    _install(root)
    monkeypatch.syspath_prepend(str(root))
    plugins.reload()
    yield root
    sys.modules.pop("fake_mine_plugin", None)
    plugins.reload()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_with_nothing_installed_only_the_shipped_names_exist() -> None:
    plugins.reload()
    assert set(connectors()) == {"github", "http_api", "postgres"}
    assert plugins.known_ask_kinds() == plugins.NATIVE_ASK_KINDS
    assert plugins.skills() == {}
    assert plugins.problems() == []


def test_a_plugin_adds_a_connector_and_cannot_take_a_shipped_kind(installed: Path) -> None:
    from unbidden.connect.postgres import PostgresConnector

    found = connectors()
    assert set(found) == {"github", "http_api", "postgres", "mqtt"}
    assert isinstance(found["postgres"], PostgresConnector)  # the shipped one, not the plugin's
    reasons = {(p.group, p.name): p.why for p in plugins.problems()}
    assert "Unbidden ships" in reasons[(plugins.CONNECTORS, "postgres")]


def test_a_plugin_that_fails_or_is_not_what_its_group_expects_is_left_out_and_said(installed: Path) -> None:
    reasons = {(p.group, p.name): p.why for p in plugins.problems()}
    assert "failed to load" in reasons[(plugins.CONNECTORS, "opcua")]
    assert "not a skill" in reasons[(plugins.SKILLS, "half")]
    assert all(p.source == "fake-mine-plugin 0.1" for p in plugins.problems())
    assert set(plugins.skills()) == {"pillar_fos"}  # the good ones still load


def test_a_plugins_connection_is_checked_and_gated_like_a_shipped_one(
    installed: Path, repo: Path, store: Store, mandate: Mandate
) -> None:
    mandate.connections = [ConnectionGrant(id="broker", kind="mqtt", location="127.0.0.1:1883", permissions=["read"])]
    (conn,) = [c for c in survey(repo, store, mandate, None, connectors()) if c.grant]
    assert conn.state is ConnectionState.CONNECTED and conn.protocol == "mqtt"
    assert require(conn, mandate, "read", None, "read sensors") is conn
    # The broker would let it publish; the mandate grants read, so the gate refuses the write.
    with pytest.raises(Unavailable, match="grants"):
        require(conn, mandate, "write", "mine/#", "publish a setpoint")
    conn.state = ConnectionState.REVOKED
    with pytest.raises(Unavailable, match="revoked"):
        require(conn, mandate, "read", None, "read sensors")


def test_a_plugins_connector_validates_the_grant_before_anything_is_reached(
    installed: Path, repo: Path, store: Store, mandate: Mandate
) -> None:
    mandate.connections = [ConnectionGrant(id="broker", kind="mqtt", location="nowhere")]
    (conn,) = [c for c in survey(repo, store, mandate, None, connectors()) if c.grant]
    assert conn.state is ConnectionState.NEEDS_CONFIGURATION and "host:port" in (conn.blocked or "")


def test_a_grant_for_a_kind_nobody_connects_is_reported_and_never_used(
    repo: Path, store: Store, mandate: Mandate
) -> None:
    plugins.reload()
    mandate.connections = [ConnectionGrant(id="broker", kind="mqtt", location="127.0.0.1:1883")]
    (conn,) = [c for c in survey(repo, store, mandate, None, connectors()) if c.grant]
    assert conn.state is ConnectionState.NEEDS_CAPABILITY and "no connector for mqtt" in (conn.blocked or "")
    with pytest.raises(Unavailable):
        require(conn, mandate, "read", None, "read sensors")
    with pytest.raises(ValueError):
        ConnectionGrant(id="x", kind="Not A Kind", location="h:1")


def _meeting() -> Ask:
    return Ask(
        kind="meeting",
        title="Meet geotechnics about pillar B3",
        why="its factor of safety is 1.2, under the 1.4 the mine asks",
        options=[
            AskOption(key="schedule", label="schedule: type the date", input="text"),
            AskOption(key="later", label="later"),
        ],
        dedup_key="meeting:pillar:B3",
    )


def test_an_ask_of_an_unknown_kind_is_not_opened(store: Store) -> None:
    plugins.reload()
    with pytest.raises(asks.AskError, match="no ask kind 'meeting'"):
        asks.open_ask(store, _meeting())
    assert asks.open_asks(store) == []


def test_a_plugins_ask_is_opened_and_its_answer_applies_the_plugins_effect(installed: Path, store: Store) -> None:
    ask = asks.open_ask(store, _meeting())
    with pytest.raises(asks.AskError, match="needs a date"):  # the plugin's ValueError, as an answer refused
        asks.answer(None, store, ask.id, "schedule", by="ana")
    assert asks.open_asks(store) != []
    done = asks.answer(None, store, ask.id, "schedule", value="2026-12-01", by="ana")
    assert done.status == "answered" and done.outcome == "meeting schedule: 2026-12-01"


def test_an_ask_outlives_its_plugin_and_says_what_is_missing(
    installed: Path, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    ask = asks.open_ask(store, _meeting())
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(installed)])
    plugins.reload()
    (kept,) = asks.open_asks(store)  # still readable
    assert kept.id == ask.id
    with pytest.raises(asks.AskError, match="not installed"):
        asks.answer(None, store, ask.id, "schedule", value="2026-12-01", by="ana")
    assert asks.answer(None, store, ask.id, "later", by="ana").outcome == "nothing changed"


def test_a_skill_shows_its_card_and_runs(installed: Path) -> None:
    skill = plugins.skills()["pillar_fos"]
    assert skill.card.permissions == ("sandbox.run",) and skill.card.evidence_level == 3
    assert skill.run({"ucs_mpa": 100.0, "stress_mpa": 50.0}) == {"fos": 2.0}


def test_the_plugins_command_lists_what_loaded_and_what_was_left_out(
    installed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from unbidden.cli import main

    assert main(["plugins", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {(p["group"], p["name"]) for p in data["plugins"]} == {
        (plugins.CONNECTORS, "mqtt"),
        (plugins.ASK_KINDS, "meeting"),
        (plugins.SKILLS, "pillar_fos"),
    }
    assert {b["name"] for b in data["problems"]} == {"postgres", "opcua", "half"}
    assert data["skills"]["pillar_fos"]["inputs"]["ucs_mpa"] == "intact strength, MPa"
