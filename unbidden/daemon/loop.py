"""The background loop behind `unbidden watch`: a scheduler and one worker in a single process."""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from datetime import timedelta
from typing import Any

from unbidden.contracts.common import utc_now
from unbidden.contracts.llm import Tier
from unbidden.daemon.cycle import Cycle, Log, job, retry_after, timeout_for
from unbidden.guardian.killswitch import CURRENT, JobScope, TrackingExecutor, kill_containers
from unbidden.runtime import Runtime

HEALTH_EVERY_S = 60.0
MAP_EVERY_S = 300.0  # the running system's map, refreshed between commits (no model call)


def _model_key(runtime: Runtime) -> str | None:
    """The remote model's key, read only to send what the mandate allows; never logged or stored."""

    route = runtime.config.routing.get(Tier.CODE)
    provider = runtime.brain.providers.get(route.provider) if route else None
    from unbidden.guardian.credentials import broker

    return broker().get(getattr(provider, "key_env", ""), "model.remote") or None


def _probe_forever(runtime: Runtime, log: Log, stop: threading.Event) -> None:
    """Probes run on their own thread with their own connection, so long lab or model work never starves them:
    a deploy that is not observed cannot be judged."""
    from unbidden.contracts.world import WorldModel
    from unbidden.observe.health import HealthWatcher, UiCheck
    from unbidden.observe.live import LiveWatcher
    from unbidden.observe.logs import LOG_EVERY_S, LogWatcher
    from unbidden.world import jaeger, prometheus

    store = runtime.workspace.store()
    killswitch = runtime.workspace.killswitch()
    last_health = 0.0
    last_logs = 0.0
    while not stop.is_set():
        mandate = runtime.workspace.mandate()
        world = store.get("world", "world", WorldModel)
        if world is not None and world.of_kind("endpoint") and not killswitch.engaged:
            try:
                LiveWatcher(runtime.workspace.repo, store, mandate, world, log).tick()
            except Exception as exc:
                log(f"live probe failed: {exc}")
        if world is not None and not killswitch.engaged and time.monotonic() - last_logs >= LOG_EVERY_S:
            last_logs = time.monotonic()
            try:
                LogWatcher(store, world, log).tick()
            except Exception as exc:
                log(f"log window failed: {exc}")
        url = prometheus.find(world) if world is not None else None
        if url and not killswitch.engaged and time.monotonic() - last_health >= HEALTH_EVERY_S:
            last_health = time.monotonic()
            try:
                traces = jaeger.find(world)  # type: ignore[arg-type]
                ui = UiCheck(store, world, runtime.workspace.dir / "artifacts" / "ui", _model_key(runtime))  # type: ignore[arg-type]
                HealthWatcher(store, world, prometheus.Prometheus(url), log, traces, ui, mandate).tick()  # type: ignore[arg-type]
            except Exception as exc:
                log(f"health check failed: {exc}")
        stop.wait(mandate.operations.probe_every_s)


async def watch(
    runtime: Runtime,
    *,
    log: Log = print,
    interval_s: float = 30,
    poll_every: timedelta = timedelta(minutes=5),
    once: bool = False,
) -> None:
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
    asyncio.get_running_loop().set_default_executor(TrackingExecutor())
    stop = threading.Event()
    if not once:
        threading.Thread(target=_probe_forever, args=(runtime, log, stop), name="unbidden-probes", daemon=True).start()
    try:
        await _work(runtime, cycle, handlers, store, killswitch, log, interval_s, poll_every, once)
    finally:
        stop.set()


class Stopped(Exception):
    """A job stopped from outside: past its time, or by the kill switch."""

    def __init__(self, why: str, *, drained: bool) -> None:
        tail = "" if drained else f"; its threads were still working after {DRAIN_S:.0f} s, so it is not retried"
        super().__init__(why + tail)
        self.drained = drained


DRAIN_S = 30.0
KILL_POLL_S = 1.0


async def run_job(handler: Any, claimed: Any, scope: JobScope, killswitch: Any, timeout_s: float) -> None:
    """Run one job under its scope. On timeout or kill switch: cancel the scope (its code stops at the next
    checkpoint), kill the sandbox containers it started, cancel the task, and wait for its threads to end."""
    token = CURRENT.set(scope)
    try:
        task = asyncio.ensure_future(handler(claimed))  # the task copies the context: the scope goes with it
    finally:
        CURRENT.reset(token)
    deadline = time.monotonic() + timeout_s
    while not task.done():
        await asyncio.wait({task}, timeout=min(KILL_POLL_S, max(0.0, deadline - time.monotonic())))
        if task.done():
            break
        if killswitch.engaged:
            scope.cancel("the kill switch was engaged")
        elif time.monotonic() >= deadline:
            scope.cancel(f"ran past {timeout_s:g} s")
        if scope.cancelled.is_set():
            await asyncio.to_thread(kill_containers, scope.job_id)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise Stopped(f"stopped: {scope.why}", drained=await _drained(scope))
    task.result()


async def _drained(scope: JobScope) -> bool:
    end = time.monotonic() + DRAIN_S
    while scope.active and time.monotonic() < end:
        await asyncio.sleep(0.2)
    return scope.active == 0


async def _work(
    runtime: Runtime,
    cycle: Cycle,
    handlers: dict[str, Any],
    store: Any,
    killswitch: Any,
    log: Log,
    interval_s: float,
    poll_every: timedelta,
    once: bool,
) -> None:
    while True:
        now = utc_now()
        bucket = int(now.timestamp() // interval_s)
        store.enqueue(job("observe.head", str(bucket)))
        if once:
            store.enqueue(job("observe.live", str(bucket)))
        store.enqueue(job("director.sweep", f"tick:{bucket}"))
        store.enqueue(job("github.poll", str(int(now.timestamp() // poll_every.total_seconds()))))
        if not once:
            store.enqueue(job("world.refresh", str(int(now.timestamp() // MAP_EVERY_S))))
        # Every cycle starts by checking its connections: a `--once` run, or a daemon at each map interval.
        store.enqueue(job("connect.survey", now.isoformat() if once else str(int(now.timestamp() // MAP_EVERY_S))))
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
            scope = JobScope(claimed.id)
            try:
                await run_job(handler, claimed, scope, killswitch, timeout_for(claimed.type))
            except Stopped as stop:
                log(f"{claimed.type}: {stop}")
                # Retried only once every thread it started has ended: never two copies of a job at once.
                retry = retry_after(claimed.attempts) if stop.drained else None
                store.finish(claimed, error=str(stop), retry_in=retry)
            except Exception as exc:
                log(f"{claimed.type} failed: {exc}")
                store.finish(
                    claimed,
                    error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}",
                    retry_in=retry_after(claimed.attempts),
                )
            else:
                store.finish(claimed)
        if once:
            return
        await asyncio.sleep(interval_s)
