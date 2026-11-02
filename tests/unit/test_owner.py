"""The engine lock: one executor per workspace, told apart by a lock the kernel keeps (unbidden/daemon/owner.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from unbidden.daemon import owner
from unbidden.daemon.owner import EngineBusy, EngineLock

pytestmark = pytest.mark.unit


def _hold(argv: list[str], reaper: list[int], *, stdin: Any = subprocess.DEVNULL) -> subprocess.Popen[str]:
    child = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    reaper.append(child.pid)
    assert child.stdout is not None
    line = child.stdout.readline()  # the child says "held" once it owns the lock
    assert line.strip() == "held", line
    return child


def test_a_second_process_is_refused_with_the_first_ones_pid(
    tmp_path: Path, standin_argv: Any, reaper: list[int]
) -> None:
    first = _hold(standin_argv(tmp_path, "exit-dirty"), reaper, stdin=subprocess.PIPE)
    with pytest.raises(EngineBusy) as refused:
        EngineLock.acquire(tmp_path, "scan")
    message = str(refused.value)
    assert message.startswith(
        f"another unbidden is working in this workspace: pid {first.pid} (unbidden watch, started "
    )
    assert message.endswith("See it: unbidden status · stop it: unbidden stop")
    held = owner.holder(tmp_path)
    assert held is not None and held["pid"] == first.pid and held["command"] == "watch"
    assert owner.stale(tmp_path) is False
    # The first ends without releasing (no `unbidden stop`): the kernel frees the lock, the file stays.
    assert first.stdin is not None
    first.stdin.write("\n")
    first.stdin.close()
    assert first.wait(timeout=10) == 0
    assert owner.holder(tmp_path) is None
    assert owner.stale(tmp_path) is True
    assert (owner.last(tmp_path) or {})["pid"] == first.pid
    # The next acquire needs no cleanup and no pid heuristics.
    with EngineLock.acquire(tmp_path, "scan") as lock:
        assert owner.stale(tmp_path) is False
        assert (owner.holder(tmp_path) or {})["pid"] == os.getpid()
        assert lock.held
    assert not (tmp_path / owner.LOCK_NAME).exists()  # a clean release removes the file
    assert owner.stale(tmp_path) is False and owner.last(tmp_path) is None


def test_a_holder_killed_with_sigkill_leaves_a_stale_lock_that_is_simply_taken(
    tmp_path: Path, standin_argv: Any, reaper: list[int]
) -> None:
    child = _hold(standin_argv(tmp_path), reaper)
    assert (owner.holder(tmp_path) or {})["pid"] == child.pid
    child.kill()
    child.wait(timeout=10)
    assert owner.holder(tmp_path) is None
    assert owner.stale(tmp_path) is True
    lock = EngineLock.acquire(tmp_path, "watch")
    assert owner.stale(tmp_path) is False
    lock.release()
    lock.release()  # twice is fine


def test_alive_holder_only_trusts_a_pid_whose_command_names_unbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = EngineLock.acquire(tmp_path, "watch")
    try:
        monkeypatch.setattr(owner, "_command_of", lambda pid: "/usr/bin/python3 something_else.py")
        assert owner.alive_holder(tmp_path) is None  # a reused pid is never signalled
        monkeypatch.setattr(owner, "_command_of", lambda pid: f"{sys.executable} -m unbidden.cli watch")
        assert (owner.alive_holder(tmp_path) or {})["pid"] == os.getpid()
    finally:
        lock.release()
    assert owner.alive_holder(tmp_path) is None


def test_the_real_ps_sees_this_process(tmp_path: Path) -> None:
    assert owner._command_of(os.getpid())  # pyright: ignore[reportPrivateUsage]
    assert owner._command_of(2**22 - 1) == ""  # pyright: ignore[reportPrivateUsage]


def test_the_lock_file_says_who_and_what(tmp_path: Path) -> None:
    with EngineLock.acquire(tmp_path, "try") as lock:
        info = owner.last(tmp_path)
        assert info is not None and info == lock.info
        assert info["pid"] == os.getpid() and info["command"] == "try" and info["host"] and info["version"]
        assert set(info) >= {"pid", "host", "started_at", "command", "version", "argv_hint"}
    assert owner.last(tmp_path) is None
