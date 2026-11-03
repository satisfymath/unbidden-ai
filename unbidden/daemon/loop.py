"""The background loop behind `unbidden watch`: a scheduler and one worker in a single process."""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from datetime import timedelta
from typing import Any

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.jobs import Job, JobStatus
from unbidden.contracts.llm import Tier
from unbidden.daemon.cycle import Cycle, Log, job, retry_after, timeout_for
from unbidden.director.asks import reconcile
from unbidden.director.blocks import PARKED, release
from unbidden.director.pipeline import job_stage
from unbidden.guardian.killswitch import CURRENT, JobScope, TrackingExecutor, kill_containers
from unbidden.runtime import Runtime

HEALTH_EVERY_S = 60.0
MAP_EVERY_S = 300.0  # the running system's map, refreshed between commits (no model call)
DURATIONS_KEY = "durations"  # kv: job type -> the last seconds it took, for "this usually takes ~N s"
DURATIONS_KEPT = 10


def _job_event(store: Any, type_: EventType, claimed: Job, payload: dict[str, Any]) -> None:
    subject = next((str(v) for k, v in (claimed.payload or {}).items() if k in ("id", "goal", "opp")), None)
    store.append_event(Event(type=type_, actor="daemon", entity_id=claimed.id, correlation_id=claimed.correlation_id,
                             payload={"type": claimed.type, "subject": subject, **payload}))  # fmt: skip


def usual_seconds(store: Any, job_type: str) -> float | None:
    """The median of the last runs of this job type, or None the first time: nothing is invented."""
    kept = (store.get_value(DURATIONS_KEY) or {}).get(job_type) or []
    if not kept:
        return None
    ordered = sorted(float(x) for x in kept)
    return ordered[len(ordered) // 2]


def remember_seconds(store: Any, job_type: str, seconds: float) -> None:
    durations = dict(store.get_value(DURATIONS_KEY) or {})
    durations[job_type] = [*list(durations.get(job_type) or [])[-(DURATIONS_KEPT - 1) :], seconds]
    store.set_value(DURATIONS_KEY, durations)


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
    stopping: asyncio.Event | None = None,
) -> None:
    """Observe HEAD every `interval_s`, follow pull requests every `poll_every`, and work the queue in between.

    With `once`, run until the queue is empty and return: one full cycle, useful for demos and tests.
    `stopping`, once set (SIGTERM, SIGINT: `unbidden stop`), ends the loop cleanly: no new job is claimed, the job
    running is cancelled like the kill switch does and put back without spending an attempt, and `watch` returns.
    """
    cycle = Cycle(runtime, log=log)
    handlers = cycle.handlers()
    store = runtime.store
    requeued = store.requeue_running()
    if requeued:
        log(f"resumed {requeued} interrupted job(s)")
    from unbidden.publish.github import reconcile_publishing

    for proposal in reconcile_publishing(store):
        log(f"{proposal.id}: left publishing by a run that ended; ready again (an existing pull request is reused)")
    killswitch = runtime.workspace.killswitch()
    asyncio.get_running_loop().set_default_executor(TrackingExecutor())
    stop = threading.Event()
    if not once:
        threading.Thread(target=_probe_forever, args=(runtime, log, stop), name="unbidden-probes", daemon=True).start()
    try:
        await _work(runtime, cycle, handlers, store, killswitch, log, interval_s, poll_every, once, stopping=stopping)
    finally:
        stop.set()


class Stopped(Exception):
    """A job stopped from outside: past its time, by the kill switch, or by `unbidden stop`."""

    def __init__(self, why: str, *, drained: bool, by_stop: bool = False) -> None:
        tail = "" if drained else f"; its threads were still working after {DRAIN_S:.0f} s, so it is not retried"
        super().__init__(why + tail)
        self.drained = drained
        self.by_stop = by_stop  # the process is ending: the job resumes on the next start, no attempt spent


STOP_WHY = "unbidden stop"


DRAIN_S = 30.0
KILL_POLL_S = 1.0


