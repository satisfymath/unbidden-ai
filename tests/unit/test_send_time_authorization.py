"""Every mutating request is authorized at the moment it is sent, retries included: a 503 followed by a change of
policy, approval, connection, kill switch or budget sends no further write, from the oracle, an action or an undo.

Reproduction (review of 6bdd2a8): a POST sent under ALLOW, answered 503; the policy turned to DENY; `call`'s own
retry loop sent the POST again without looking."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest

from bench.ecosystem.depot import Depot, transport
from tests.unit.test_postconditions import KEY, REAL_CALL, built
from unbidden.connect.base import Unavailable
from unbidden.connect.effects import approve_writes, attempts_today
from unbidden.connect.registry import get, record
from unbidden.contracts.action import Action, ActionStatus
from unbidden.contracts.connection import Connection, ConnectionState
from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.forge import api_client
from unbidden.forge.api_client import ApiIntegration, CallFailed, call
from unbidden.guardian.approvals import COLLECTION as APPROVALS
from unbidden.guardian.approvals import Approval
from unbidden.guardian.killswitch import KillSwitch
from unbidden.operate import actions
from unbidden.operate.actions import compensate, idempotency_key, run_api_action
from unbidden.store import Store

pytestmark = pytest.mark.unit
STOPS = ["deny", "approval expired", "approval gone", "revoked", "kill switch", "budget"]


@pytest.fixture(autouse=True)
def held() -> Any:
    from unbidden.guardian import credentials

    fresh = credentials.reset()
    fresh._values["DEPOT_KEY"] = KEY  # pyright: ignore[reportPrivateUsage]
    fresh.grant("DEPOT_KEY", "connection:depot")
    yield
    credentials.reset()


def stopper(stop: str, store: Store, mandate: Mandate, conn: Connection) -> Callable[[], None]:
    """What changes between the first attempt and the next."""

    def act() -> None:
        if stop == "deny":
            mandate.autonomy.act_on_connections = Autonomy.DENY
        elif stop.startswith("approval"):
            for approval in store.list(APPROVALS, Approval):
                if stop == "approval gone":
                    store.delete(APPROVALS, approval.id)
                else:
                    approval.expires_at = approval.expires_at - timedelta(days=1)
                    store.put(APPROVALS, approval)
        elif stop == "revoked":
            current = get(store, conn.id)
            assert current is not None
            current.state = ConnectionState.REVOKED
            record(store, current, reason="key revoked")
        elif stop == "kill switch":
            KillSwitch.of(store).engage("stop")  # type: ignore[union-attr]
        elif stop == "budget":
            mandate.connections[0].limits["max_writes_per_day"] = attempts_today(store, conn)

    return act


class Flaky:
    """Depot behind a door: the first mutating request is applied or not, answered 503, and the world changes."""

    def __init__(self, depot: Depot, then: Callable[[], None], *, applied: bool = False) -> None:
        self.depot, self.then, self.applied, self.mutations, self.failed = depot, then, applied, 0, False

    def transport(self) -> httpx.MockTransport:
        inner = transport(self.depot)

        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return inner.handle_request(request)
            self.mutations += 1
            if not self.failed:
                self.failed = True
                if self.applied:
                    inner.handle_request(request)
                self.then()
                return httpx.Response(503, json={"detail": "unavailable"})
            return inner.handle_request(request)

        return httpx.MockTransport(handle)


def setup(store: Store, mandate: Mandate, stop: str) -> tuple[Depot, ApiIntegration, Connection]:
    depot = Depot({KEY})
    integration, conn, _ = built(mandate, store, depot)  # validated under ALLOW
    if stop.startswith("approval"):
        mandate.autonomy.act_on_connections = Autonomy.REQUIRE_APPROVAL
        approve_writes(store, mandate, "depot", by="a person", hours=1)
    return depot, integration, conn


def restock(conn: Connection) -> Action:
    body = {"bin": "B03", "units": 5}
    return Action(
        kind="api_call",
        goal="g",
        connection=conn.id,
        environment="staging",
        operation="requestRestock",
        body=body,
        requires="connection.write",
        idempotency_key=idempotency_key("g", conn.id, "requestRestock", body, "today"),
    )


@pytest.fixture
def disk(tmp_path: Any) -> Store:
    return Store(tmp_path / "state.db")  # the kill switch lives beside the workspace's state


def test_the_reported_case_a_503_then_deny_sends_no_second_post(disk: Store, mandate: Mandate) -> None:
    depot, integration, conn = setup(disk, mandate, "deny")
    door = Flaky(depot, stopper("deny", disk, mandate, conn))
    with pytest.raises((CallFailed, Unavailable)):
        call(integration, conn, mandate, "requestRestock", body={"bin": "B03", "units": 5}, idempotency_key="k",
             transport=door.transport(), store=disk)  # fmt: skip
    assert door.mutations == 1


def test_a_mutating_request_cannot_be_sent_without_its_send_time_authorization(disk: Store, mandate: Mandate) -> None:
    depot, integration, conn = setup(disk, mandate, "deny")
    with pytest.raises(Unavailable, match="authoriz"):
        call(integration, conn, mandate, "requestRestock", body={"bin": "B03", "units": 5}, idempotency_key="k",
             transport=transport(depot), gate=False)  # fmt: skip
    assert depot.bins["B03"]["incoming"] == 0


@pytest.mark.parametrize("stop", STOPS)
@pytest.mark.parametrize("applied", [False, True])
def test_an_action_sends_no_new_write_after_the_condition_changes(
    stop: str, applied: bool, disk: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    depot, integration, conn = setup(disk, mandate, stop)
    door = Flaky(depot, stopper(stop, disk, mandate, conn), applied=applied)
    monkeypatch.setattr(actions, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": door.transport()}))
    monkeypatch.setattr(api_client, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": door.transport()}))
    before = attempts_today(disk, conn)
    done = run_api_action(disk, mandate, restock(conn), integration, conn, [])
    assert door.mutations == 1, "a second write left after the condition changed"
    assert done.status is not ActionStatus.VERIFIED or applied  # reconciled by reading, never resent
    if applied:
        # The 503 hid a write that happened: read back, it is reconciled without sending again.
        assert depot.bins["B03"]["incoming"] == 5 and done.status is ActionStatus.VERIFIED
    assert attempts_today(disk, conn) == before + 1  # the one attempt sent is audited and counted


@pytest.mark.parametrize("stop", STOPS)
def test_the_oracle_sends_no_new_probe_after_the_condition_changes(stop: str, disk: Store, mandate: Mandate) -> None:
    from unbidden.forge.api_client import oracle

    depot, integration, conn = setup(disk, mandate, stop)
    door = Flaky(depot, stopper(stop, disk, mandate, conn))
    oracle(integration, conn, mandate, store=disk, transport=door.transport())
    assert door.mutations == 1


@pytest.mark.parametrize("stop", STOPS)
def test_an_undo_is_not_sent_after_the_condition_changes(
    stop: str, disk: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    depot, integration, conn = setup(disk, mandate, stop)
    monkeypatch.setattr(actions, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": transport(depot)}))
    monkeypatch.setattr(api_client, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": transport(depot)}))
    done = run_api_action(disk, mandate, restock(conn), integration, conn, [])
    assert done.status is ActionStatus.VERIFIED
    door = Flaky(depot, stopper(stop, disk, mandate, conn))
    monkeypatch.setattr(actions, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": door.transport()}))
    monkeypatch.setattr(api_client, "call", lambda *a, **k: REAL_CALL(*a, **{**k, "transport": door.transport()}))
    undone = compensate(disk, mandate, done, integration, conn)
    assert door.mutations == 1 and undone.status is not ActionStatus.COMPENSATED
    again = compensate(disk, mandate, undone, integration, conn)  # a later attempt is authorized again, and refused
    assert door.mutations == 1 and again.status is not ActionStatus.COMPENSATED
