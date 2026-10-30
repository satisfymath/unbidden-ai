"""Throwaway data services (the repository's own database images) on an internal network for tests.

Each call gets a fresh network and fresh containers whose data lives in tmpfs, so both sides of an
experiment start from the same empty state and nothing persists.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from unbidden.observe.compose import Service
from unbidden.sandbox.runner import INTERNAL_PREFIX, SandboxError

DATA_DIRS = {"postgres": "/var/lib/postgresql", "mysql": "/var/lib/mysql", "mariadb": "/var/lib/mysql",
             "redis": "/data", "mongo": "/data/db"}  # fmt: skip
READY = {
    "postgres": ["pg_isready", "-q"],
    "mysql": ["mysqladmin", "ping", "-h", "127.0.0.1", "--silent"],
    "mariadb": ["mariadb-admin", "ping", "-h", "127.0.0.1", "--silent"],
    "redis": ["redis-cli", "ping"],
    "mongo": ["mongosh", "--quiet", "--eval", "db.adminCommand('ping')"],
}


@dataclass(frozen=True)
class Sidecars:
    network: str
    names: dict[str, str]  # service name -> container name


def _run(docker: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([docker, *args], capture_output=True, text=True, check=False)


@contextmanager
def data_services(
    services: list[Service], *, docker: str = "docker", ready_timeout_s: float = 90, statements: bool = False
) -> Iterator[Sidecars | None]:
    """`statements`: PostgreSQL also keeps per-statement statistics (pg_stat_statements), read by the lab to see
    what a measured request made the engine do."""
    if not services:
        yield None
        return
    run_id = uuid.uuid4().hex[:10]
    network = f"{INTERNAL_PREFIX}{run_id}"
    names: dict[str, str] = {}
    created = _run(docker, "network", "create", "--internal", network)
    if created.returncode != 0:
        raise SandboxError(f"could not create an internal network: {created.stderr.strip()}")
    try:
        for service in services:
            kind = service.data_kind or ""
            container = f"unbidden-data-{service.name}-{run_id}"
            argv = ["run", "-d", "--rm", "--name", container, "--network", network, "--network-alias", service.name,
                    "--tmpfs", f"{DATA_DIRS.get(kind, '/data')}:rw", "--memory", "1g"]  # fmt: skip
            for key, value in sorted(service.environment.items()):
                argv += ["-e", f"{key}={value}"]
            command = (["postgres", "-c", "shared_preload_libraries=pg_stat_statements", "-c",
                        "pg_stat_statements.track=all"] if statements and kind == "postgres" else [])  # fmt: skip
            started = _run(docker, *argv, service.image or "", *command)
            if started.returncode != 0:
                raise SandboxError(f"data service {service.name} did not start: {started.stderr.strip()[-300:]}")
            names[service.name] = container
        deadline = time.monotonic() + ready_timeout_s
        for service in services:
            probe = READY.get(service.data_kind or "")
            if probe is None:
                continue
            while _run(docker, "exec", names[service.name], *probe).returncode != 0:
                if time.monotonic() > deadline:
                    raise SandboxError(f"data service {service.name} was not ready within {ready_timeout_s:.0f}s")
                time.sleep(0.5)
        yield Sidecars(network, names)
    finally:
        for container in names.values():
            _run(docker, "rm", "-f", container)
        _run(docker, "network", "rm", network)