async def run_job(
    handler: Any,
    claimed: Any,
    scope: JobScope,
    killswitch: Any,
    timeout_s: float,
    stopping: asyncio.Event | None = None,
) -> None:
    """Run one job under its scope. On timeout, kill switch or stop: cancel the scope (its code stops at the next
    checkpoint), kill the sandbox containers it started, cancel the task, and wait for its threads to end."""
    token = CURRENT.set(scope)
    try:
        task = asyncio.ensure_future(handler(claimed))  # the task copies the context: the scope goes with it
    finally:
        CURRENT.reset(token)
    deadline = time.monotonic() + timeout_s
    waited: set[asyncio.Future[Any]] = {task}
    stop_waiter = asyncio.ensure_future(stopping.wait()) if stopping is not None else None
    if stop_waiter is not None:
        waited.add(stop_waiter)  # a stop wakes this loop at once, not at the next poll
    try:
        while not task.done():
            timeout = min(KILL_POLL_S, max(0.0, deadline - time.monotonic()))
            await asyncio.wait(waited, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                break
            if killswitch.engaged:
                scope.cancel("the kill switch was engaged")
            elif stopping is not None and stopping.is_set():
                scope.cancel(STOP_WHY)
            elif time.monotonic() >= deadline:
                scope.cancel(f"ran past {timeout_s:g} s")
            if scope.cancelled.is_set():
                await asyncio.to_thread(kill_containers, scope.job_id)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise Stopped(f"stopped: {scope.why}", drained=await _drained(scope), by_stop=scope.why == STOP_WHY)
    finally:
        if stop_waiter is not None:
            stop_waiter.cancel()
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
    stopping: asyncio.Event | None = None,
) -> None:
    def stop_asked() -> bool:
        return stopping is not None and stopping.is_set()

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
        # What a person granted since the last cycle: the work it held runs now, not after its backoff.
        for met in release(store, runtime.workspace.mandate()) if runtime is not None else []:
            log(f"unblocked: {met.needs}; {len(met.jobs)} job(s) run again")
        for gone in reconcile(store):
            log(f"question withdrawn: {gone.title} ({gone.withdrawn_why})")
        while True:
            if stop_asked():
                break  # no new job once a stop was asked; the queue waits for the next start
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
            started, queued_before = time.monotonic(), {j.id for j in store.jobs(status=JobStatus.QUEUED)}
            _job_event(
                store,
                EventType.JOB_STARTED,
                claimed,
                {
                    "stage": job_stage(claimed.type)[1],
                    "doing": job_stage(claimed.type)[0],
                    "usual_s": usual_seconds(store, claimed.type),
                },
            )
            outcome = "ok"
            try:
                await run_job(handler, claimed, scope, killswitch, timeout_for(claimed.type), stopping)
            except Stopped as stop:
                outcome = "stopped"
                log(f"{claimed.type}: {stop}")
                # Retried only once every thread it started has ended: never two copies of a job at once.
                retry = retry_after(claimed.attempts) if stop.drained else None
                if stop.by_stop:
                    # The process ends here, its threads with it: the job resumes on the next start, due at once,
                    # and the interruption is not the job's own failure, so no attempt is spent.
                    claimed.attempts, retry = claimed.attempts - 1, timedelta(0)
                store.finish(claimed, error=str(stop), retry_in=retry)
            except Exception as exc:
                outcome = "failed"
                log(f"{claimed.type} failed: {exc}")
                from unbidden.director.blocks import classify, record

                subject = next((str(v) for k, v in (claimed.payload or {}).items() if k in ("id", "goal", "opp")), "")
                block = record(store, classify(f"{claimed.type} {subject}".strip(), f"{type(exc).__name__}: {exc}",
                                               f"{claimed.type} runs again"), claimed.id)  # fmt: skip
                retry = retry_after(claimed.attempts)
                if block.kind == "pending_person":
                    outcome = "parked"
                    log(f"needs a person: {block.needs} (then: {block.continues})")
                    # Parked until a person answers: waiting is not the job's own failure, so no attempt is spent.
                    claimed.attempts, retry = claimed.attempts - 1, PARKED
                    from unbidden.director.asks import for_block, open_ask

                    ask = for_block(block)
                    if ask is not None:
                        ask.correlation_id = claimed.correlation_id
                        open_ask(store, ask)
                store.finish(claimed, error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}",
                             retry_in=retry)  # fmt: skip
            else:
                store.finish(claimed)
            seconds = round(time.monotonic() - started, 1)
            queued_after = [j for j in store.jobs(status=JobStatus.QUEUED) if j.id not in queued_before]
            if outcome == "ok":
                remember_seconds(store, claimed.type, seconds)
            _job_event(
                store,
                EventType.JOB_FINISHED,
                claimed,
                {"outcome": outcome, "seconds": seconds, "next": sorted({j.type for j in queued_after})},
            )
        if once or stop_asked():
            return
        if stopping is None:
            await asyncio.sleep(interval_s)
            continue
        try:
            await asyncio.wait_for(stopping.wait(), interval_s)
        except TimeoutError:
            continue
        return  # stopped while idle
