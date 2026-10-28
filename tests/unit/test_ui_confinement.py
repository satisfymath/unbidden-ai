"""The page capture reaches the project's published page and nothing else, and its screenshots do not pile up.

Shown for real once (a local page asking for example.com: the page loaded through the relay, every request to
another host failed, no container or network was left); these tests pin the arguments that make it so.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from unbidden.lab import ui

pytestmark = pytest.mark.unit


def test_the_browser_runs_on_an_internal_network_read_only_and_not_as_root(tmp_path: Path) -> None:
    argv = ui.capture_argv("unbidden-int-ui-x", 8080, "/shop", tmp_path, 3000)
    assert argv[argv.index("--network") + 1] == "unbidden-int-ui-x"
    assert "--add-host" not in argv  # F5: no route to the host's gateway, nor the internet behind it
    assert {"--read-only", "--cap-drop", "--pids-limit"} <= set(argv)
    assert argv[argv.index("--user") + 1] == "1001:1001"
    assert "http://app:8080/shop" in argv


def test_the_relay_reaches_the_published_port_only() -> None:
    argv = ui.forwarder_argv("unbidden-ui-relay-x", 8080)
    assert argv[-2:] == ["/cap/ui_forward.py", "8080"]
    assert {"--read-only", "--cap-drop"} <= set(argv)


def test_only_a_page_published_on_this_machine_is_captured(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="published on this machine"):
        ui.capture("https://example.com/", tmp_path)


def test_anomaly_captures_are_removed_after_the_mandates_retention(tmp_path: Path) -> None:
    now = time.time()
    old, recent = tmp_path / f"anomaly-{int(now - 20 * 86400)}", tmp_path / f"anomaly-{int(now - 86400)}"
    for d in (old, recent, tmp_path / "reference"):
        d.mkdir()
        (d / "screenshot.png").write_bytes(b"png")
    assert ui.prune(tmp_path, 14, now=now) == [old.name]
    assert sorted(os.listdir(tmp_path)) == sorted([recent.name, "reference"])
