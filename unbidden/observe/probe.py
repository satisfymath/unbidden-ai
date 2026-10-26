"""Probes: the running system observed from outside, the way a user meets it.

Every round sends a few GET requests to each observed endpoint without path parameters and records each
latency and status with the version that served it. A version is the repository commit the serving container
was started from, recorded the first time that container is seen. Login, when the live API declares OAuth2
password flow, uses credentials read from unbidden's own environment.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from unbidden.contracts.guardian import ProbeAuth
from unbidden.contracts.world import WorldModel
from unbidden.store import Store
from unbidden.workspace import head_sha
from unbidden.world.runtime import fetch_openapi, host_ports, running_containers

REQUESTS_PER_ROUND = 5


@dataclass
class Target:
    label: str  # "GET /api/v1/items/"
    url: str
    auth: bool


@dataclass
class Prober:
    repo: Path
    store: Store
    world: WorldModel
    auth: ProbeAuth | None = None
    requests_per_round: int = REQUESTS_PER_ROUND
    _token: str | None = field(default=None, init=False)

    def app_containers(self) -> dict[str, dict[str, Any]]:
        services = {r.attributes.get("service") for r in self.world.of_kind("endpoint")}
        return {c["Service"]: c for c in running_containers(self.repo) if c.get("Service") in services}

    def version(self) -> str | None:
        """The commit the app containers were started from; None when no app container runs."""
        containers = self.app_containers()
        if not containers:
            return None
        key = ",".join(sorted(c.get("ID", "") for c in containers.values()))
        known: dict[str, str] = self.store.get_value("container_versions", {})
        if key not in known:
            known[key] = head_sha(self.repo)
            self.store.set_value("container_versions", known)
            # Every new set of containers is a deploy, even of a version seen before (a rollback).
            sequence: list[str] = self.store.get_value("deploy_sequence", [])
            if not sequence or sequence[-1] != known[key]:
                self.store.set_value("deploy_sequence", [*sequence, known[key]])
        return known[key]

    def targets(self) -> list[Target]:
        found: list[Target] = []
        for endpoint in self.world.of_kind("endpoint"):
            method, _, path = endpoint.name.partition(" ")
            port = endpoint.attributes.get("port")
            if method != "GET" or "{" in path or not port:
                continue
            found.append(Target(endpoint.name, f"http://127.0.0.1:{port}{path}", bool(endpoint.attributes.get("auth"))))
        return found

    def _login(self, client: httpx.Client) -> str | None:
        if self.auth is None:
            return None
        user, password = os.environ.get(self.auth.username_env), os.environ.get(self.auth.password_env)
        if not user or not password:
            return None
        for container in self.app_containers().values():
            for port in host_ports(container):
                found = fetch_openapi(port)
                if found is None:
                    continue
                schemes = found[1].get("components", {}).get("securitySchemes", {})
                for scheme in schemes.values():
                    token_url = (scheme.get("flows", {}).get("password") or {}).get("tokenUrl")
                    if not token_url:
                        continue
                    url = (
                        token_url
                        if token_url.startswith("http")
                        else f"http://127.0.0.1:{port}/{token_url.lstrip('/')}"
                    )
                    response = client.post(url, data={"username": user, "password": password})
                    if response.status_code == 200:
                        return response.json().get("access_token")
        return None

    def round(self) -> int:
        """One pass over every target. Returns the number of requests sent."""
        version = self.version()
        if version is None:
            return 0
        sent = 0
        with httpx.Client(timeout=10.0) as client:
            for target in self.targets():
                headers: dict[str, str] = {}
                if target.auth:
                    self._token = self._token or self._login(client)
                    if self._token is None:
                        continue
                    headers["Authorization"] = f"Bearer {self._token}"
                statuses: list[int] = []
                latencies: list[float] = []
                for _ in range(self.requests_per_round):
                    started = time.perf_counter()
                    try:
                        status = client.get(target.url, headers=headers).status_code
                    except httpx.HTTPError:
                        status = 0  # transport failure: counted as an error, never as a latency
                    latencies.append((time.perf_counter() - started) * 1000)
                    statuses.append(status)
                    if status == 401:
                        self._token = None
                self.store.add_round(target.label, version, statuses, latencies)
                sent += len(statuses)
        return sent
