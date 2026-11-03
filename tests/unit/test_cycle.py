from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.jobs import Job
from unbidden.contracts.opportunity import Decision, Opportunity
from unbidden.daemon.cycle import EXPERIMENTS_PER_SWEEP, Cycle
from unbidden.store import Store

pytestmark = pytest.mark.unit


def make_cycle(store: Store, mandate: Mandate, *, checks: str | None = "passed") -> Cycle:
    """A cycle whose project checks ran at the head with `checks` (None: they have not run yet)."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    store.set_value("head", head)
    if checks is not None:
        store.set_value("baseline_checks", {"rev": head, "status": checks, "collected": 12})
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


def _opps(store: Store, n: int) -> None:
    for i in range(n):
        opp = Opportunity(
            source="tsc", category="types", title=f"t{i}", summary="s", dedup_key=f"k{i}",
            evidence=[EvidenceRef(kind="file", locator="a")],
        )  # fmt: skip
        store.put("opportunities", opp, key=opp.dedup_key)


@pytest.mark.parametrize("checks", [None, "infra_failed", "no_plan"])
async def test_no_experiment_starts_before_the_checks_are_reproduced(
    store: Store, mandate: Mandate, checks: str | None
) -> None:
    """Stage 10 (Prefect B-post1): 229 experiments ran on a commit whose base checks had failed to start."""
    _opps(store, 2)
    cycle = make_cycle(store, mandate, checks=checks)
    await cycle.director_sweep(Job(type="director.sweep", idempotency_key="s"))
    assert not [j for j in store.jobs() if j.type == "lab.experiment"]
    assert store.get_value("readiness_block")["rev"] == store.get_value("head")


async def test_one_sweep_waits_at_a_time(store: Store, mandate: Mandate) -> None:
    """Stage 10: every finished experiment queued its own sweep; the queue of Prefect's cycle never emptied."""
    cycle = make_cycle(store, mandate)
    for i in range(5):
        cycle._wake(f"after:{i}")  # pyright: ignore[reportPrivateUsage]
    assert len([j for j in store.jobs() if j.type == "director.sweep"]) == 1


async def test_a_measurement_deferred_by_a_busy_host_is_repeated_once_then_stays_deferred(
    store: Store, mandate: Mandate
) -> None:
    """Campaign to v1.0 (section 6): a predefined retry policy; an attempt the host prevented is not counted."""
    _opps(store, 1)
    cycle = make_cycle(store, mandate)
    sweep = Job(type="director.sweep", idempotency_key="s")
    await cycle.director_sweep(sweep)
    assert len([j for j in store.jobs() if j.type == "lab.experiment"]) == 1
    opp = store.list("opportunities", Opportunity)[0]
    opp.details = {**opp.details, "blocked": {"why": "deferred: the host is busy"}, "deferrals": 1}
    store.put("opportunities", opp, key=opp.dedup_key)
    await cycle.director_sweep(sweep)
    jobs = [j for j in store.jobs() if j.type == "lab.experiment"]
    assert len(jobs) == 2 and jobs[-1].idempotency_key.endswith(":d1")  # one repeat
    opp.details = {**opp.details, "deferrals": 2}
    store.put("opportunities", opp, key=opp.dedup_key)
    await cycle.director_sweep(sweep)
    assert len([j for j in store.jobs() if j.type == "lab.experiment"]) == 2  # no third try at this commit
    assert int(opp.details.get("attempts", 0)) == 0  # never counted as a failed attempt


async def test_a_proposal_that_needs_approval_opens_one_ask_and_a_note(
    store: Store, mandate: Mandate, tmp_path: Path
) -> None:
    """github_publish under `require_approval`: the NeedsApproval becomes a question with options, once, plus a NOTE
    event the app shows; publishing is never attempted."""
    from unbidden.contracts.common import EvidenceLevel
    from unbidden.contracts.events import EventType
    from unbidden.contracts.experiment import Proposal
    from unbidden.director.asks import open_asks

    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    opp = Opportunity(id="opp_a", source="t", category="perf", title="t", summary="s", dedup_key="opp_a",
                      evidence=[EvidenceRef(kind="file", locator="a")],
                      evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION)  # fmt: skip
    store.put("opportunities", opp, key="opp_a")
    proposal = Proposal(opportunity_id="opp_a", experiment_id="exp_a", branch="unbidden/t", base_sha=sha,
                        commit_sha=sha, title="t", body_md="b",
                        evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION)  # fmt: skip
    store.put("proposals", proposal, key="opp_a")
    cycle = make_cycle(store, mandate)
    cast(Any, cycle.runtime).workspace.dir = tmp_path  # where a patch artifact would be; none here
    job_ = Job(type="github.publish", idempotency_key="pub:1", payload={"id": proposal.id})
    await cycle.github_publish(job_)
    await cycle.github_publish(job_)
    asks = open_asks(store)
    assert len(asks) == 1 and asks[0].kind == "approval" and asks[0].subject == "opp_a"
    notes = [e for e in store.events() if e.type is EventType.NOTE]
    assert notes and "waiting for a person" in notes[0].payload["text"]


async def test_a_measurement_stopped_by_the_monthly_cap_is_listed_as_a_persons_block(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Campaign 12, spoolman run 2: the cap was hit inside the lab and the record's blocks stayed empty."""
    from unbidden.director.blocks import open_blocks
    from unbidden.lab import perf

    cycle = make_cycle(store, mandate)
    head = store.get_value("head")
    opp = Opportunity(
        source="world", category="performance", title="spool.filament_id", summary="s", dedup_key="perf1",
        evidence=[EvidenceRef(kind="file", locator="a")], details={"rev": head, "table": "spool"},
    )  # fmt: skip
    store.put("opportunities", opp, key=opp.dedup_key)
    monkeypatch.setattr(cycle, "_env", lambda rev: (None, {}))
    runtime: Any = cycle.runtime
    runtime.brain = None  # the stub below never calls it

    class Stopped:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        async def run(self, opp: Opportunity) -> perf.PerfResult:
            return perf.PerfResult(blocked="cannot measure: the mandate's monthly spend cap stops model calls "
                                   "(remote spend this month is US$2.00, at the US$2.00 cap)")  # fmt: skip

    monkeypatch.setattr(perf, "PerfLab", Stopped)
    await cycle.lab_experiment(Job(type="lab.experiment", idempotency_key="e", payload={"id": opp.id}))
    blocks = open_blocks(store)
    assert len(blocks) == 1 and blocks[0].kind == "pending_person" and "maximum_monthly_spend_usd" in blocks[0].needs
    assert blocks[0].continues.startswith(f"the measurement of {opp.id}")
    kept = store.get("opportunities", opp.id, Opportunity)
    assert kept is not None and "monthly spend cap" in kept.details["blocked"]["why"] and "attempts" not in kept.details
