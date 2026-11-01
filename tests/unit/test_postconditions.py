"""Block 1.2: an effect is verified by reading it back as documented, never by a success status alone.

Every case runs against Depot (`bench/ecosystem/depot.py`), in-process, through the real executor and oracle."""

from __future__ import annotations

from typing import Any

import pytest

from bench.ecosystem.depot import Depot, document, transport
from unbidden.connect.registry import record
from unbidden.contracts.action import Action, ActionStatus
from unbidden.contracts.connection import Connection, ConnectionState
from unbidden.contracts.guardian import Autonomy, ConnectionGrant, Mandate
from unbidden.forge import api_client
from unbidden.forge.api_client import ApiIntegration, choose, documented, oracle, signature
from unbidden.guardian import credentials
from unbidden.operate import actions
from unbidden.operate.actions import compensate, idempotency_key, run_api_action
from unbidden.store import Store

pytestmark = pytest.mark.unit
KEY = "depot-key-" + "x" * 12
REAL_CALL = api_client.call


@pytest.fixture(autouse=True)
def held() -> Any:
    fresh = credentials.reset()
    fresh._values["DEPOT_KEY"] = KEY  # pyright: ignore[reportPrivateUsage]
    fresh.grant("DEPOT_KEY", "connection:depot")
    yield
    credentials.reset()


def built(mandate: Mandate, store: Store, depot: Depot) -> tuple[ApiIntegration, Connection, dict[str, Any]]:
    mandate.connections = [
        ConnectionGrant(
            id="depot",
            kind="http_api",
            location="http://depot.test",
            docs="x",
            credential_ref="DEPOT_KEY",
            permissions=["read", "write:restocks"],
        )
    ]
    mandate.autonomy.act_on_connections = Autonomy.ALLOW
    answer = {
        "operations": [
            {"id": "listBins", "use": "read", "why": "x"},
            {"id": "requestRestock", "use": "write", "why": "x"},
        ]
    }
    ops, _ = choose(answer, documented(document()), mandate.connections[0])
    integration = ApiIntegration(
        source="http_api:http://depot.test",
        title="Depot",
        api_version="1.4.0",
        document_url="x",
        document_sha256="x",
        signature=signature(document(), ops),
        auth={"type": "apiKey", "in": "header", "name": "X-Depot-Key"},
        operations=ops,
    )
    conn = Connection(
        id="http_api:http://depot.test",
        project="p",
        kind="http_api",
        protocol="http",
        location="http://depot.test",
        grant="depot",
        state=ConnectionState.CONNECTED,
    )
    record(store, conn, reason="test")
    verdict = oracle(integration, conn, mandate, store=store, transport=transport(depot))
    integration.quality = verdict
    conn.abilities = api_client.abilities(integration, verdict)
    return integration, conn, verdict


def test_the_oracle_learns_the_documented_effect_and_its_undo(mandate: Mandate, store: Store) -> None:
    integration, _, verdict = built(mandate, store, Depot({KEY}))
    assert verdict["passed"], verdict
    assert integration.op("requestRestock").observed_effect == {
        "field": "incoming",
        "amount_from": "units",
        "match": ["bin"],
        "observed": "incoming +1 on the record matched by ['bin']",
    }


@pytest.mark.parametrize(
    ("fault", "what"),
    [
        ("no_effect", "changed nothing"),  # a success status with nothing applied
        ("wrong_field", "documented: False"),  # a field the documentation does not describe
        ("undo_noop", "restored: False"),  # an undo that answers 200 and reverts nothing
        ("duplicate_on_repeat", "repeat applied again: True"),  # the same id returned, the effect applied twice
    ],
)
def test_the_oracle_does_not_enable_a_write_it_could_not_see_work(
    fault: str, what: str, mandate: Mandate, store: Store
) -> None:
    integration, conn, verdict = built(mandate, store, Depot({KEY}, {fault}))
    assert not verdict["operations"]["requestRestock"]["passed"]
    assert what in verdict["operations"]["requestRestock"]["observed"]
    assert integration.op("requestRestock").observed_effect is None and not conn.can("write", "requestRestock")


