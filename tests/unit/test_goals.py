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
    if state == "complete":
        # The API was read whole and does not report b: a stored record it lacks is a discrepancy, not a skipped row.
        assert [r["slug"] for r in rows] == ["a", "b"] and rows[1].get("_absent_from_api") and rows[1]["shown"] == 0
    else:
        assert [r["slug"] for r in rows] == ["a"]  # only what was read is judged
    assert (partial is None) if outcome is None else partial == "why unknown"


def test_keys_a_row_limited_query_did_not_read_are_not_taken_as_zero(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 9 regression on Conduit: the read-only query stopped at its 1,000-row limit, every other key of the API
    was joined as "stored zero", and 19,000 of 20,000 keys were reported short."""
    from unbidden.connect.pages import Completeness, Read

    rows = [{"slug": f"a{i}", "stored": 1} for i in range(1000)]
    monkeypatch.setattr(goals, "query", lambda *a, **k: rows)
    monkeypatch.setattr(goals, "query_all", lambda *a, **k: (rows, False))  # the whole read hit its ceiling too
    api = [{"slug": f"a{i}", "shown": 1} for i in range(1500)]
    monkeypatch.setattr("unbidden.forge.api_client.read_collection",
                        lambda *a, **k: Read(api, Completeness.COMPLETE, "whole", "offset", 15))  # fmt: skip
    integration: Any = type("I", (), {"op": lambda self, op_id: type("O", (), {"id": op_id})()})()
    conns: Any = {"db": type("D", (), {"id": "postgres:x"})(), "api": type("C", (), {"id": "http_api:x"})()}
    plan = {"key": "slug", "sql": {"connection": "db", "query": "q"}, "api": {"connection": "api", "operation": "l"},
            "shortfall": "stored - shown"}  # fmt: skip
    joined, partial = goals._read(store, mandate, plan, conns, {"api": integration}, GoalRun(goal="g"))  # pyright: ignore[reportPrivateUsage]
    assert len(joined) == 1000 and "limit of 1000 rows" in str(partial)  # the 500 unread keys are not "zero"


def test_a_build_that_raises_is_a_failed_attempt_not_a_need_left_building(store: Store, mandate: Mandate) -> None:
    """Stage 9, LNbits: Guardian refused the builder's prompt, the exception escaped, and the need stayed "building"
    while nine questions waited on it."""
    import asyncio

    from unbidden.contracts.capability import NeedStatus
    from unbidden.forge import needs

    need, _ = needs.record(store, "api_client", "http_api:x", "a question needs it")

    async def refusing(n: Any, lines: list[str]) -> Any:
        raise RuntimeError("the prompt contains credential_assignment")

    after = asyncio.run(needs.build(store, mandate, need, lambda kind, source: [source], refusing))
    assert after.status is NeedStatus.FAILED and any("credential_assignment" in n for n in after.notes)


def test_a_uuid_from_the_database_meets_the_same_id_as_text_from_the_api(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 10 on Prefect: psycopg gives a uuid.UUID, JSON a string; 10000 flow runs each side, no key in common."""
    import uuid

    from unbidden.connect.pages import Completeness, Read

    ids = [uuid.uuid4() for _ in range(3)]
    monkeypatch.setattr(goals, "query", lambda *a, **k: [{"id": i, "db_count": 2} for i in ids])
    api = [{"id": str(i), "run_count": 1} for i in ids]
    monkeypatch.setattr("unbidden.forge.api_client.read_collection",
                        lambda *a, **k: Read(api, Completeness.COMPLETE, "whole", "offset", 1))  # fmt: skip
    integration: Any = type("I", (), {"op": lambda self, op_id: type("O", (), {"id": op_id})()})()
    conns: Any = {"db": type("D", (), {"id": "postgres:x"})(), "api": type("C", (), {"id": "http_api:x"})()}
    plan = {"key": "id", "sql": {"connection": "db", "query": "q"}, "api": {"connection": "api", "operation": "l"},
            "shortfall": "db_count - run_count"}  # fmt: skip
    joined, _ = goals._read(store, mandate, plan, conns, {"api": integration}, GoalRun(goal="g"))  # pyright: ignore[reportPrivateUsage]
    assert len(joined) == 3 and all(r["run_count"] == 1 and r["db_count"] == 2 for r in joined)


def test_a_query_that_fills_its_first_page_is_read_whole_by_key_pages_up_to_a_ceiling(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 10, Prefect and rag-api: the goal's 1,000-row read against an API read whole left the join partial.
    A full first page is followed by keyset pages on the plan's key; the ceiling leaves the read partial, and said."""
    from unbidden.connect.pages import Completeness, Read

    rows = [{"id": f"{i:05d}", "stored": 1} for i in range(2500)]
    monkeypatch.setattr(goals, "query", lambda *a, **k: rows[:1000])
    monkeypatch.setattr(goals, "query_all", lambda *a, **k: (rows, True))
    api = [{"id": f"{i:05d}", "shown": 1} for i in range(2500)]
    monkeypatch.setattr("unbidden.forge.api_client.read_collection",
                        lambda *a, **k: Read(api, Completeness.COMPLETE, "whole", "offset", 25))  # fmt: skip
    integration: Any = type("I", (), {"op": lambda self, op_id: type("O", (), {"id": op_id})()})()
    conns: Any = {"db": type("D", (), {"id": "postgres:x"})(), "api": type("C", (), {"id": "http_api:x"})()}
    plan = {"key": "id", "sql": {"connection": "db", "query": "q"}, "api": {"connection": "api", "operation": "l"},
            "shortfall": "stored - shown"}  # fmt: skip
    run = GoalRun(goal="g")
    joined, partial = goals._read(store, mandate, plan, conns, {"api": integration}, run)  # pyright: ignore[reportPrivateUsage]
    assert len(joined) == 2500 and partial is None and run.reads[0]["whole"] is True
    monkeypatch.setattr(goals, "query_all", lambda *a, **k: (rows[:2000], False))  # the ceiling reached
    run = GoalRun(goal="g")
    joined, partial = goals._read(store, mandate, plan, conns, {"api": integration}, run)  # pyright: ignore[reportPrivateUsage]
    assert len(joined) == 2000 and partial is not None and run.reads[0]["completeness"] == "incomplete"


def test_keyset_pages_follow_the_key_and_stop_at_a_short_page_or_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    from unbidden.connect import postgres

    seen: list[str] = []

    def fake_query(conn: Any, mandate: Any, sql: str, params: Any = None, *, limit: int = 200) -> list[dict[str, Any]]:
        seen.append(sql)
        start = int(params["last"]) + 1 if params else 0
        return [{"k": i} for i in range(start, min(start + limit, 2300))]

    monkeypatch.setattr(postgres, "query", fake_query)
    rows, whole = postgres.query_all(None, None, "SELECT k FROM t", "k", page=1000)  # type: ignore[arg-type]
    assert len(rows) == 2300 and whole and len(seen) == 3 and 'ORDER BY "k"' in seen[0] and '"k" > %(last)s' in seen[1]
    rows, whole = postgres.query_all(None, None, "SELECT k FROM t", "k", page=1000, max_rows=1500)  # type: ignore[arg-type]
    assert len(rows) == 1500 and not whole
    with pytest.raises(postgres.QueryRefused):
        postgres.query_all(None, None, "SELECT k FROM t", "k; DROP", page=10)  # type: ignore[arg-type]


def test_a_plan_without_a_declared_comparison_or_with_unlike_quantities_is_inconclusive() -> None:
    """Stage 10, Prefect: a plan compared a count of states per run with the API's run count and reported every
    key short. What is compared is declared before any number is read; two numbers are not enough."""
    from unbidden.director.goals import comparison_problem

    base = {"sql": {"connection": "db", "query": "q"}, "api": {"connection": "api", "operation": "l"}, "key": "id"}
    assert comparison_problem({"needs": ["x"]}) is None  # nothing compared yet
    assert "not declared" in str(comparison_problem(base))
    partial = {**base, "comparison": {"entity": "a flow run", "quantity": "runs", "same_quantity": True}}
    assert "incomplete" in str(comparison_problem(partial))
    unlike = {**base, "comparison": {
        "entity": "a flow run", "quantity": "runs", "sql_measures": "count of states per run",
        "api_measures": "number of executions of the run", "same_quantity": False, "correspondence": "schema",
    }}  # fmt: skip
    assert "do not measure the same quantity" in str(comparison_problem(unlike))
    mixed = {**base, "comparison": {
        "entity": "an order", "quantity": "amount", "sql_measures": "sum of line amounts",
        "api_measures": "count of lines", "same_quantity": True, "correspondence": "handler",
    }}  # fmt: skip
    assert "aggregations differ" in str(comparison_problem(mixed))
    declared = {**base, "comparison": {
        "entity": "an assistant", "quantity": "versions", "sql_measures": "count of assistant_versions rows",
        "api_measures": "count of versions (documented total)", "same_quantity": True,
        "correspondence": "the handler counts assistant_versions",
    }}  # fmt: skip
    assert comparison_problem(declared) is None


def test_an_endpoint_declared_to_need_a_credential_is_probed_once_anonymously_get_only() -> None:
    import httpx

    from unbidden.research.anonymous import answers_without_credential

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path} {request.headers.get('authorization', '-')}")
        return httpx.Response(200 if request.url.path == "/v1/usage" else 401, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert answers_without_credential("http://127.0.0.1:1/", "GET /v1/usage", client=client) == 200
    assert answers_without_credential("http://127.0.0.1:1", "GET /v1/private", client=client) == 401
    assert answers_without_credential("http://127.0.0.1:1", "POST /v1/usage", client=client) is None
    assert answers_without_credential("http://127.0.0.1:1", "GET /v1/items/{id}", client=client) is None
    assert seen == ["GET /v1/usage -", "GET /v1/private -"]  # no credential ever sent


def test_equal_totals_with_differing_records_filters_or_relations_are_discrepancies_not_agreement(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A count that matches never shows the records agree: the comparison is record by record on the declared
    quantity. Three shapes: a value differs; a filter hides one record and adds another (the same total); a
    relation is attributed to another key (the same sum)."""
    from unbidden.connect.pages import Completeness, Read
    from unbidden.director.goals import evaluate

    db = [{"id": "a", "n": 2}, {"id": "b", "n": 3}, {"id": "c", "n": 1}]  # total 6, three keys
    api_value = [{"id": "a", "n": 2}, {"id": "b", "n": 2}, {"id": "c", "n": 2}]  # total 6, b and c differ
    api_filter = [{"id": "a", "n": 2}, {"id": "b", "n": 3}, {"id": "d", "n": 1}]  # total 6, c hidden, d added
    api_relation = [{"id": "a", "n": 3}, {"id": "b", "n": 2}, {"id": "c", "n": 1}]  # total 6, one unit moved
    monkeypatch.setattr(goals, "query", lambda *a, **k: db)
    integration: Any = type("I", (), {"op": lambda self, op_id: type("O", (), {"id": op_id})()})()
    conns: Any = {"db": type("D", (), {"id": "postgres:x"})(), "api": type("C", (), {"id": "http_api:x"})()}
    plan = {"key": "id", "sql": {"connection": "db", "query": "q"}, "api": {"connection": "api", "operation": "l"},
            "shortfall": "n - n_api"}  # fmt: skip
    for api, expected in ((api_value, {"b", "c"}), (api_filter, {"c", "d"}), (api_relation, {"a", "b"})):
        records = [{"id": r["id"], "n_api": r["n"]} for r in api]
        monkeypatch.setattr("unbidden.forge.api_client.read_collection",
                            lambda *a, _r=records, **k: Read(_r, Completeness.COMPLETE, "whole", "offset", 1))  # fmt: skip
        run = GoalRun(goal="g")
        joined, _ = goals._read(store, mandate, plan, conns, {"api": integration}, run)  # pyright: ignore[reportPrivateUsage]
        assert sum(r["n"] for r in db) == sum(r["n"] for r in api)  # the totals agree
        differing = {r["id"] for r in joined if evaluate(plan["shortfall"], r) != 0}
        assert differing == expected, (api, differing)
