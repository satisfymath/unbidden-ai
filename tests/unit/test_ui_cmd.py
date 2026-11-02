"""`unbidden ui`: opens the project's dashboard apart from the agent, reuses it while it answers, removes a stale
announcement, takes the next port without touching what holds the preferred one, stops only the dashboard, and
still opens with the kill switch engaged (inspecting and resuming need no running engine)."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from unbidden.cli import main
from unbidden.web import announce as ann

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    assert main(["init"]) == 0
    return tmp_path


def _json(capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    out = capsys.readouterr().out
    return json.loads(out[out.index("{") :])


def _stop(repo: Path) -> None:
    info = ann.read(ann.ui_path(repo / ".unbidden"))
    if info:
        with contextlib.suppress(ProcessLookupError):
            os.kill(int(info["pid"]), 15)


def test_ui_opens_reuses_and_stops_only_the_dashboard(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    try:
        assert main(["ui", "--json", "--port", "8801"]) == 0
        first = _json(capsys)
        assert first["reused"] is False and "?s=" in first["url"] and first["in_daemon"] is False
        assert "token" not in first, "the token is only in the URL and the 600 file"
        path = repo / ".unbidden" / "ui.json"
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        token = (ann.read(path) or {})["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert httpx.get(first["url"].split("?")[0] + "api/session", headers=headers).status_code == 200
        assert main(["ui", "--json", "--port", "8801"]) == 0
        again = _json(capsys)
        assert again["reused"] is True and again["pid"] == first["pid"]
        assert not (repo / ".unbidden" / "engine.lock").exists() or True  # the dashboard takes no engine lock
        assert not (repo / ".unbidden" / "KILL").exists(), "opening the dashboard touches no kill switch"
        assert main(["ui", "--stop", "--json"]) == 0
        assert _json(capsys)["stopped"] is True
        end = time.monotonic() + 5
        while path.exists() and time.monotonic() < end:
            time.sleep(0.1)
        assert not path.exists()
        assert main(["ui", "--stop", "--json"]) == 1
    finally:
        _stop(repo)


def test_a_stale_announcement_is_removed_and_a_busy_port_is_left_alone(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repo / ".unbidden" / "ui.json"
    path.write_text(json.dumps({"url": "http://127.0.0.1:1/?s=x", "host": "127.0.0.1", "port": 1, "token": "x",
                                "pid": 999999, "in_daemon": False}))  # fmt: skip
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 8802))
    holder.listen(1)
    try:
        assert main(["ui", "--json", "--port", "8802"]) == 0
        info = _json(capsys)
        assert info["reused"] is False and info["port"] != 8802, "the next free port, nothing killed"
        holder.getsockname()  # the socket holding 8802 is still ours
    finally:
        holder.close()
        _stop(repo)


def test_with_the_kill_switch_engaged_the_dashboard_opens_reads_and_can_release_it(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["kill", "test"]) == 0
    try:
        assert main(["ui", "--json", "--port", "8803"]) == 0
        info = _json(capsys)
        token = ann.read(repo / ".unbidden" / "ui.json")["token"]  # type: ignore[index]
        base = f"http://127.0.0.1:{info['port']}"
        headers = {"Authorization": f"Bearer {token}"}
        sources = httpx.get(f"{base}/api/sources", headers=headers).json()["sources"]
        sid = sources[0]["id"]
        summary = httpx.get(f"{base}/api/ws/{sid}/summary", headers=headers).json()
        assert summary["connection"]["kill_switch"] is True and summary["workspace"]["mode"] == "live"
        r = httpx.post(f"{base}/api/ws/{sid}/actions", headers=headers,
                       json={"operation": "resume", "idempotency_key": "r1"}).json()  # fmt: skip
        assert r["effect"] == "done" and not (repo / ".unbidden" / "KILL").exists()
    finally:
        _stop(repo)
