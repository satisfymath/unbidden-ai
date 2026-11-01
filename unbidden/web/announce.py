"""Where the project's dashboard is: `.unbidden/ui.json`, written by whoever serves it after the port is bound
(the standalone server with `--announce`, or the agent serving its own dashboard), removed when it exits.

`unbidden ui` reads it to reuse a dashboard that is alive instead of starting another: alive means the process
exists AND the server answers `/api/session` with the token in the file. A file whose server does not answer is
stale and removed. The token lives only in this file (mode 600) and in the server's memory: never in argv.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

FILENAME = "ui.json"


def ui_path(state_dir: Path) -> Path:
    return state_dir / FILENAME


def announce(path: Path, *, host: str, port: int, token: str, in_daemon: bool) -> dict[str, Any]:
    info = {
        "url": f"http://{host}:{port}/?s={token}",
        "host": host,
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "in_daemon": in_daemon,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(info, f, indent=2)
    os.replace(tmp, path)
    return info


def withdraw(path: Path) -> None:
    """Remove the announcement if it is still ours (another server may have announced after we lost the file)."""
    info = read(path)
    if info is not None and info.get("pid") == os.getpid():
        path.unlink(missing_ok=True)


def read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def answers(info: dict[str, Any], timeout: float = 2.0) -> bool:
    """Whether the announced server answers with the announced token (the token never leaves this machine)."""
    import httpx

    try:
        response = httpx.get(
            f"http://{info['host']}:{info['port']}/api/session",
            headers={"Authorization": f"Bearer {info['token']}"},
            timeout=timeout,
        )
    except (httpx.HTTPError, KeyError):
        return False
    return response.status_code == 200


def alive(path: Path) -> dict[str, Any] | None:
    """The announcement when its process exists and its server answers; otherwise the stale file is removed."""
    info = read(path)
    if info is None:
        return None
    if isinstance(info.get("pid"), int) and process_exists(info["pid"]) and answers(info):
        return info
    path.unlink(missing_ok=True)
    return None


def public(info: dict[str, Any]) -> dict[str, Any]:
    """What a command prints: everything but the token (the URL carries it, by design, for the person's browser)."""
    return {k: v for k, v in info.items() if k != "token"}


def is_our_web_process(pid: int) -> bool:
    """Before signalling a pid from a file: it must still be an `unbidden.web` process (a reused pid is not)."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return "unbidden.web" in out.stdout or ("unbidden" in out.stdout and "--announce" in out.stdout)


def stop(path: Path, *, timeout_s: float = 8.0) -> dict[str, Any]:
    """Stop the standalone dashboard announced here. The agent's own dashboard is not stopped from here: its
    lifetime is the agent's (`unbidden stop`). Nothing else is ever signalled."""
    info = alive(path)
    if info is None:
        return {"stopped": False, "reason": "the dashboard is not running"}
    if info.get("in_daemon"):
        return {
            "stopped": False,
            "reason": f"the dashboard is served by the agent (pid {info['pid']}); `unbidden stop` stops both; "
            "closing the tab stops nothing",
            "pid": info["pid"],
        }
    pid = int(info["pid"])
    if not is_our_web_process(pid):
        path.unlink(missing_ok=True)
        return {"stopped": False, "reason": f"pid {pid} is not an unbidden.web process any more; stale file removed"}
    os.kill(pid, signal.SIGTERM)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if not process_exists(pid):
            path.unlink(missing_ok=True)
            return {"stopped": True, "pid": pid}
        time.sleep(0.1)
    return {"stopped": False, "reason": f"pid {pid} did not exit within {timeout_s:g} s", "pid": pid}
