"""PR12: what must be known before an experiment is worth it, each through a mechanism that exists, each bounded."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from unbidden.contracts.capability import CapabilityNeed
from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, Opportunity
from unbidden.daemon.cycle import Cycle
from unbidden.director.decide import MAX_MEASURES, Context, decide
from unbidden.store import Store

pytestmark = pytest.mark.unit


def world_opp(**details: Any) -> Opportunity:
    return Opportunity(
        source="world", category="performance", title="t", summary="s", dedup_key=str(sorted(details)),
        evidence=[EvidenceRef(kind="config", locator="psql")], details={"rev": "a" * 40, **details},
    )  # fmt: skip


def test_an_unobserved_table_size_is_measured_first_and_only_a_few_times(mandate: Mandate) -> None:
    opp = world_opp(check="unindexed_foreign_key", table="orders", rows=None)
    assert decide(opp, mandate, Context(0, 0)).chosen is ActionKind.MEASURE
    opp.details["measure"] = {"rev": "a" * 40, "asked": MAX_MEASURES}
    decision = decide(opp, mandate, Context(0, 0))
    assert decision.chosen is ActionKind.WAIT and "cannot be measured" in decision.reason
    opp.details["rev"] = "b" * 40  # a new commit: measured again
    assert decide(opp, mandate, Context(0, 0)).chosen is ActionKind.MEASURE
    opp.details["rows"] = 50_000  # observed: decided on it
    assert decide(opp, mandate, Context(0, 0)).chosen is ActionKind.RUN_EXPERIMENT


def test_a_missing_reader_is_acquired_and_a_built_one_waits_for_its_approval(mandate: Mandate) -> None:
    opp = world_opp(check="slow_endpoint", service="api", traffic="unknown")
    assert decide(opp, mandate, Context(0, 0, capability_needs={"compose:api": "open"})).chosen is (
        ActionKind.ACQUIRE_CAPABILITY
    )
    awaiting = decide(opp, mandate, Context(0, 0, capability_needs={"compose:api": "awaiting_approval"}))
    assert awaiting.chosen is ActionKind.WAIT and "approval" in awaiting.reason
    # In use, or given up: decided without waiting on it.
    for status in ("in_use", "abandoned", None):
        needs = {"compose:api": status} if status else {}
        assert decide(opp, mandate, Context(0, 0, capability_needs=needs)).chosen is ActionKind.RUN_EXPERIMENT


def test_a_runtime_signal_is_investigated_once(mandate: Mandate) -> None:
    opp = world_opp(incident={"good": "a", "bad": "b", "incident": "5xx", "subject": "api"})
    assert decide(opp, mandate, Context(0, 0)).chosen is ActionKind.INVESTIGATE
    opp.details["investigations"] = 1
    assert decide(opp, mandate, Context(0, 0)).chosen is ActionKind.RUN_EXPERIMENT


def test_style_outside_what_the_team_lints_is_declined(mandate: Mandate) -> None:
    # Found on PR16's dev scenario `low-value-style`: the CI runs `ruff check src tests`; tests run from `.`.
    def lint(path: str) -> Opportunity:
        return Opportunity(
            source="ruff", category="lint", title="t", summary="s", dedup_key=path,
            evidence=[EvidenceRef(kind="file", locator=path)], details={"tool": "ruff", "paths": [path]},
        )  # fmt: skip

    ctx = Context(0, 0, checked_dirs=(".",), ci_commands="ruff check src tests\npytest")
    decision = decide(lint("scripts/count.py"), mandate, ctx)
    assert decision.chosen is ActionKind.DECLINE and "src" in decision.reason
    assert decide(lint("src/pantry/handlers.py"), mandate, ctx).chosen is ActionKind.RUN_EXPERIMENT


def test_the_cycle_carries_each_action_out_through_the_existing_jobs(store: Store) -> None:
    cycle = Cycle(SimpleNamespace(store=store), log=lambda _: None)  # type: ignore[arg-type]
    measured = world_opp(table="orders", rows=None)
    store.put("opportunities", measured)
    cycle._before_experiment(measured, ActionKind.MEASURE)  # pyright: ignore[reportPrivateUsage]
    cycle._before_experiment(measured, ActionKind.MEASURE)  # pyright: ignore[reportPrivateUsage]
    assert measured.details["measure"]["asked"] == 2
    store.put("needs", CapabilityNeed(id="need_1", kind="log_adapter", source="compose:api", why="x"))
    reader = world_opp(service="api", traffic="unknown")
    cycle._before_experiment(reader, ActionKind.ACQUIRE_CAPABILITY)  # pyright: ignore[reportPrivateUsage]
    need = store.get("needs", "need_1", CapabilityNeed)
    assert need is not None and need.resume == [{"type": "director.sweep", "key": f"need:{reader.id}"}]
    signal = world_opp(incident={"good": "a", "bad": "b", "incident": "5xx", "subject": "api"})
    cycle._before_experiment(signal, ActionKind.INVESTIGATE)  # pyright: ignore[reportPrivateUsage]
    cycle._before_experiment(signal, ActionKind.INVESTIGATE)  # pyright: ignore[reportPrivateUsage]
    types = sorted(j.type for j in store.jobs())
    assert types.count("world.refresh") == 2 and types.count("forge.build") == 1
    assert types.count("research.investigate") == 1 and signal.details["investigations"] == 1
