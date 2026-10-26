"""Run a fixed command in a throwaway container with no network, a read-only root and hard limits."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.guardian.scanner import scan_many, secret_hits

OUTPUT_CAP = 2_000_000  # bytes kept per stream; tools like prettier report on stderr, so both are kept


class SandboxError(RuntimeError):
    pass


INTERNAL_PREFIX = "unbidden-net-"


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    argv: list[str]
    # "none", or an internal Docker network created by unbidden (containers on it reach each other, never the
    # internet). Anything else is refused.
    network: str = "none"
    cpus: float = 2.0
    memory: str = "2g"
    pids: int = 512
    timeout_s: float = 600.0
    env: dict[str, str] = field(default_factory=dict[str, str])
    # Values read from files tracked in the repository (already public there), e.g. a compose service's
    # environment interpolated from the tracked .env. Not scanned for secrets; everything else in env is.
    public_env: dict[str, str] = field(default_factory=dict[str, str])
    workdir: str = "/work"


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    stdout_truncated: bool
    stderr_truncated: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def _cap(data: bytes) -> tuple[str, bool]:
    return data[:OUTPUT_CAP].decode(errors="replace"), len(data) > OUTPUT_CAP


def docker_argv(spec: SandboxSpec, work: Path, name: str) -> list[str]:
    if spec.network != "none" and not spec.network.startswith(INTERNAL_PREFIX):
        raise SandboxError(f"sandbox network must be none or an unbidden internal network, not {spec.network!r}")
    argv = [
        "docker", "run", "--rm", "--name", name,
        "--network", spec.network,
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "1000:1000",
        "--cpus", str(spec.cpus),
        "--memory", spec.memory, "--memory-swap", spec.memory,
        "--pids-limit", str(spec.pids),
        "-v", f"{work}:{spec.workdir}:rw",
        "-w", spec.workdir,
        "-e", "HOME=/tmp", "-e", "CI=1",
    ]  # fmt: skip
    for key, value in sorted({**spec.public_env, **spec.env}.items()):
        argv += ["-e", f"{key}={value}"]
    return [*argv, spec.image, *spec.argv]


class SandboxRunner:
    def __init__(self, docker: str = "docker") -> None:
        self.docker = docker

    def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
        if secret_hits(scan_many([*spec.argv, *(f"{k}={v}" for k, v in spec.env.items())])):
            raise SandboxError("refusing to pass a secret into the sandbox")
        if spec.network != "none":
            inspect = subprocess.run(
                [self.docker, "network", "inspect", "-f", "{{.Internal}}", spec.network],
                capture_output=True, text=True, check=False,
            )  # fmt: skip
            if inspect.stdout.strip() != "true":
                raise SandboxError(f"network {spec.network} is not internal; refusing to run")
        name = f"unbidden-{uuid.uuid4().hex[:12]}"
        argv = docker_argv(spec, work, name)
        argv[0] = self.docker
        started = time.monotonic()
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = proc.communicate(timeout=spec.timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            subprocess.run([self.docker, "kill", name], capture_output=True, check=False)
            out, err = proc.communicate()
            timed_out = True
        stdout, out_cut = _cap(out)
        stderr, err_cut = _cap(err)
        return SandboxResult(
            exit_code=None if timed_out else proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_s=time.monotonic() - started,
            stdout_truncated=out_cut,
            stderr_truncated=err_cut,
        )


def snapshot(repo: Path, rev: str, dest: Path | None = None) -> Path:
    """Copy the tracked files of `rev` into a fresh directory.

    Only tracked files: an untracked `.env` or local credential file never reaches a sandbox.
    """
    target = dest or Path(tempfile.mkdtemp(prefix="unbidden-work-"))
    target.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", rev], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
    target.chmod(0o777)  # the container runs as uid 1000
    for path in target.rglob("*"):
        if path.is_symlink():  # tracked symlinks may point anywhere, even nowhere; never follow them
            continue
        if path.is_dir():
            path.chmod(0o777)
        else:
            path.chmod(0o666 | (path.stat().st_mode & 0o111))
    return target


def discard(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)
