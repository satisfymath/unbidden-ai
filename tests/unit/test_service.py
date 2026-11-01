"""`unbidden start` / `stop` / `status` behind the CLI (unbidden/daemon/service.py).

The fast tests spawn a stand-in agent (tests/conftest.py STANDIN_AGENT) through `service.start(command=...)`: a real
`unbidden watch` imports the whole engine and runs its first cycle, which is not something to do in a unit test on
every machine. One slow test runs the real `watch`.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from unbidden.cli import main
from unbidden.contracts.jobs import JobStatus
from unbidden.daemon import owner, service
from unbidden.daemon.cycle import job
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    return Workspace(tmp_path)


def _processes_named(marker: str) -> list[str]:
    out = subprocess.run(["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True, check=False).stdout
    return [line for line in out.splitlines() if marker in line and "ps -ax" not in line]


def test_start_twice_runs_one_agent_and_stop_ends_it_without_freezing(
    ws: Workspace, standin_argv: Any, reaper: list[int]
) -> None:
    before = service.status(ws)
    assert before["running"] is False and before["stale"] is False and before["jobs_running"] == 0
    first = service.start(ws, command=standin_argv(ws.dir))
    assert first["started"] is True, first
    reaper.append(first["pid"])
    assert first["log"] == str(ws.dir / "logs" / "agent.log")
    second = service.start(ws, command=standin_argv(ws.dir))
    assert second["started"] is False and second["already"]["pid"] == first["pid"]
    assert (owner.holder(ws.dir) or {})["pid"] == first["pid"]
    assert len(_processes_named(str(ws.dir))) == 1  # exactly one agent over this workspace
    assert (owner.alive_holder(ws.dir) or {})["pid"] == first["pid"]  # `ps` names unbidden in its command
    status = service.status(ws)
    assert status["running"] is True and status["pid"] == first["pid"] and status["command"] == "watch"
    assert status["started_at"] and status["stale"] is False

    stopped = service.stop(ws, timeout_s=10)
    assert stopped["stopped"] is True and stopped["pid"] == first["pid"] and stopped["forced"] is False
    assert stopped["jobs_left_running"] == 0
    assert owner.holder(ws.dir) is None
    assert owner.stale(ws.dir) is False  # a clean stop removes the file: nothing to recover
    assert not (ws.dir / "KILL").exists()  # stop never freezes
    assert _processes_named(str(ws.dir)) == []
    assert (ws.dir / "logs" / "agent.log").read_text().strip() == "held"
    again = service.stop(ws)
    assert again == {"stopped": False, "reason": "not running", "jobs_running": 0}


def test_stop_reports_jobs_left_running_and_the_next_start_requeues_them(
    ws: Workspace, standin_argv: Any, reaper: list[int]
) -> None:
    store = ws.store()
    store.enqueue(job("observe.head", "x"))
    claimed = store.claim()
    assert claimed is not None and claimed.status is JobStatus.RUNNING
    store.close()
    started = service.start(ws, command=standin_argv(ws.dir))
    assert started["started"] is True
    reaper.append(started["pid"])
    assert service.status(ws)["jobs_running"] == 1
    stopped = service.stop(ws, timeout_s=10)
    assert stopped["stopped"] is True and stopped["jobs_left_running"] == 1
    store = ws.store()
    assert store.requeue_running() == 1  # what `watch` does first on the next start
    assert [j.status for j in store.jobs()] == [JobStatus.QUEUED]
    store.close()


def test_a_child_that_dies_early_is_reported_with_its_log(ws: Workspace) -> None:
    result = service.start(ws, command=[sys.executable, "-c", "print('no mandate here'); raise SystemExit(3)"])
    assert result["started"] is False and result["exit"] == 3 and result["log_tail"] == ["no mandate here"]
    assert owner.holder(ws.dir) is None and owner.stale(ws.dir) is False


def test_a_forced_stop_is_said(ws: Workspace, reaper: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    deaf = (
        "import signal, sys, time\nfrom pathlib import Path\nfrom unbidden.daemon.owner import EngineLock\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\nlock = EngineLock.acquire(Path(sys.argv[1]), 'watch')\n"
        "print('held', flush=True)\ntime.sleep(120)\n"
    )
    started = service.start(ws, command=[sys.executable, "-c", deaf, str(ws.dir)])
    assert started["started"] is True
    reaper.append(started["pid"])
    stopped = service.stop(ws, timeout_s=0.5)
    assert stopped["stopped"] is True and stopped["forced"] is True and stopped["timeout_s"] == 0.5
    assert owner.holder(ws.dir) is None
    assert owner.stale(ws.dir) is True  # killed, so the file stayed: status says the run ended without `stop`
    status = service.status(ws)
    assert status["running"] is False and status["stale"] is True and status["pid"] == started["pid"]


def test_a_stale_lock_is_said_by_stop_and_status(ws: Workspace, standin_argv: Any, reaper: list[int]) -> None:
    child = subprocess.Popen(
        standin_argv(ws.dir, "exit-dirty"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    reaper.append(child.pid)
    assert child.stdout is not None and child.stdout.readline().strip() == "held"
    assert child.stdin is not None
    child.stdin.write("\n")
    child.stdin.close()
    child.wait(timeout=10)
    result = service.stop(ws)
    assert result["stopped"] is False and result["stale"] is True and result["last"]["pid"] == child.pid
    assert service.status(ws)["stale"] is True


def test_the_log_rotates_by_rename_past_the_limit(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    log = ws.dir / "logs" / "agent.log"
    log.parent.mkdir()
    log.write_text("old\n")
    monkeypatch.setattr(service, "LOG_MAX_BYTES", 2)
    result = service.start(ws, command=[sys.executable, "-c", "print('new'); raise SystemExit(1)"])
    assert result["started"] is False
    assert (ws.dir / "logs" / "agent.log.1").read_text() == "old\n" and log.read_text() == "new\n"


@pytest.mark.slow
def test_the_real_watch_starts_in_the_background_and_stops_cleanly(ws: Workspace, reaper: list[int]) -> None:
    """A real `unbidden watch --interval 3600` child: imports the engine, takes the lock before opening the runtime,
    runs its first cycle in an empty repository, and ends on SIGTERM; no Ollama or Docker is required to start."""
    subprocess.run(["git", "-C", str(ws.repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]})  # fmt: skip
    started = service.start(ws, interval_s=3600, wait_s=30)
    assert started["started"] is True, started
    reaper.append(started["pid"])
    assert (owner.alive_holder(ws.dir) or {})["command"] == "watch"
    log = ws.dir / "logs" / "agent.log"
    deadline = time.monotonic() + 60
    while "watching" not in log.read_text() and time.monotonic() < deadline:
        time.sleep(0.2)  # the runtime is open and the first cycle runs: the stop below interrupts real work
    stopped = service.stop(ws, timeout_s=90)
    assert stopped["stopped"] is True and stopped["forced"] is False
    assert owner.holder(ws.dir) is None and owner.stale(ws.dir) is False
    assert not (ws.dir / "KILL").exists()
    text = (ws.dir / "logs" / "agent.log").read_text()
    assert "watching" in text and "stopped" in text