def act(
    store: Store,
    mandate: Mandate,
    integration: ApiIntegration,
    conn: Connection,
    depot: Depot,
    monkeypatch: pytest.MonkeyPatch,
    units: int = 5,
) -> Action:
    monkeypatch.setattr(actions, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": transport(depot)}))
    monkeypatch.setattr(api_client, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": transport(depot)}))
    body = {"bin": "B03", "units": units}
    action = Action(
        kind="api_call",
        goal="g",
        connection=conn.id,
        environment="staging",
        operation="requestRestock",
        body=body,
        requires="connection.write",
        idempotency_key=idempotency_key("g", conn.id, "requestRestock", body, "today"),
    )
    return run_api_action(store, mandate, action, integration, conn, [])


def test_an_action_is_verified_by_its_documented_effect_and_undone_by_reading_back(
    mandate: Mandate, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    depot = Depot({KEY})
    integration, conn, _ = built(mandate, store, depot)
    done = act(store, mandate, integration, conn, depot, monkeypatch)
    assert done.status is ActionStatus.VERIFIED and "incoming 0 → 5" in done.reason
    assert act(store, mandate, integration, conn, depot, monkeypatch).id == done.id  # the same intent: not resent
    assert depot.bins["B03"]["incoming"] == 5
    undone = compensate(store, mandate, done, integration, conn)
    assert undone.status is ActionStatus.COMPENSATED and depot.bins["B03"]["incoming"] == 0


@pytest.mark.parametrize(
    ("fault", "status", "why"),
    [
        ("no_effect", ActionStatus.UNVERIFIED, "no change"),
        ("wrong_field", ActionStatus.UNVERIFIED, "reserved"),
    ],
)
def test_a_service_that_misbehaves_after_validation_is_never_verified(
    fault: str, status: ActionStatus, why: str, mandate: Mandate, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    depot = Depot({KEY})
    integration, conn, _ = built(mandate, store, depot)  # validated on a healthy service...
    depot.faults = {fault}  # ...which then goes wrong
    done = act(store, mandate, integration, conn, depot, monkeypatch)
    assert done.status is status and why in done.reason


def test_an_undo_that_answers_success_without_reverting_is_not_compensated(
    mandate: Mandate, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    depot = Depot({KEY})
    integration, conn, _ = built(mandate, store, depot)
    done = act(store, mandate, integration, conn, depot, monkeypatch)
    depot.faults = {"undo_noop"}
    undone = compensate(store, mandate, done, integration, conn)
    assert undone.status is ActionStatus.VERIFIED and "not restored" in undone.reason


def test_a_timeout_after_a_write_is_reconciled_by_reading_and_never_duplicated(
    mandate: Mandate, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    depot = Depot({KEY})
    integration, conn, _ = built(mandate, store, depot)
    depot.faults, depot.timed_out_once = {"timeout_after_write"}, False
    done = act(store, mandate, integration, conn, depot, monkeypatch, units=7)
    assert done.status is ActionStatus.VERIFIED and depot.bins["B03"]["incoming"] == 7  # applied once, not twice
    assert any("answer was lost" in str(e) for e in done.evidence)


def test_under_require_approval_a_persons_approval_lets_the_write_and_its_undo_through(
    mandate: Mandate, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unbidden.connect.effects import approve_writes

    depot = Depot({KEY})
    integration, conn, _ = built(mandate, store, depot)
    mandate.autonomy.act_on_connections = Autonomy.REQUIRE_APPROVAL
    refused = act(store, mandate, integration, conn, depot, monkeypatch)
    assert refused.status is ActionStatus.REFUSED and "approve-writes" in refused.reason
    assert depot.bins["B03"]["incoming"] == 0
    assert all(r["state"] == "cancelled" for r in depot.restocks.values())  # only the oracle's probes, each undone
    store.delete("actions", refused.id)
    approve_writes(store, mandate, "depot", by="a person", hours=1)
    done = act(store, mandate, integration, conn, depot, monkeypatch)
    assert done.status is ActionStatus.VERIFIED and depot.bins["B03"]["incoming"] == 5
    undone = compensate(store, mandate, done, integration, conn)
    assert undone.status is ActionStatus.COMPENSATED and depot.bins["B03"]["incoming"] == 0
