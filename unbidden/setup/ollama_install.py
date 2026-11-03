"""Ollama on this machine, done by Unbidden when the person says so: the official installer on Linux (it asks for
sudo in the person's own terminal), Homebrew on macOS. Then the server is checked, not assumed."""

from __future__ import annotations

import platform
import shutil
import subprocess
import time
from collections.abc import Callable

import httpx

SITE = "https://ollama.com/download"
LINUX_INSTALL = "curl -fsSL https://ollama.com/install.sh | sh"

Terminal = Callable[[list[str]], int]


def installed() -> bool:
    return shutil.which("ollama") is not None


def serving(url: str, timeout_s: float = 3.0) -> bool:
    try:
        return httpx.get(url, timeout=timeout_s).status_code == 200
    except httpx.HTTPError:
        return False


def install_command() -> list[str] | None:
    """The command that installs Ollama here, or None when only the download page can (unknown system, no brew)."""
    system = platform.system()
    if system == "Linux":
        return ["sh", "-c", LINUX_INSTALL]
    if system == "Darwin" and shutil.which("brew"):
        return ["brew", "install", "ollama"]
    return None


def install(terminal: Terminal) -> bool:
    """Run the installer in the person's terminal. True when `ollama` is on PATH afterwards."""
    command = install_command()
    if command is None:
        return False
    return terminal(command) == 0 and installed()


def start_server(url: str, wait_s: float = 15.0) -> bool:
    """The Linux installer leaves a systemd service running; elsewhere the server is started detached. True when
    `url` answers within `wait_s`."""
    if serving(url):
        return True
    if platform.system() == "Darwin" and shutil.which("brew"):
        subprocess.run(["brew", "services", "start", "ollama"], check=False, capture_output=True)
    elif installed():
        subprocess.Popen(
            ["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if serving(url):
            return True
        time.sleep(0.5)
    return serving(url)
