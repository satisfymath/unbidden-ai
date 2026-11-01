"""One `unbidden watch --once` cycle for the harnesses, bounded in time.

`subprocess.run(timeout=...)` kills only the process it started: `uv run`, not the daemon under it. Stage 10's
Prefect B-r14 kept every timed-out daemon alive, so the next cycle ran beside it on the same store, and after the
workspace was archived one of them wrote a new one, which stopped A-r14 from starting. The cycle runs in its own
process group, the whole group is stopped at the bound, and what it printed until then is kept.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from pathlib import Path

CYCLE_TIMEOUT_S = 5400


def run_cycle(argv: list[str], cwd: Path, env: dict[str, str], cycle: int, timeout_s: float = CYCLE_TIMEOUT_S) -> str:
    """The cycle's log entry: its exit and output, or that it did not finish in time, with what it printed."""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)  # fmt: skip
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        return f"== cycle {cycle} (exit {proc.returncode})\n{out}"
    except subprocess.TimeoutExpired:
        _stop(proc)
        out, _ = proc.communicate()
        return f"== cycle {cycle} (did not finish within {timeout_s:.0f} s; its process group was stopped)\n{out}"


def _stop(proc: subprocess.Popen[str]) -> None:
    """SIGINT first, as a person's ctrl-c (the daemon finishes its job's bookkeeping), then SIGKILL to the whole
    group in any case: a process of the group that ignores SIGINT would outlive the cycle and hold its output open."""
    try:
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=60)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
