"""Campaign 12, phase 6: a busy host and a reached spend cap are blocks, never verdicts on the candidate."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from unbidden.brain.router import BrainError, KillSwitchEngaged, PolicyDenied, SpendLimitReached
from unbidden.contracts.opportunity import EvidenceRef, Opportunity
from unbidden.lab import perf
from unbidden.lab.perf import PerfResult, experiment_not_executed, host_load_max, spend_blocked

pytestmark = pytest.mark.unit


def test_the_quiet_host_rule_scales_with_the_cpus_and_keeps_its_floor() -> None:
    # fst, campaign 12 run 2: an 18-CPU host idles at 2.5-3; the absolute 1.5 deferred every session for 900 s.
    assert host_load_max(4) == 1.5 and host_load_max(1) == 1.5
    assert host_load_max(18) == 4.5 and host_load_max(8) == 2.0


def test_a_deferral_is_the_block_itself_and_a_broken_workload_is_the_candidates() -> None:
    note, blocked = experiment_not_executed("deferred: the host is busy (1-minute load 2.80 > 1.50 for 4 CPUs)")
    assert blocked == note and note.startswith("deferred:")
    note, blocked = experiment_not_executed("candidate session 1: the application answered 500")
    assert blocked is None and note.startswith("the candidate broke the workload: ")


def test_the_cap_the_kill_switch_and_the_policy_block_without_repair_attempts() -> None:
    spend = spend_blocked(SpendLimitReached("remote spend this month is US$2.00, at the US$2.00 cap"))
    assert spend is not None and spend[0] == "spend" and "monthly spend cap" in spend[1] and "US$2.00" in spend[1]
    kill = spend_blocked(KillSwitchEngaged("kill switch engaged"))
    assert kill is not None and "unbidden resume" in kill[1]
    policy = spend_blocked(PolicyDenied("model.remote.synthetic denied"))
    assert policy is not None and policy[0] == "policy"
    assert spend_blocked(BrainError("timeout")) is None  # a failed answer is repaired or retried as before


class _CappedBrain:
    calls = 0

    async def complete_json(self, request: Any) -> Any:
        self.calls += 1
        raise SpendLimitReached("remote spend this month is US$2.00, at the US$2.00 cap")


async def test_choosing_a_request_at_the_cap_blocks_once_instead_of_five_attempts() -> None:
    # spoolman, campaign 12 run 2: five "choosing the request" attempts in one second, then "no workload was valid".
    lab = perf.PerfLab.__new__(perf.PerfLab)
    lab.progress = lambda *_: None  # type: ignore[method-assign]
    lab.prep_block = None
    brain = _CappedBrain()
    lab.brain = brain  # type: ignore[assignment]
    opp = Opportunity(
        source="world", category="performance", title="spool.filament_id", summary="s", dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="a")],
        details={"endpoints": ["GET /api/v1/spool"], "table": "spool", "column": "filament_id"},
    )  # fmt: skip
    result = PerfResult()
    request = await lab._choose_request(opp, ("spool", "filament_id"), "filament", [], "", result)  # pyright: ignore[reportPrivateUsage]
    assert request is None and brain.calls == 1
    assert lab.prep_block is not None and lab.prep_block[0] == "spend"
    assert result.notes[-1].startswith("lab.perf_request: the mandate's monthly spend cap stops model calls")


async def test_the_files_helper_blocks_the_same_way() -> None:
    lab = perf.PerfLab.__new__(perf.PerfLab)
    lab.prep_block = None

    class Brain:
        async def complete(self, request: Any) -> Any:
            raise KillSwitchEngaged("kill switch engaged")

    lab.brain = Brain()  # type: ignore[assignment]
    notes: list[str] = []
    opp = SimpleNamespace(id="opp_x")
    assert await lab._ask_files("lab.workload", "x = 1", opp, "sha", 10, notes) is None  # type: ignore[arg-type]  # pyright: ignore[reportPrivateUsage]
    assert lab.prep_block is not None and "unbidden resume" in lab.prep_block[1]
    assert notes[-1].startswith("lab.workload: ")
