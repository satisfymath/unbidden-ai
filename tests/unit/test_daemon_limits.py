from __future__ import annotations

import asyncio
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.guardian import Mandate
from unbidden.daemon import loop
from unbidden.daemon.cycle import retry_after, timeout_for
from unbidden.guardian.killswitch import (
    CURRENT,
    Cancelled,
    JobScope,
    KillSwitch,
    TrackingExecutor,
    before_effect,
    checkpoint,
    labels,
)
from unbidden.store import Store

pytestmark = pytest.mark.unit


def test_retries_back_off_and_are_capped() -> None:
    assert [retry_after(n) for n in (1, 2, 3)] == [timedelta(minutes=2), timedelta(minutes=4), timedelta(minutes=8)]
    assert retry_after(12) == timedelta(hours=1)


def test_a_hung_job_is_cancelled_and_the_next_one_still_runs(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from unbidden.daemon.cycle import job

    monkeypatch.setattr(loop, "timeout_for", lambda _: 0.05)
    ran: list[str] = []

    async def hangs(_: Any) -> None:
        await asyncio.sleep(10)

    async def quick(_: Any) -> None:
        ran.append("quick")

    store.enqueue(job("observe.head", "a"))
    store.enqueue(job("director.sweep", "b"))

    class Switch:
        engaged = False

    asyncio.run(
        loop._work(  # pyright: ignore[reportPrivateUsage]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            {"observe.head": hangs, "director.sweep": quick, "github.poll": quick},
            store,
            Switch(),
            lambda _: None,
            1,
            timedelta(minutes=5),
            True,
        )
    )
    assert "quick" in ran
    hung = next(j for j in store.jobs() if j.type == "observe.head" and j.idempotency_key.endswith(":a"))
    assert hung.last_error == "stopped: ran past 0.05 s" and hung.status.value == "queued"
    assert timeout_for("lab.experiment") > timeout_for("observe.head")


class _Switch:
    def __init__(self) -> None:
        self.engaged = False


def _run(handler: Any, scope: Any, switch: Any, timeout_s: float) -> None:
    async def main() -> None:
        asyncio.get_running_loop().set_default_executor(TrackingExecutor())
        await loop.run_job(handler, object(), scope, switch, timeout_s)

    asyncio.run(main())


def test_a_timed_out_job_stops_its_threads_at_the_next_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # F3: wait_for cancelled the coroutine and left the thread working, and a retry could run beside it.
    monkeypatch.setattr(loop, "kill_containers", lambda *_: 0)
    steps: list[int] = []

    def work() -> None:
        for i in range(200):
            checkpoint("next step")
            steps.append(i)
            time.sleep(0.01)

    async def handler(_: Any) -> None:
        await asyncio.to_thread(work)

    scope = JobScope("job_1")
    with pytest.raises(loop.Stopped) as stopped:
        _run(handler, scope, _Switch(), 0.1)
    assert stopped.value.drained and scope.active == 0
    done = len(steps)
    time.sleep(0.1)
    assert len(steps) == done < 200  # nothing ran after the stop


def test_a_job_whose_thread_ignores_the_stop_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop, "kill_containers", lambda *_: 0)
    monkeypatch.setattr(loop, "DRAIN_S", 0.2)
    release = threading.Event()

    async def handler(_: Any) -> None:
        await asyncio.to_thread(release.wait, 5)  # no checkpoint: work Python cannot interrupt

    scope = JobScope("job_2")
    threading.Timer(0.4, release.set).start()  # ends the thread after the drain gave up, so the test does not wait
    with pytest.raises(loop.Stopped) as stopped:
        _run(handler, scope, _Switch(), 0.1)
    assert not stopped.value.drained and "not retried" in str(stopped.value)


def test_the_kill_switch_stops_a_running_job_and_kills_its_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[str | None] = []
    monkeypatch.setattr(loop, "kill_containers", lambda job_id=None: killed.append(job_id) or 1)
    switch = _Switch()

    async def handler(_: Any) -> None:
        await asyncio.sleep(0.2)
        switch.engaged = True
        await asyncio.sleep(10)

    with pytest.raises(loop.Stopped, match="kill switch"):
        _run(handler, JobScope("job_3"), switch, 60)
    assert killed == ["job_3"]


def test_sandbox_containers_carry_the_job_that_started_them() -> None:
    assert labels() == ["--label", "unbidden.sandbox=1"]
    token = CURRENT.set(JobScope("job_4"))
    try:
        assert labels() == ["--label", "unbidden.sandbox=1", "--label", "unbidden.job=job_4"]
    finally:
        CURRENT.reset(token)


def test_effects_check_the_switch_immediately_before_acting(tmp_path: Path, mandate: Mandate) -> None:
    from unbidden.operate.deploy import deploy

    store = Store(tmp_path / "state.db")
    KillSwitch(tmp_path).engage("stop")
    with pytest.raises(Cancelled, match="kill switch"):
        before_effect(store, "merge")
    mandate.operations.deploy_steps = [["true"]]
    mandate.autonomy.deploy = __import__("unbidden.contracts.guardian", fromlist=["Autonomy"]).Autonomy.ALLOW
    with pytest.raises(Cancelled):
        deploy(tmp_path, store, mandate, "a" * 40, reason="t")
    assert store.get_value("deploys", []) == []
