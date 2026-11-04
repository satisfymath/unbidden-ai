"""Shared pieces of the campaign harness: the campaign HOME with the installed tool, bounded commands, records, the
ledger, and sanitizing (no token, no key value ever reaches a record)."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LAB = Path.home() / "unbidden-lab" / "c13"  # every campaign resource lives under here (INVENTORY.md)
HOME = LAB / "home"  # the campaign HOME: the installed tool, its credentials file, the dashboard's state
REAL_HOME = Path(os.environ.get("C12_REAL_HOME", str(Path.home())))
LEDGER_HOME = REAL_HOME / ".unbidden"  # the machine's ledger: every paid call counts in the real budget
TOKEN_RE = re.compile(r"(\?s=|Bearer )[A-Za-z0-9_\-]+")


def scrub(text: str) -> str:
    """Dashboard session tokens out of anything kept; key values never appear because they travel by broker."""
    return TOKEN_RE.sub(r"\1<token>", text)


def env(envelope: str, run: str) -> dict[str, str]:
    """The environment of every product command: the campaign HOME, the real ledger, the envelope and run tag, the
    real Docker config (an empty HOME has no CLI plugins). PATH keeps /usr/sbin for sysctl."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("UNBIDDEN_")}
    e.update(
        HOME=str(HOME),
        UV_TOOL_DIR=str(HOME / "tools"),
        UV_TOOL_BIN_DIR=str(HOME / "bin"),
        UNBIDDEN_HOME=str(LEDGER_HOME),
        UNBIDDEN_ENVELOPE=envelope,
        UNBIDDEN_RUN=run,
        DOCKER_CONFIG=str(REAL_HOME / ".docker"),
        PATH=host_path(),
    )
    return e


