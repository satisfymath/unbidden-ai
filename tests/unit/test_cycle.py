from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.jobs import Job
from unbidden.contracts.opportunity import Decision, Opportunity
from unbidden.daemon.cycle import EXPERIMENTS_PER_SWEEP, Cycle
from unbidden.store import Store

pytestmark = pytest.mark.unit


def make_cycle(store: Store, mandate: Mandate) -> Cycle:
    workspace = SimpleNamespace(mandate=lambda: mandate, repo=Path("."))
    runtime: Any = SimpleNamespace(store=store, workspace=workspace)
    return Cycle(runtime, log=lambda _: None)


async def test_experiments_beyond_the_cap_are_queued_on_a_later_sweep(store: Store, mandate: Mandate) -> None:
    for i in range(EXPERIMENTS_PER_SWEEP + 1):
        opp = Opportunity(
            source="tsc", category="types", title=f"t{i}", summary="s", dedup_key=f"k{i}",
            evidence=[EvidenceRef(kind="file", locator="a")],
        )  # fmt: skip
        store.put("opportunities", opp, key=opp.dedup_key)
    cycle = make_cycle(store, mandate)
    sweep = Job(type="director.sweep", idempotency_key="s")
    await cycle.director_sweep(sweep)
    assert len([j for j in store.jobs() if j.type == "lab.experiment"]) == EXPERIMENTS_PER_SWEEP
    await cycle.director_sweep(sweep)
    assert len([j for j in store.jobs() if j.type == "lab.experiment"]) == EXPERIMENTS_PER_SWEEP + 1
    decisions = store.list("decisions", Decision)
    assert len(decisions) == EXPERIMENTS_PER_SWEEP + 1  # recorded once each


def test_every_handled_job_type_has_a_priority(store: Store, mandate: Mandate) -> None:
    from unbidden.daemon.cycle import PRIORITY

    assert set(make_cycle(store, mandate).handlers()) <= set(PRIORITY)
