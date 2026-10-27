from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from unbidden.daemon import loop
from unbidden.daemon.cycle import retry_after, timeout_for
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
    assert hung.last_error == "timed out" and hung.status.value == "queued"
    assert timeout_for("lab.experiment") > timeout_for("observe.head")
