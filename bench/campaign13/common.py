"""Shared pieces of the campaign harness: the campaign HOME with the installed tool, bounded commands, records, the
ledger, and sanitizing (no token, no key value ever reaches a record)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
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
        PATH=f"{HOME / 'bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    )
    return e


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
