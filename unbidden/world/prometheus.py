"""Read-only Prometheus connector: who calls whom in real traffic, and how each service of the project behaves.

Only fixed query templates are sent (`GET /api/v1/query`); no model writes PromQL. What is read is limited to the
workspace's own services and containers: a Prometheus that scrapes the whole host (the OpenTelemetry demo's
collector reads the Docker socket) also holds other projects' containers, and those are never taken in.

Families read, when present (others are named as a blind spot, not guessed):
- OpenTelemetry span metrics (`traces_span_metrics_*`): requests, errors and latency of each service's server spans.
- Client call metrics with a peer label (`rpc_client_*`, `http_client_*`, `db_client_*`): observed calls.
- Container metrics (`container_cpu_utilization_ratio`, `container_memory_usage_total_bytes`).
"""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from unbidden.contracts.common import EpistemicStatus, EvidenceRef, utc_now
from unbidden.contracts.world import BlindSpot, Relation, WorldModel
from unbidden.world.connectors import PROMETHEUS

CALLS_WINDOW = "15m"
CALLS_TTL = timedelta(minutes=15)
PROMETHEUS_PORT = 9090

# (metric, label naming the callee). Rates over the window, so only calls that happened recently count.
CLIENT_FAMILIES: tuple[tuple[str, str], ...] = (
    ("rpc_client_duration_milliseconds_count", "server_address"),
    ("rpc_client_call_duration_seconds_count", "server_address"),
    ("http_client_request_duration_seconds_count", "server_address"),
    ("http_client_duration_milliseconds_count", "net_peer_name"),
    ("db_client_operation_duration_seconds_count", "server_address"),
    ("db_client_operations_duration_seconds_count", "server_address"),
)
SPAN_CALLS = "traces_span_metrics_calls_total"
SPAN_BUCKETS = "traces_span_metrics_duration_milliseconds_bucket"
SERVER = 'span_kind="SPAN_KIND_SERVER"'


class PrometheusError(RuntimeError):
    pass


@dataclass
class Prometheus:
    url: str
    timeout_s: float = 5.0
    transport: httpx.BaseTransport | None = None
    sent: list[str] = field(default_factory=list[str])

    def query(self, promql: str, at: float | None = None) -> list[tuple[dict[str, str], float]]:
        """An instant query, now or at a past Unix time (`at`), which calibrations replay history with."""
        self.sent.append(promql)
        params = {"query": promql, **({"time": str(at)} if at is not None else {})}
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                response = client.get(f"{self.url}/api/v1/query", params=params)
        except httpx.HTTPError as exc:
            raise PrometheusError(f"{self.url} unreachable: {exc}") from exc
        body = response.json() if "json" in response.headers.get("content-type", "") else {}
        if response.status_code != 200 or body.get("status") != "success":
            raise PrometheusError(f"{self.url} answered {response.status_code}: {str(body)[:200]}")
        rows: list[tuple[dict[str, str], float]] = []
        for item in body["data"].get("result", []):
            value = float(item["value"][1])
            if not math.isnan(value):
                rows.append((dict(item["metric"]), value))
        return rows

    def names(self) -> set[str]:
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                response = client.get(f"{self.url}/api/v1/label/__name__/values")
            return set(response.json().get("data", []))
        except (httpx.HTTPError, ValueError) as exc:
            raise PrometheusError(f"{self.url} unreachable: {exc}") from exc


def find(world: WorldModel) -> str | None:
    """The project's own Prometheus: a running service whose image is Prometheus, on a published port."""
    for container in world.of_kind("container"):
        image = str(container.attributes.get("image") or "")
        if "prometheus" not in image.split("/")[-1]:
            continue
        ports: list[int] = container.attributes.get("ports") or []
        port = PROMETHEUS_PORT if PROMETHEUS_PORT in ports else (ports[0] if ports else None)
        if port is not None:
            return f"http://127.0.0.1:{port}"
    return None


@dataclass(frozen=True)
class ServiceHealth:
    service: str
    requests: float  # in the window
    errors: float
    p95_ms: float | None

    @property
    def error_ratio(self) -> float:
        return self.errors / self.requests if self.requests else 0.0


def health(
    prom: Prometheus, window: str, *, offset: str | None = None, at: float | None = None, by: str = "service_name"
) -> dict[str, ServiceHealth]:
    """Requests, errors and p95 of server spans over `window` (ending `offset` before `at`), per service, or per
    service and operation with `by="service_name, span_name"` (keys are then `service/operation`)."""
    shift = f" offset {offset}" if offset else ""
    total = prom.query(f"sum by ({by}) (increase({SPAN_CALLS}{{{SERVER}}}[{window}]{shift}))", at)
    failed = prom.query(
        f'sum by ({by}) (increase({SPAN_CALLS}{{{SERVER},status_code="STATUS_CODE_ERROR"}}[{window}]{shift}))', at
    )
    p95 = prom.query(
        f"histogram_quantile(0.95, sum by ({by}, le) (rate({SPAN_BUCKETS}{{{SERVER}}}[{window}]{shift})))", at
    )

    def key(m: dict[str, str]) -> str:
        return "/".join(m.get(k.strip(), "") for k in by.split(","))

    errors = {key(m): v for m, v in failed}
    latency = {key(m): v for m, v in p95 if not math.isinf(v)}
    return {
        key(m): ServiceHealth(key(m), v, errors.get(key(m), 0.0), latency.get(key(m)))
        for m, v in total
        if m.get("service_name")
    }


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def resolve_peer(peer: str, services: set[str], ips: dict[str, str]) -> tuple[str, str]:
    """('service', name) for a project service, ('external', host) for anything outside the project, or
    ('unknown', host) for a bare name that looks internal but is no service of this project."""
    host = peer.rstrip(".")
    if host in services:
        return "service", host
    if host in ips:
        return "service", ips[host]
    if _is_ip(host) or "." in host:
        return "external", host
    return "unknown", host