SYSTEM_PATH = ["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
OPTIONAL_PATH = ["/opt/homebrew/bin", "/home/linuxbrew/.linuxbrew/bin"]  # kept only where they exist


def host_path() -> str:
    """The campaign HOME's bin first, then the directories of the host's own tools (wherever `uv`, `gh`, `docker`,
    `act`, `node` live here), then the system's. No directory is assumed to exist (macOS Homebrew, Linux, ...)."""
    found = [str(Path(w).parent) for t in TOOLS if (w := shutil.which(t))]
    extra = [d for d in OPTIONAL_PATH if Path(d).is_dir()]
    parts = [str(HOME / "bin"), *found, *extra, *SYSTEM_PATH]
    return ":".join(dict.fromkeys(parts))


TOOLS = ("uv", "gh", "docker", "act", "node", "git")


def tool_versions(which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    """Each host tool the harness uses: its path and its version line, or None when it is not installed."""
    out: dict[str, Any] = {}
    for tool in TOOLS:
        path = which(tool)
        version = None
        if path:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30, check=False)
                version = (done.stdout or done.stderr).strip().splitlines()[0] if (done.stdout or done.stderr) else None
        out[tool] = {"path": path, "version": version}
    return out


def host_header() -> dict[str, Any]:
    return {
        "host": platform.node(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "tools": tool_versions(),
        "path": host_path(),
    }


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """An exclusive lock beside `path` (fcntl, released when the block ends, or when the process dies)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_summary(path: Path, line: dict[str, Any], keys: tuple[str, ...] = ("name",)) -> list[dict[str, Any]]:
    """Read-modify-write of a summary file under its lock: the line replaces any with the same keys. Written to a
    temporary file and renamed, so a reader never sees half a file. Safe across processes."""
    with locked(path):
        summary: list[dict[str, Any]] = json.loads(path.read_text()) if path.exists() else []
        summary = [s for s in summary if any(s.get(k) != line.get(k) for k in keys)] + [line]
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(summary, indent=1, default=str))
        tmp.replace(path)
        return summary


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def envelope_for(phase: str) -> str:
    """The envelope a phase spends from (docs/bench/campaign13/PROTOCOL.md §2): dev (each work stream's bounded
    runs), pass (the intermediate pass), final (the frozen final pass) or confirm (repetitions from clean)."""
    for name in ("pass", "final", "confirm"):
        if phase.startswith(name):
            return f"s13-{name}"
    return "s13-dev"


def candidate_of(corpus: dict[str, Any], key: str) -> tuple[str, str]:
    """The (commit, wheel sha256) pair a run records: the frozen candidate, or a named one (`confirm`: phase 7)."""
    if not key:
        return corpus["candidate"], corpus["wheel_sha256"]
    return corpus[f"{key}_candidate"], corpus[f"{key}_wheel_sha256"]


def unbidden() -> str:
    return str(HOME / "bin" / "unbidden")


@dataclass
class Step:
    name: str
    argv: list[str]
    code: int
    seconds: float
    stdout: str
    stderr: str
    timed_out: bool = False

    def json(self) -> Any:
        try:
            return json.loads(self.stdout) if self.stdout.strip().startswith(("{", "[")) else None
        except ValueError:
            return None

    def record(self, keep: int = 4000) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": [scrub(a) for a in self.argv],
            "code": self.code,
            "seconds": self.seconds,
            "timed_out": self.timed_out,
            "stdout": scrub(self.stdout[-keep:]),
            "stderr": scrub(self.stderr[-keep:]),
        }


def run(
    name: str, argv: list[str], *, cwd: Path, env_: dict[str, str], timeout_s: float, stdin: str | None = None
) -> Step:
    started = time.monotonic()
    try:
        out = subprocess.run(
            argv, cwd=cwd, env=env_, capture_output=True, text=True, timeout=timeout_s, input=stdin, check=False
        )
        return Step(name, argv, out.returncode, round(time.monotonic() - started, 1), out.stdout, out.stderr)
    except subprocess.TimeoutExpired as exc:
        out_s = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err_s = (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return Step(name, argv, -1, round(time.monotonic() - started, 1), str(out_s), str(err_s), timed_out=True)


def run_spend(run_tag: str, envelope: str = "s13-dev") -> dict[str, Any]:
    """What THIS run's calls cost, by its run tag in the ledger: envelope deltas mix concurrent runs."""
    step = run("spend", [unbidden(), "spend", "--json"], cwd=Path.home(), env_=env(envelope, "ledger"), timeout_s=60)
    data = step.json() or {}
    row = (data.get("by_run") or {}).get(run_tag) or {}
    return {
        "run": run_tag,
        "calls": row.get("calls", 0),
        "usd": round(row.get("usd", 0.0), 4),
        "tokens_in": row.get("tokens_in", 0),
        "tokens_out": row.get("tokens_out", 0),
    }


def ledger(envelope: str) -> dict[str, Any]:
    """What the ledger says now for one envelope (spent) and the machine (available); read with the installed tool."""
    step = run("spend", [unbidden(), "spend", "--json"], cwd=Path.home(), env_=env(envelope, "ledger"), timeout_s=60)
    data = step.json() or {}
    envelopes = data.get("envelopes", {})
    return {
        "envelope": envelope,
        "envelope_spent_usd": (envelopes.get(envelope) or {}).get("spent_usd"),
        "available_usd": data.get("available_usd"),
        "permitted_usd": data.get("permitted_usd"),
    }


@dataclass
class Record:
    """One run's record, written as JSON (sanitized) with every step, and a few derived fields."""

    repo: str
    phase: str
    run: str
    candidate: str
    wheel_sha256: str
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    steps: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    human: list[dict[str, Any]] = field(default_factory=list)  # {step, minutes, why}: preparation, counted
    blocks: list[str] = field(default_factory=list)

    def add(self, step: Step) -> Step:
        self.steps.append(step.record())
        return step

    def write(self, out: Path) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.__dict__, indent=1, default=str, ensure_ascii=False))
        return out


def install(wheel_dir: Path, version: str, *, port: int = 8790) -> dict[str, Any]:
    """Install the frozen wheel into the campaign HOME from a local server (there is no public release); idempotent.
    Returns the installer's record. The server is started here and stopped after."""
    HOME.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=wheel_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1)
        e = env("s13-dev", "install") | {"UNBIDDEN_INSTALL_BASE": f"http://127.0.0.1:{port}"}
        installer = Path(__file__).resolve().parents[2] / "install.sh"
        step = run("install", ["sh", str(installer), "--yes", "--version", version], cwd=HOME, env_=e, timeout_s=900)
        version_step = run("version", [unbidden(), "--version"], cwd=HOME, env_=e, timeout_s=60)
        return {"install": step.record(), "version": version_step.stdout.strip(), "ok": step.code == 0}
    finally:
        server.terminate()
        server.wait(timeout=10)


def hold_key(name: str, value: str) -> None:
    """Write one credential into the campaign HOME's .env through the product's own path (setup credentials reads the
    value on stdin): the value never appears in argv or in a record."""
    raise NotImplementedError("use `unbidden setup credentials --credential NAME` with the value on stdin from a repo")
