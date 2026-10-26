"""The background loop behind `unbidden watch`: a scheduler and one worker in a single process."""

from __future__ import annotations

import asyncio
import traceback
from datetime import timedelta

from unbidden.contracts.common import utc_now
from unbidden.daemon.cycle import RETRY, Cycle, Log, job
from unbidden.runtime import Runtime


async def watch(
    runtime: Runtime, *, log: Log = print, interval_s: float = 30, poll_every: timedelta = timedelta(minutes=5),
    once: bool = False,
) -> None:  # fmt: skip
    """Observe HEAD every `interval_s`, follow pull requests every `poll_every`, and work the queue in between.

    With `once`, run until the queue is empty and return: one full cycle, useful for demos and tests.
    """
    cycle = Cycle(runtime, log=log)
    handlers = cycle.handlers()
    store = runtime.store
    requeued = store.requeue_running()
    if requeued:
        log(f"resumed {requeued} interrupted job(s)")
    killswitch = runtime.workspace.killswitch()
    while True:
        now = utc_now()
        bucket = int(now.timestamp() // interval_s)
        store.enqueue(job("observe.head", str(bucket)))
        store.enqueue(job("github.poll", str(int(now.timestamp() // poll_every.total_seconds()))))
        while True:
            if killswitch.engaged:
                log("kill switch engaged; waiting")
                break
            claimed = store.claim()
            if claimed is None:
                break
            handler = handlers.get(claimed.type)
            if handler is None:
                store.finish(claimed, error=f"no handler for {claimed.type}")
                continue
            try:
                await handler(claimed)
            except Exception as exc:
                log(f"{claimed.type} failed: {exc}")
                store.finish(claimed, error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}",
                             retry_in=RETRY)  # fmt: skip
            else:
                store.finish(claimed)
        if once:
            return
        await asyncio.sleep(interval_s)