def observe(prom: Prometheus, world: WorldModel, ips: dict[str, str], *, environment: str = "local") -> None:
    """Add what the project's Prometheus shows: observed calls, and each service's and container's recent load."""
    now = utc_now()
    names = prom.names()
    services = {r.name for r in [*world.of_kind("service"), *world.of_kind("database")]}
    containers = {str(r.name): r for r in world.of_kind("container")}

    families = [(metric, label) for metric, label in CLIENT_FAMILIES if metric in names]
    if not families:
        world.blind_spots.append(
            BlindSpot(what="calls in traffic", why="Prometheus holds no client call metric Unbidden knows how to read")
        )
    unknown: dict[str, set[str]] = {}
    external: dict[str, set[str]] = {}
    for metric, label in families:
        query = f"sum by (service_name, {label}) (increase({metric}[{CALLS_WINDOW}]))"
        for labels, value in prom.query(query):
            caller, peer = labels.get("service_name", ""), labels.get(label, "")
            if value <= 0 or caller not in services or not peer:
                continue
            kind, callee = resolve_peer(peer, services, ips)
            if kind == "external":
                external.setdefault(caller, set()).add(callee)
                continue
            if kind == "unknown":
                unknown.setdefault(caller, set()).add(callee)
                continue
            if callee == caller:
                continue
            target = world.resources.get(f"service:{callee}")
            predicate = "uses_database" if target is not None and target.kind == "database" else "calls"
            world.relate(
                Relation(
                    src=f"service:{caller}",
                    dst=f"service:{callee}",
                    predicate=predicate,
                    status=EpistemicStatus.OBSERVED,
                    confidence=1.0,
                    evidence=[
                        EvidenceRef(
                            kind="config",
                            locator=f"{prom.url} {query}",
                            note=f"{value:.0f} calls in {CALLS_WINDOW} ({peer})",
                        )
                    ],
                    source=PROMETHEUS.ref,
                    environment=environment,
                    observed_at=now,
                    expires_at=now + CALLS_TTL,
                )
            )
    for caller, hosts in sorted(unknown.items()):
        world.blind_spots.append(
            BlindSpot(
                what=f"{caller} calls {', '.join(sorted(hosts))}",
                why="seen in its client metrics, but no service of this project has that name: not deployed?",
            )
        )
    for caller, hosts in sorted(external.items()):
        resource = world.resources.get(f"service:{caller}")
        if resource is not None:
            resource.attributes["external_peers"] = sorted(hosts)

    if SPAN_CALLS in names:
        for service, h in health(prom, "5m").items():
            resource = world.resources.get(f"service:{service}")
            if resource is None:
                continue
            resource.attributes["traffic"] = {
                "window": "5m",
                "requests": round(h.requests),
                "error_ratio": round(h.error_ratio, 4),
                "p95_ms": round(h.p95_ms, 1) if h.p95_ms is not None else None,
                "at": now.isoformat(),
                "source": PROMETHEUS.ref,
            }
    else:
        world.blind_spots.append(
            BlindSpot(what="request health", why="Prometheus holds no span metrics; errors and latency unseen")
        )

    cpu = {m.get("container_name", ""): v for m, v in _maybe(prom, names, "container_cpu_utilization_ratio")}
    mem = {m.get("container_name", ""): v for m, v in _maybe(prom, names, "container_memory_usage_total_bytes")}
    for name, resource in containers.items():
        if name in cpu or name in mem:
            resource.attributes["resources"] = {
                "cpu_ratio": round(cpu[name], 4) if name in cpu else None,
                "memory_bytes": int(mem[name]) if name in mem else None,
                "at": now.isoformat(),
                "source": PROMETHEUS.ref,
            }


def _maybe(prom: Prometheus, names: set[str], metric: str) -> list[tuple[dict[str, str], float]]:
    """A container metric summed per container. Rows for containers outside the project are dropped by the
    caller, which only reads names of this project's containers."""
    if metric not in names:
        return []
    return prom.query(f"sum by (container_name) ({metric})")


def project_ips(repo: Path) -> dict[str, str]:
    """IP address -> service, for this compose project's containers only."""
    from unbidden.operate.ledger import _docker_json  # pyright: ignore[reportPrivateUsage]
    from unbidden.world.runtime import running_containers

    rows = running_containers(repo)
    ids = [str(r["ID"]) for r in rows if r.get("ID")]
    if not ids:
        return {}
    found: dict[str, str] = {}
    for item in _docker_json("inspect", *ids):
        labels: dict[str, str] = (item.get("Config") or {}).get("Labels") or {}
        service = labels.get("com.docker.compose.service", "")
        networks: dict[str, Any] = (item.get("NetworkSettings") or {}).get("Networks") or {}
        for net in networks.values():
            ip = net.get("IPAddress")
            if ip and service:
                found[str(ip)] = service
    return found
