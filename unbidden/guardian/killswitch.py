"""Stopping Unbidden: the kill switch, and what a stop reaches.

A stop reaches four things, each in its own way:
- jobs: no job starts while the switch is engaged;
- running work: the job's scope is cancelled, the sandbox containers it started are killed (they carry its label),
  and its code stops at the next checkpoint (a sandbox run, a model call, an external effect);
- external effects (push, pull request, merge, deploy, rollback, a remote judge): each checks the switch immediately
  before acting, whether or not a job runs it;
- threads: Python cannot kill a thread, so a stopped job whose threads are still working after a grace period is
  not retried, and is recorded as such, rather than run twice at once.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SANDBOX_LABEL = "unbidden.sandbox"
JOB_LABEL = "unbidden.job"


class KillSwitch:
    """A file anyone can create by hand. While it exists, no job starts, no model is called, no effect is made."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "KILL"

    @classmethod
    def of(cls, store: Any) -> KillSwitch | None:
        """The switch of the workspace a store belongs to (the state database lives in the workspace directory)."""
        path = getattr(store, "path", None)
        return cls(path.parent) if isinstance(path, Path) else None

    @property
    def engaged(self) -> bool:
        return self.path.exists()

    def engage(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(reason.strip() + "\n")

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


class Cancelled(RuntimeError):
    """The work was stopped: its job timed out or the kill switch was engaged."""


@dataclass
class JobScope:
    job_id: str
    cancelled: threading.Event = field(default_factory=threading.Event)
    why: str = ""
    _active: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def cancel(self, why: str) -> None:
        self.why = self.why or why
        self.cancelled.set()

    @property
    def active(self) -> int:
        """Threads still working for this job."""
        with self._lock:
            return self._active

    def enter(self) -> None:
        with self._lock:
            self._active += 1

    def exit(self) -> None:
        with self._lock:
            self._active -= 1


CURRENT: ContextVar[JobScope | None] = ContextVar("unbidden_job", default=None)


def checkpoint(what: str) -> None:
    """Raise if the current job was cancelled: called before starting anything that takes time or has an effect."""
    scope = CURRENT.get()
    if scope is not None and scope.cancelled.is_set():
        raise Cancelled(f"{what} not started: {scope.why}")


def before_effect(store: Any, what: str) -> None:
    """Immediately before an external effect: the job must not be cancelled and the switch must not be engaged."""
    checkpoint(what)
    switch = KillSwitch.of(store)
    if switch is not None and switch.engaged:
        raise Cancelled(f"{what} not done: the kill switch is engaged")


def labels() -> list[str]:
    """docker run arguments that tie a sandbox container to Unbidden and to the job that started it."""
    scope = CURRENT.get()
    return ["--label", f"{SANDBOX_LABEL}=1", *(["--label", f"{JOB_LABEL}={scope.job_id}"] if scope else [])]


def kill_containers(job_id: str | None = None, docker: str = "docker") -> int:
    """Kill the sandbox containers of one job, or every sandbox container Unbidden started. Only containers carrying
    Unbidden's label are touched. Returns how many were killed."""
    selector = f"{JOB_LABEL}={job_id}" if job_id else f"{SANDBOX_LABEL}=1"
    try:
        listed = subprocess.run(
            [docker, "ps", "-q", "--filter", f"label={selector}"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return 0
    ids = listed.stdout.split()
    if ids:
        subprocess.run([docker, "kill", *ids], capture_output=True, check=False)
    return len(ids)


class TrackingExecutor(ThreadPoolExecutor):
    """The event loop's default executor: each thread a job starts (`asyncio.to_thread`, anywhere below the job's
    handler) is counted on the job's scope, so the loop knows whether a stopped job has really finished."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        scope = CURRENT.get()  # read on the loop's thread, inside the job's task context
        if scope is None:
            return super().submit(fn, *args, **kwargs)
        scope.enter()

        def tracked() -> Any:
            try:
                return fn(*args, **kwargs)
            finally:
                scope.exit()

        return super().submit(tracked)
