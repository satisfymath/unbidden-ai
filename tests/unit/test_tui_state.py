"""The status bar's line drops fields from the right when the terminal is narrow, and the cheap read is cheap."""

from __future__ import annotations

from datetime import timedelta

import pytest

from unbidden.contracts.common import utc_now
from unbidden.tui.state import Bar, format_bar

pytestmark = pytest.mark.unit


def _bar() -> Bar:
    now = utc_now()
    return Bar(workspace="shop", agent_running=True, agent_pid=4242, jobs_running=1, jobs_queued=3, mode="supervised",
               profile="local-first", local_reachable=True, spend_available=0.4312, spend_verified=True,
               dashboard_url="http://127.0.0.1:8765", last_seq=10, last_event_at=now - timedelta(seconds=2),
               read_at=now)  # fmt: skip


def test_the_full_bar_names_everything() -> None:
    line = format_bar(_bar(), 200)
    for piece in ("○˙ shop", "● agent 4242", "1 running/3 queued", "supervised · local-first", "ollama ✓",
                  "US$0.4312 available", "http://127.0.0.1:8765", "2 s ago"):  # fmt: skip
        assert piece in line, piece


def test_a_narrow_bar_keeps_the_mark_and_the_agent() -> None:
    line = format_bar(_bar(), 40)
    assert "○˙ shop" in line and "agent 4242" in line and "http://" not in line


def test_the_kill_switch_and_the_transient_come_first_and_last() -> None:
    bar = _bar()
    bar.kill = True
    bar.transient = "thinking…"
    line = format_bar(bar, 200)
    assert line.index("KILL SWITCH") < line.index("agent") and line.endswith("thinking…[/]")
