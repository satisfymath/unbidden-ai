"""The agent in the background: `unbidden start`, `unbidden stop`, and what `status` says about it.

`start` spawns `unbidden watch` in its own session (no terminal, no SIGHUP when the terminal closes), with stdout and
stderr appended to `.unbidden/logs/agent.log`, and waits until the child owns the workspace (daemon/owner.py).
`stop` sends SIGTERM to the owner and waits for the lock to be released: the loop finishes or puts back the job it
was running, and the process ends; past the timeout, SIGKILL. Jobs left RUNNING by a forced stop are requeued by
the next `watch` (`Store.requeue_running`), which is correct because there is one executor by construction.

Nothing here survives a reboot: no launchd, no systemd, no crontab. After a reboot the agent is not running and
`unbidden status` says so (and whether the last run ended without `unbidden stop`).

Neither `start` nor `stop` touches the kill switch (`.unbidden/KILL`): `kill` freezes, and the freeze persists until
`resume`; `stop` ends a process and freezes nothing. `start` after `kill` starts a process that waits.

The child's environment is the parent's: no secret is added to argv or env; the child reads unbidden's own `.env`
into its credential broker itself (`Workspace.load_env`).
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from unbidden.contracts.jobs import JobStatus
from unbidden.daemon import owner
from unbidden.workspace import Workspace

LOG_NAME = "agent.log"
LOG_MAX_BYTES = 20 * 1024 * 1024
START_WAIT_S = 5.0
POLL_S = 0.2
TAIL_LINES = 20


def agent_command(interval_s: float, extra_args: Sequence[str] = ()) -> list[str]:
    """The child's argv: this interpreter running `unbidden watch`."""
    return [sys.executable, "-m", "unbidden.cli", "watch", "--interval", str(interval_s), *extra_args]


def start(
    ws: Workspace,
    *,
    interval_s: float = 30,
    log_dir: Path | None = None,
    extra_args: Sequence[str] = (),
    command: Sequence[str] | None = None,
    wait_s: float = START_WAIT_S,
) -> dict[str, Any]:
    """Spawn the agent unless one owns the workspace already.

    `command` replaces the whole argv (tests use a stand-in that takes the lock); by default it is `agent_command`.
    Returns `{"started": True, "pid", "log"}`, `{"started": False, "already": <holder>}` when the lock was held, or
    `{"started": False, "exit": <code>, "log_tail": [...]}` when the child ended before owning the workspace.
    """
    existing = owner.holder(ws.dir)
    if existing is not None:
        return {"started": False, "already": existing}
    log_path = _log_path(ws, log_dir)
    _rotate(log_path)
    argv = list(command) if command is not None else agent_command(interval_s, extra_args)
    with open(log_path, "ab") as log_file:
        child = subprocess.Popen(
            argv,
            cwd=ws.repo,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=os.environ.copy(),
        )
    deadline = time.monotonic() + wait_s
    while True:
        held = owner.holder(ws.dir)
        if held is not None and held.get("pid") == child.pid:
            return {"started": True, "pid": child.pid, "log": str(log_path)}
        code = child.poll()
        if code is not None:
            if held is not None:  # someone else won the race; the child said so and left
                return {"started": False, "already": held}
            return {"started": False, "exit": code, "log_tail": _tail(log_path)}
        if time.monotonic() >= deadline:
            note = f"the child did not own the workspace within {wait_s:g} s; it may still be starting"
            return {"started": False, "exit": None, "log_tail": _tail(log_path), "pid": child.pid, "note": note}
        time.sleep(0.05)


def stop(ws: Workspace, *, timeout_s: float = 60) -> dict[str, Any]:
    """End the running agent: SIGTERM, wait for the lock to be released, SIGKILL past the timeout."""
    alive = owner.alive_holder(ws.dir)
    if alive is None:
        result: dict[str, Any] = {"stopped": False, "reason": "not running", "jobs_running": _running(ws)}
        if owner.stale(ws.dir):
            result["stale"], result["last"] = True, owner.last(ws.dir)
        return result
    pid = int(alive["pid"])
    began = time.monotonic()
    forced = False
    _signal(pid, signal.SIGTERM)
    if not _wait_free(ws.dir, pid, timeout_s):
        forced = True
        _signal(pid, signal.SIGKILL)
        _wait_free(ws.dir, pid, 5.0)  # the kernel releases the lock with the process
    return {
        "stopped": True,
        "pid": pid,
        "waited_s": round(time.monotonic() - began, 1),
        "forced": forced,
        "timeout_s": timeout_s,
        "jobs_left_running": _running(ws),
    }


def status(ws: Workspace) -> dict[str, Any]:
    """Running or not, who, since when, where its log is, whether the last run ended badly, and the queue."""
    held = owner.holder(ws.dir)
    running = held is not None
    info = held if held is not None else (owner.last(ws.dir) if owner.stale(ws.dir) else None) or {}
    return {
        "running": running,
        "pid": info.get("pid"),
        "started_at": info.get("started_at"),
        "command": info.get("command"),
        "log": str(_log_path(ws, None)),
        "stale": not running and owner.stale(ws.dir),
        "jobs_running": _running(ws),
        "jobs_queued": _count(ws, JobStatus.QUEUED),
    }


def _signal(pid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, sig)


def _wait_free(state_dir: Path, pid: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        held = owner.holder(state_dir)
        if held is None or held.get("pid") != pid:
            return True
        time.sleep(POLL_S)
    held = owner.holder(state_dir)
    return held is None or held.get("pid") != pid


def _running(ws: Workspace) -> int:
    return _count(ws, JobStatus.RUNNING)


def _count(ws: Workspace, status: JobStatus) -> int:
    if not (ws.dir / "state.db").exists():
        return 0
    store = ws.store()
    try:
        return len(store.jobs(status=status))
    finally:
        store.close()


def _log_path(ws: Workspace, log_dir: Path | None) -> Path:
    directory = log_dir if log_dir is not None else ws.dir / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / LOG_NAME


def _rotate(path: Path) -> None:
    """One previous log is kept: rename when the current one grew past the limit."""
    try:
        if path.stat().st_size > LOG_MAX_BYTES:
            path.rename(path.with_suffix(".log.1"))
    except FileNotFoundError:
        pass


def _tail(path: Path, lines: int = TAIL_LINES) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()[-lines:]
    except FileNotFoundError:
        return []
