"""The one place a mandate is edited: modes keep their semantics, autonomous keeps its conditions, a bad mandate is
never written, and every change is recorded."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from unbidden.contracts.events import Event, EventType
from unbidden.guardian.mandate_edit import (
    MODEL_OPTIONS,
    MODES,
    apply_autonomy,
    apply_mode,
    apply_model_option,
    autonomous_blockers,
    current_mode,
    read_raw,
    write_mandate,
)
from unbidden.store import Store
from unbidden.workspace import default_mandate

pytestmark = pytest.mark.unit


@pytest.fixture
def mandate_file(tmp_path: Path) -> Path:
    path = tmp_path / "mandate.yaml"
    path.write_text(yaml.safe_dump(default_mandate("shop", "acme/shop"), sort_keys=False))
    return path


def test_modes_are_the_cli_modes_and_never_touch_the_permissions_beyond_them() -> None:
    assert set(MODES) == {"supervised", "autopilot", "autonomous"}
    for fields in MODES.values():
        assert set(fields) == {
            "open_pull_requests",
            "merge_pull_requests",
            "deploy",
            "rollback",
            "use_new_capabilities",
        }
    assert MODES["supervised"]["merge_pull_requests"] == "deny"
    assert MODES["autopilot"]["open_pull_requests"] == "allow" and MODES["autopilot"]["merge_pull_requests"] == "deny"
    assert all(v == "allow" for v in MODES["autonomous"].values())


def test_apply_mode_keeps_act_on_connections_as_it_was(mandate_file: Path) -> None:
    raw = read_raw(mandate_file)
    assert current_mode(raw["mandate"]["autonomy"]) == "supervised"
    raw["mandate"]["autonomy"]["act_on_connections"] = "deny"
    apply_mode(raw, "autopilot")
    assert current_mode(raw["mandate"]["autonomy"]) == "autopilot"
    assert raw["mandate"]["autonomy"]["act_on_connections"] == "deny"
    assert raw["mandate"]["autonomy"]["run_experiments"] == "allow"


def test_autonomous_needs_deploy_steps_and_a_passed_drill(mandate_file: Path) -> None:
    raw = read_raw(mandate_file)
    store = Store(None)
    blockers = autonomous_blockers(raw, store)
    assert len(blockers) == 2 and "deploy_steps" in blockers[0] and "drill" in blockers[1]
    raw["mandate"]["operations"] = {"deploy_steps": ["make deploy"]}
    assert autonomous_blockers(raw, store) == ["autonomous needs a passed rollback drill first: run `unbidden drill`"]
    store.set_value("rollback_drill", {"passed": False})
    assert len(autonomous_blockers(raw, store)) == 1
    store.set_value("rollback_drill", {"passed": True})
    assert autonomous_blockers(raw, store) == []


def test_model_options_map_to_the_existing_policy_fields(mandate_file: Path) -> None:
    raw = read_raw(mandate_file)
    _, api = apply_model_option(raw, "api")
    assert api["profile"] == "frontier" and api["local_inference"] == "deny" and api["local_fallback"] == "deny"
    assert api["private_code_to_frontier"] == "deny", "an option never widens what leaves the machine"
    _, mixed = apply_model_option(raw, "mixed")
    assert mixed["profile"] == "local-first" and mixed["local_inference"] == "allow"
    _, local = apply_model_option(raw, "local")
    assert local["profile"] == "local"
    assert set(MODEL_OPTIONS) == {"local", "mixed", "api"}


def test_write_validates_first_and_records_the_change(mandate_file: Path) -> None:
    store = Store(None)
    raw = read_raw(mandate_file)
    before = mandate_file.read_text()
    apply_autonomy(raw, act_on_connections="definitely-not-a-value")
    with pytest.raises(ValidationError):
        write_mandate(mandate_file, raw, store, {"test": True})
    assert mandate_file.read_text() == before, "an invalid mandate is never written"
    assert not list(mandate_file.parent.glob("*.tmp"))
    assert [e for e in store.events() if e.type is EventType.MANDATE_CHANGED] == []

    raw = read_raw(mandate_file)
    applied = apply_mode(raw, "autopilot")
    mandate = write_mandate(mandate_file, raw, store, {"from": "supervised", "to": "autopilot", "autonomy": applied})
    assert mandate.autonomy.open_pull_requests.value == "allow"
    assert "open_pull_requests: allow" in mandate_file.read_text()
    events: list[Event] = [e for e in store.events() if e.type is EventType.MANDATE_CHANGED]
    assert len(events) == 1 and events[0].actor.startswith("person:") and events[0].payload["to"] == "autopilot"
