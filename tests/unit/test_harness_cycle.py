from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from bench.ecosystem.cycle import run_cycle

pytestmark = pytest.mark.unit


def test_a_cycle_past_its_bound_is_stopped_whole_and_keeps_what_it_printed(tmp_path: Path) -> None:
    # A parent with a child that outlives it, as `uv run` starts the daemon (stage 10, Prefect B-r14).
    log = run_cycle(["sh", "-c", "echo started; sleep 300 & echo child $!; wait"], tmp_path, dict(os.environ), 3, 1)
    assert log.startswith("== cycle 3 (did not finish within 1 s; its process group was stopped)")
    assert "started" in log
    child = int(next(line for line in log.splitlines() if line.startswith("child")).split()[1])
    # On Linux the orphaned child is reparented and reaped a moment after the group is killed (GitHub's runner);
    # macOS raises at once. Gone within two seconds either way.
    deadline = time.monotonic() + 2
    while True:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        assert time.monotonic() < deadline, f"child {child} still alive after the group was stopped"
        time.sleep(0.05)


def test_a_cycle_that_finishes_gives_its_exit_and_output(tmp_path: Path) -> None:
    assert run_cycle(["sh", "-c", "echo done"], tmp_path, dict(os.environ), 1, 30) == "== cycle 1 (exit 0)\ndone\n"
