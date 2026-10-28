"""C2: a need noticed in the cycle is built, judged, admitted and used, and what waited for it runs, with no CLI."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.unit.test_forge_build import Brain
from unbidden.contracts.capability import CapabilityNeed, NeedStatus
from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.forge import needs
from unbidden.forge.build import Forge
from unbidden.observe.logs import LogWatcher
from unbidden.store import Store

pytestmark = pytest.mark.unit

STATUSES = ["200", "201", "404", "500", "302"]
ACCESS = [
    f'172.18.0.{i % 9} - - "{("GET", "POST")[i % 2]} /items/{i} HTTP/1.1" {STATUSES[i % 5]}' for i in range(1, 120)
]
RESUME = {"type": "research.investigate", "key": "opp_1", "payload": {"id": "opp_1"}}


def read(_: str, __: str) -> list[str]:
    return ACCESS


async def real_forge(need: CapabilityNeed, lines: list[str], store: Store) -> tuple[str | None, str, list[str]]:
    result = await Forge(Brain(), store).build_log_adapter(need.source, lines)  # type: ignore[arg-type]
    return (result.adapter.id if result.adapter else None), "built", result.notes


def build(store: Store, mandate: Mandate, need: CapabilityNeed) -> CapabilityNeed:
    return asyncio.run(needs.build(store, mandate, need, read, lambda n, ls: real_forge(n, ls, store)))


def queued(store: Store) -> list[str]:
    return [j.type for j in store.jobs() if j.type == "research.investigate"]


def test_a_need_is_recorded_once_and_collects_what_waits_for_it(store: Store) -> None:
    first, buildable = needs.record(store, "log_adapter", "compose:api", "unparsed", resume=[RESUME])
    again, _ = needs.record(store, "log_adapter", "compose:api", "unparsed", resume=[RESUME])
    assert buildable and first.id == again.id and again.resume == [RESUME]
    assert len(store.list(needs.COLLECTION, CapabilityNeed)) == 1


def test_built_validated_awaits_approval_then_resumes_what_waited(store: Store, mandate: Mandate) -> None:
    need, _ = needs.record(store, "log_adapter", "compose:api", "unparsed", resume=[RESUME])
    need = build(store, mandate, need)  # use_new_capabilities is deny by default
    assert need.status is NeedStatus.AWAITING_APPROVAL and need.capability_id
    assert queued(store) == []
    from unbidden.forge.adapter import LogAdapter

    adapter = store.get("capabilities", need.capability_id, LogAdapter)
    assert adapter is not None
    adapter.status = "approved"  # what `unbidden forge approve` does, then it calls needs.approved
    store.put("capabilities", adapter)
    (filled,) = needs.approved(store, adapter.id)
    assert filled.status is NeedStatus.IN_USE and queued(store) == ["research.investigate"]


def test_when_the_mandate_allows_its_use_the_need_is_filled_without_a_person(store: Store, mandate: Mandate) -> None:
    mandate.autonomy.use_new_capabilities = Autonomy.ALLOW
    need, _ = needs.record(store, "log_adapter", "compose:api", "unparsed", resume=[RESUME])
    assert build(store, mandate, need).status is NeedStatus.IN_USE
    assert queued(store) == ["research.investigate"]


def test_failed_builds_are_retried_then_abandoned(store: Store, mandate: Mandate) -> None:
    async def fails(*_: Any) -> tuple[str | None, str, list[str]]:
        return None, "failed", ["the oracle refused it"]

    need, _ = needs.record(store, "stats_reader", "http://127.0.0.1:1/stats", "unknown format")
    need = asyncio.run(needs.build(store, mandate, need, read, fails))
    assert need.status is NeedStatus.FAILED
    assert needs.record(store, "stats_reader", "http://127.0.0.1:1/stats", "unknown format")[1]  # one more try
    need = asyncio.run(needs.build(store, mandate, need, read, fails))
    assert need.status is NeedStatus.ABANDONED
    assert not needs.record(store, "stats_reader", "http://127.0.0.1:1/stats", "unknown format")[1]


def test_building_needs_the_mandates_experiments(store: Store, mandate: Mandate) -> None:
    mandate.autonomy.run_experiments = Autonomy.DENY
    need, _ = needs.record(store, "log_adapter", "compose:api", "unparsed")
    need = build(store, mandate, need)
    assert need.status is NeedStatus.OPEN and need.attempts == 0 and "not built" in need.notes[-1]


def test_a_service_writing_an_unparsed_access_log_is_a_need(store: Store) -> None:
    watcher = LogWatcher(store, world=None)
    watcher._access_need("api", ACCESS[:10])  # pyright: ignore[reportPrivateUsage]
    assert store.list(needs.COLLECTION, CapabilityNeed) == []  # too few lines to say
    watcher._access_need("api", ACCESS)  # pyright: ignore[reportPrivateUsage]
    (need,) = store.list(needs.COLLECTION, CapabilityNeed)
    assert need.kind == "log_adapter" and need.source == "compose:api"


def test_the_cycle_queues_and_builds_needs_on_its_own(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from types import SimpleNamespace

    from unbidden.daemon.cycle import Cycle
    from unbidden.forge import build as forge_build

    monkeypatch.setattr(forge_build, "compose_logs", lambda *_, **__: ACCESS)
    mandate.autonomy.use_new_capabilities = Autonomy.ALLOW
    runtime = SimpleNamespace(
        store=store, brain=Brain(), bridge=lambda: object(),  # a bridge exists: still not used
        workspace=SimpleNamespace(repo=tmp_path, mandate=lambda: mandate),
    )  # fmt: skip
    cycle = Cycle(runtime, log=lambda _: None)  # type: ignore[arg-type]
    needs.record(store, "log_adapter", "compose:api", "unparsed", resume=[RESUME])
    cycle._queue_needs()  # pyright: ignore[reportPrivateUsage]
    (queued_build,) = [j for j in store.jobs() if j.type == "forge.build"]
    asyncio.run(cycle.forge_build(queued_build))
    (need,) = store.list(needs.COLLECTION, CapabilityNeed)
    assert need.status is NeedStatus.IN_USE and queued(store) == ["research.investigate"]
