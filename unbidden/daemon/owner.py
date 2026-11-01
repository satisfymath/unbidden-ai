"""Who runs the engine: one job executor per workspace, told apart by a lock the kernel keeps.

The risk two processes pose is not the database (SQLite serializes writers) but two *executors*: `requeue_running`
would steal the RUNNING jobs of a live process, two probe threads would measure the same system, and `try`, `scan`
or `deploy` would run the same effect a `watch` is running. So every command that executes jobs or effects takes
this lock; short decisions (`approve`, `mode`, `kill`, ...) do not: they are transactions the loop reads on its next
cycle.

The lock is `fcntl.flock(LOCK_EX | LOCK_NB)` on `.unbidden/engine.lock`. The holder writes who it is into the file
(pid, host, start, command, version) *after* acquiring, and removes the file on release. The kernel drops the lock
when the holder dies, however it dies, so no pid heuristics are needed:

- lock held: the engine is running; the file says who (`holder`);
- file present, lock free: the last run ended without `unbidden stop` (a crash, a `kill -9`, a closed laptop);
  `stale()` says so, and the next `acquire` simply succeeds;
- no file: the last run ended cleanly.

A pid is signalled only when the lock is held *and* the process behind it is an unbidden (`alive_holder`): a pid
read from a file is never trusted on its own, because pids are reused.

flock does not work across NFS; the workspace is a local checkout by design.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from unbidden import __version__
from unbidden.contracts.common import utc_now
from unbidden.workspace import WorkspaceError

LOCK_NAME = "engine.lock"
_READ_RETRIES = 10  # the holder writes right after locking; a probe in that window reads again


class EngineBusy(WorkspaceError):
    """Another process executes this workspace's jobs."""


def busy_message(info: dict[str, Any]) -> str:
    return (
        f"another unbidden is working in this workspace: pid {info.get('pid', '?')} "
        f"(unbidden {info.get('command', '?')}, started {info.get('started_at', '?')}, host {info.get('host', '?')}). "
        "See it: unbidden status · stop it: unbidden stop"
    )


class EngineLock:
    """The engine lock, held from `acquire` to `release` (or to the end of the process)."""

    def __init__(self, path: Path, fd: int, info: dict[str, Any]) -> None:
        self.path = path
        self._fd: int | None = fd
        self.info = info

    @classmethod
    def acquire(cls, state_dir: Path, command: str) -> EngineLock:
        """Take the lock for `command`, or raise EngineBusy naming the process that has it."""
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / LOCK_NAME
        for _ in range(20):
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                raise EngineBusy(busy_message(_wait_for_content(path))) from None
            # A release unlinks the file: if that happened between our open and our lock, we hold an orphaned
            # inode and another process could lock the new file. Check the path still means our descriptor.
            try:
                same = os.fstat(fd).st_ino == os.stat(path).st_ino
            except FileNotFoundError:
                same = False
            if same:
                break
            os.close(fd)
            time.sleep(0.01)
        else:  # pragma: no cover - twenty releases in a row during our acquire
            raise EngineBusy("the engine lock keeps changing hands; try again")
        info = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": utc_now().isoformat(),
            "command": command,
            "version": __version__,
            "argv_hint": _argv_hint(),
        }
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(info).encode())
        os.fsync(fd)
        return cls(path, fd, info)

    def release(self) -> None:
        """Remove the file, then let the lock go: a free lock without a file is a clean end."""
        if self._fd is None:
            return
        try:
            if _same_inode(self._fd, self.path):
                self.path.unlink(missing_ok=True)
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def __enter__(self) -> EngineLock:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def holder(state_dir: Path) -> dict[str, Any] | None:
    """Who holds the lock now, or None when the engine is not running (whatever the file says)."""
    path = state_dir / LOCK_NAME
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return _wait_for_content(path)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def last(state_dir: Path) -> dict[str, Any] | None:
    """What the file says, whether or not the lock is held; None without a readable file."""
    return _read(state_dir / LOCK_NAME)


def stale(state_dir: Path) -> bool:
    """File present with content, lock free: the last run ended without `unbidden stop`."""
    return last(state_dir) is not None and holder(state_dir) is None


def alive_holder(state_dir: Path) -> dict[str, Any] | None:
    """The holder, only if its pid is a live process whose command line names unbidden; the only pid a signal may
    ever go to."""
    info = holder(state_dir)
    if info is None:
        return None
    pid = info.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    return info if "unbidden" in _command_of(pid) else None


def _command_of(pid: int) -> str:
    """The command line of a live process, '' when there is none (no psutil: `ps` is everywhere)."""
    try:
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, check=False, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _argv_hint() -> str:
    return " ".join(Path(a).name if i == 0 else a for i, a in enumerate(sys.argv[:4]))[:120]


def _same_inode(fd: int, path: Path) -> bool:
    try:
        return os.fstat(fd).st_ino == os.stat(path).st_ino
    except FileNotFoundError:
        return False


def _read(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _wait_for_content(path: Path) -> dict[str, Any]:
    """A held lock whose holder has not written yet: read again briefly, then say what little is known."""
    for _ in range(_READ_RETRIES):
        data = _read(path)
        if data is not None:
            return data
        time.sleep(0.02)
    return {"pid": None, "command": "?", "started_at": "?", "host": "?"}
