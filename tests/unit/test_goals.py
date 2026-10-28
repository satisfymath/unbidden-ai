"""Goal pursuit: the model's shortfall is arithmetic only, and a goal's bounds hold across its runs."""

from __future__ import annotations

from typing import Any

import pytest

from unbidden.contracts.action import Action, ActionStatus
from unbidden.contracts.connection import Ability, Connection, ConnectionState, Environment
from unbidden.contracts.guardian import Goal, Mandate
from unbidden.director import goals
from unbidden.director.goals import GoalRun, evaluate
from unbidden.store import Store

pytestmark = pytest.mark.unit


def test_a_shortfall_is_arithmetic_over_fields_and_nothing_else() -> None:
    row = {"units": 30, "on_hand": 12, "reserved": 2, "incoming": 5}
    assert evaluate("units - (on_hand - reserved + incoming)", row) == 15
    for hostile in ("__import__('os').system('x')", "units / 0", "[units]", "units if on_hand else 0", "units ** 9"):
        with pytest.raises(ValueError):
            evaluate(hostile, row)
    with pytest.raises(KeyError):
        evaluate("units - stock", row)


def test_a_goals_bounds_hold_across_its_runs_in_a_window(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    def fake_run(store: Store, mandate: Mandate, action: Action, *_: Any) -> Action:
        sent.append(action.body or {})
        action.status = ActionStatus.VERIFIED
        store.put("actions", action)
        return action

    monkeypatch.setattr(goals, "run_api_action", fake_run)
    goal = Goal(id="g", statement="s", bounds={"environment": "staging", "max_actions": 3, "max_amount_per_action": 50})
    conn = Connection(
        id="http_api:x",
        project="p",
        kind="http_api",
        protocol="http",
        location="x",
        grant="api",
        environment=Environment.STAGING,
        state=ConnectionState.CONNECTED,
        abilities=[Ability(kind="write", operations=["createReorder"], known_by="checked: oracle")],
    )
    integration = type("I", (), {"operations": [type("O", (), {"id": "createReorder"})()], "documented": []})()
    plan = {"key": "sku", "api": {"connection": "api"}}
    act = {"operation": "createReorder", "key_field": "sku", "amount_field": "units"}
    short = [{"sku": f"S{i}", "shortfall": 100 - i} for i in range(6)]
    first = GoalRun(goal="g")
    goals._act(store, mandate, goal, first, short, act, {"api": conn}, {"api": integration}, plan, "2026-10-28")  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    second = GoalRun(goal="g")
    goals._act(store, mandate, goal, second, short, act, {"api": conn}, {"api": integration}, plan, "2026-10-28")  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    assert [b["sku"] for b in sent] == ["S0", "S1", "S2"] and second.actions == []
    assert all(b["units"] == 50 for b in sent)  # capped by the bound


def test_a_missing_write_waits_for_the_person_and_resumes_when_the_grant_widens(store: Store, mandate: Mandate) -> None:
    from unbidden.contracts.capability import CapabilityNeed, NeedStatus
    from unbidden.contracts.guardian import ConnectionGrant
    from unbidden.forge import needs

    mandate.connections = [ConnectionGrant(id="api", kind="http_api", location="x", permissions=["read"])]
    goal = Goal(id="g", statement="s", bounds={"max_actions": 3})
    conn = Connection(
        id="http_api:x", project="p", kind="http_api", protocol="http", location="x", grant="api",
        state=ConnectionState.CONNECTED,
    )  # fmt: skip
    integration: Any = type("I", (), {"operations": [], "documented": [{"id": "createReorder"}]})()
    plan, act = {"key": "sku", "api": {"connection": "api"}}, {"operation": "createReorder"}

    def pursue() -> GoalRun:
        run = GoalRun(goal="g")
        goals._act(
            store,
            mandate,
            goal,
            run,
            [{"sku": "S0", "shortfall": 9}],
            act,
            {"api": conn},
            {"api": integration},
            plan,
            "2026-10-28",
        )  # pyright: ignore[reportPrivateUsage]
        return run

    assert pursue().status == "waiting_extension"
    need = store.list(needs.COLLECTION, CapabilityNeed)[0]
    need.status, need.blocked_on = NeedStatus.BLOCKED, need.condition  # the extension found the grant read-only
    need.notes = [*need.notes, "the grant api does not allow createReorder", "blocked until a person changes it"]
    store.put(needs.COLLECTION, need)
    again = pursue()
    assert "blocked: the grant api does not allow createReorder" in again.notes[-1]
    assert store.list(needs.COLLECTION, CapabilityNeed)[0].status is NeedStatus.BLOCKED
    mandate.connections[0].permissions = ["read", "write:reorders"]  # a person widens the grant
    pursue()
    assert store.list(needs.COLLECTION, CapabilityNeed)[0].status is NeedStatus.OPEN
