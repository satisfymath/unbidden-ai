"""`unbidden update` and `unbidden uninstall`: the installer, run from inside the installed tool.

The one source of truth is `install.sh` at the repository root; the same file ships here as package data and a test
keeps the two identical. `update` runs it (download, sha256, `uv tool install --reinstall`); `uninstall` runs
`uv tool uninstall unbidden-ai` and never touches data unless asked twice (`--purge --yes`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from unbidden import __version__

NAME = "unbidden-ai"
INSTALL_SH = Path(__file__).parent / "install.sh"


def _emit(args: argparse.Namespace, data: Any) -> bool:
    """Same contract as cli._emit (imported here rather than from cli to keep cli's import graph out of this path)."""
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))
        return True
    return False


def find_uv() -> str | None:
    """uv on PATH, or where its installer puts it."""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (os.environ.get("UV_INSTALL_DIR"), Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        if candidate and (Path(candidate) / "uv").is_file() and os.access(Path(candidate) / "uv", os.X_OK):
            return str(Path(candidate) / "uv")
    return None


def data_paths(cwd: Path | None = None) -> list[Path]:
    """What an uninstall keeps and only --purge removes: the machine-wide home and this repository's .unbidden/."""
    home = Path(os.environ.get("UNBIDDEN_HOME") or Path.home() / ".unbidden")
    paths = [home]
    local = (cwd or Path.cwd()) / ".unbidden"
    if local.is_dir() and local.resolve() != home.resolve():
        paths.append(local)
    return paths


def run_installer(
    version: str | None,
    *,
    base: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    """install.sh --yes [--version X], with the environment it documents; output captured for the caller."""
    argv = ["sh", str(INSTALL_SH), "--yes"]
    if version:
        argv += ["--version", version]
    env = dict(os.environ)
    if base:
        env["UNBIDDEN_INSTALL_BASE"] = base
    return runner(argv, env=env, capture_output=True, text=True, check=False)


def installed_version(output: str) -> str | None:
    """The version the installer reports on its last lines: 'unbidden-ai X.Y.Z installed: <path>'."""
    for line in reversed(output.splitlines()):
        if line.startswith(f"{NAME} ") and " installed: " in line:
            return line.split()[1]
    return None


def cmd_update(args: argparse.Namespace) -> int:
    """Install the requested version (default: the latest published release) over this one; data is untouched."""
    version = getattr(args, "version", None)
    base = getattr(args, "base", None) or os.environ.get("UNBIDDEN_INSTALL_BASE")
    if not INSTALL_SH.is_file():
        data = {"ok": False, "error": f"installer not found at {INSTALL_SH}"}
        if not _emit(args, data):
            print(f"unbidden update: {data['error']}", file=sys.stderr)
        return 2
    if find_uv() is None:
        data = {"ok": False, "error": "uv is not installed; unbidden was not installed with install.sh here"}
        if not _emit(args, data):
            print(f"unbidden update: {data['error']}", file=sys.stderr)
        return 2
    result = run_installer(version, base=base)
    log = (result.stderr or "") + (result.stdout or "")
    new = installed_version(log)
    data = {
        "ok": result.returncode == 0,
        "from": __version__,
        "requested": version or "latest",
        "installed": new,
        "exit_code": result.returncode,
        "log": log.strip().splitlines()[-12:],
    }
    if _emit(args, data):
        return 0 if result.returncode == 0 else 1
    if result.returncode == 0:
        print(f"unbidden {__version__} -> {new or version or 'latest'}: updated.")
        for line in data["log"][-4:]:
            print(f"  {line}")
    else:
        print(
            f"unbidden update failed (exit {result.returncode}); nothing changed. The installer said:", file=sys.stderr
        )
        for line in data["log"]:
            print(f"  {line}", file=sys.stderr)
        print("  Rollback to a known version: unbidden update --version <X.Y.Z>", file=sys.stderr)
    return 0 if result.returncode == 0 else 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Show what `uv tool uninstall unbidden-ai` would remove and what stays; do it only with --yes.

    --purge adds the data paths to the removal; it refuses without --yes and lists them first.
    """
    yes = bool(getattr(args, "yes", False))
    purge = bool(getattr(args, "purge", False))
    uv = find_uv()
    kept = data_paths()
    plan: dict[str, Any] = {
        "command": [uv or "uv", "tool", "uninstall", NAME],
        "removes_data": [str(p) for p in kept] if purge else [],
        "keeps": [] if purge else [str(p) for p in kept] + [".unbidden/ in every other repository"],
        "done": False,
    }
    if purge and not yes:
        plan["error"] = "--purge deletes the paths above; add --yes to confirm"
        if not _emit(args, plan):
            print("unbidden uninstall --purge would delete:", file=sys.stderr)
            for p in kept:
                print(f"  {p}", file=sys.stderr)
            print(f"  {plan['error']}", file=sys.stderr)
        return 2
    if not yes:
        if not _emit(args, plan):
            print("Would run: " + " ".join(plan["command"]))
            print("Kept (data): " + ", ".join(plan["keeps"]))
            print("Add --yes to do it; --purge --yes also deletes the data.")
        return 0
    if uv is None:
        plan["error"] = "uv is not installed; remove the `unbidden` entry point by hand"
        if not _emit(args, plan):
            print(f"unbidden uninstall: {plan['error']}", file=sys.stderr)
        return 2
    result = subprocess.run([uv, "tool", "uninstall", NAME], capture_output=True, text=True, check=False)
    plan["done"] = result.returncode == 0
    plan["uv_said"] = (result.stderr or result.stdout or "").strip()
    if purge and result.returncode == 0:
        for p in kept:
            shutil.rmtree(p, ignore_errors=True)
    if _emit(args, plan):
        return 0 if result.returncode == 0 else 1
    if result.returncode == 0:
        print(f"{NAME} removed.")
        if purge:
            print("Deleted: " + ", ".join(str(p) for p in kept))
        else:
            print("Kept: " + ", ".join(plan["keeps"]))
    else:
        print(f"uv tool uninstall failed: {plan['uv_said']}", file=sys.stderr)
    return 0 if result.returncode == 0 else 1


def register(command: Callable[..., argparse.ArgumentParser]) -> None:
    """Wire both commands given cli.build_parser's local `command(name, handler, help_text, *, json_out)`."""
    update = command("update", cmd_update, "install a newer (or an older, with --version) release over this one")
    update.add_argument("--version", help="the release to install, e.g. 0.9.0 (default: the latest published)")
    update.add_argument("--base", help=argparse.SUPPRESS)  # UNBIDDEN_INSTALL_BASE for tests and mirrors
    uninstall = command("uninstall", cmd_uninstall, "remove the unbidden tool; ~/.unbidden and .unbidden/ stay")
    uninstall.add_argument("--yes", action="store_true", help="do it, instead of showing what would happen")
    uninstall.add_argument("--purge", action="store_true", help="also delete the data paths (needs --yes)")


# To wire these in cli.build_parser (cli.py is owned elsewhere), add after the `command` helper is defined:
#
#     from unbidden.distribution import register as register_distribution
#     register_distribution(command)
#
# or, spelled out as the two command lines plus their arguments:
#
#     update_ = command("update", cmd_update, "install a newer (or an older, with --version) release over this one")
#     command("uninstall", cmd_uninstall, "remove the unbidden tool; ~/.unbidden and .unbidden/ stay")
