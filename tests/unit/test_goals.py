"""Goal pursuit: the model's shortfall is arithmetic only, and a goal's bounds hold across its runs."""

from __future__ import annotations

from typing import Any

import pytest

from unbidden.contracts.action import Action, ActionStatus
from unbidden.contracts.common import utc_now
from unbidden.contracts.connection import Ability, Connection, ConnectionState, Environment
from unbidden.contracts.guardian import Goal, Mandate
from unbidden.director import goals
from unbidden.director.goals import GoalRun, evaluate
from unbidden.store import Store

pytestmark = pytest.mark.unit
# The window a goal's bounds count in is the UTC day its actions are dated by; a fixed date made this test fail
# after midnight UTC (found on 2026-10-29 from a clean checkout of 94765da).
TODAY = f"{utc_now():%Y-%m-%d}"


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
    goals._act(store, mandate, goal, first, short, act, {"api": conn}, {"api": integration}, plan, TODAY)  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    second = GoalRun(goal="g")
    goals._act(store, mandate, goal, second, short, act, {"api": conn}, {"api": integration}, plan, TODAY)  # pyright: ignore[reportPrivateUsage, reportArgumentType]
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
            TODAY,
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


@pytest.mark.parametrize(
    ("state", "outcome"),
    [("complete", None), ("unknown", "partial"), ("incomplete", "raises")],
)
def test_only_a_read_known_to_be_partial_blocks_everything(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch, state: str, outcome: str | None
) -> None:
    """Stage 9: an API listing whose completeness is unknown (a count that is not a total, as Conduit's) no longer
    blocks every conclusion: the records read are real; only claims about the whole set are withheld."""
    from unbidden.connect.pages import Completeness, Read

    monkeypatch.setattr(goals, "query", lambda *a, **k: [{"slug": "a", "stored": 2}, {"slug": "b", "stored": 1}])
    read = Read([{"slug": "a", "shown": 1}], Completeness(state), f"why {state}", "offset", 3)
    monkeypatch.setattr("unbidden.forge.api_client.read_collection", lambda *a, **k: read)
    integration: Any = type("I", (), {"op": lambda self, op_id: type("O", (), {"id": op_id})()})()
    conns: Any = {"db": type("D", (), {"id": "postgres:x"})(), "api": type("C", (), {"id": "http_api:x"})()}
    plan = {"key": "slug", "sql": {"connection": "db", "query": "q"}, "api": {"connection": "api", "operation": "l"},
            "shortfall": "stored - shown"}  # fmt: skip
    run = GoalRun(goal="g")
    if outcome == "raises":
        with pytest.raises(goals.Incomplete):
            goals._read(store, mandate, plan, conns, {"api": integration}, run)  # pyright: ignore[reportPrivateUsage]
        return
    rows, partial = goals._read(store, mandate, plan, conns, {"api": integration}, run)  # pyright: ignore[reportPrivateUsage]
    assert [r["slug"] for r in rows] == ["a"]  # only what was read is judged
    assert (partial is None) if outcome is None else partial == "why unknown"
