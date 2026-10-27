"""Read-only Jaeger connector (API v3): where failing requests actually fail, from their traces.

For a service, recent traces through it are fetched and, in each, the spans with an error status are found. A failing
span whose children did not fail is where the failure starts; counting those per service gives a second, independent
answer to "where does this degradation start", next to the one from metrics.

Only service names, span ids, parent ids and status codes are read. Span attributes and events (which may hold user
data: the demo can be told to put card numbers in them) are dropped as soon as a response is parsed, never stored
and never sent anywhere.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from unbidden.contracts.common import utc_now
from unbidden.contracts.world import WorldModel

BASE_PATHS = ("", "/jaeger/ui", "/jaeger")
ERROR = ("STATUS_CODE_ERROR", 2)


class JaegerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Span:
    trace: str
    span: str
    parent: str
    service: str
    failed: bool


@dataclass
class Jaeger:
    base: str  # http://127.0.0.1:port/base_path
    timeout_s: float = 5.0
    transport: httpx.BaseTransport | None = None
    sent: list[str] = field(default_factory=list[str])

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self.sent.append(f"{self.base}{path}")
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                response = client.get(f"{self.base}{path}", params=params)
        except httpx.HTTPError as exc:
            raise JaegerError(f"{self.base} unreachable: {exc}") from exc
        if response.status_code == 404 and "No traces" in response.text:
            return {}
        if response.status_code != 200:
            raise JaegerError(f"{self.base}{path} answered {response.status_code}")
        return response.json()

    def spans(self, service: str, minutes: int = 5, limit: int = 100, end: datetime | None = None) -> list[Span]:
        now = end or utc_now()
        body = self._get(
            "/traces",
            {
                "query.service_name": service,
                "query.start_time_min": (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "query.start_time_max": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "query.num_traces": str(limit),
            },
        )
        return parse(body)


def parse(body: dict[str, Any]) -> list[Span]:
    """Spans of an OTLP JSON answer, reduced to what is needed; attributes and events are dropped here."""
    found: list[Span] = []
    for resource in (body.get("result") or {}).get("resourceSpans", []):
        attrs = (resource.get("resource") or {}).get("attributes", [])
        service = next((a["value"].get("stringValue", "") for a in attrs if a.get("key") == "service.name"), "unknown")
        for scope in resource.get("scopeSpans", []):
            for s in scope.get("spans", []):
                code = (s.get("status") or {}).get("code")
                found.append(
                    Span(
                        trace=str(s.get("traceId", "")),
                        span=str(s.get("spanId", "")),
                        parent=str(s.get("parentSpanId", "")),
                        service=service,
                        failed=code in ERROR,
                    )
                )
    return found


def origins(spans: list[Span]) -> tuple[Counter[str], int, int]:
    """(failing spans whose children did not fail, per service; traces seen; traces with a failure)."""
    children: dict[tuple[str, str], list[Span]] = {}
    for s in spans:
        children.setdefault((s.trace, s.parent), []).append(s)
    counts: Counter[str] = Counter()
    failing_traces: set[str] = set()
    for s in spans:
        if not s.failed:
            continue
        failing_traces.add(s.trace)
        if not any(c.failed for c in children.get((s.trace, s.span), [])):
            counts[s.service] += 1
    return counts, len({s.trace for s in spans}), len(failing_traces)


def find(world: WorldModel) -> Jaeger | None:
    """The project's own Jaeger: a running container whose image is Jaeger and whose port answers the v3 API."""
    for container in world.of_kind("container"):
        if "jaeger" not in str(container.attributes.get("image") or "").split("/")[-1]:
            continue
        for port in container.attributes.get("ports") or []:
            for base in BASE_PATHS:
                url = f"http://127.0.0.1:{port}{base}/api/v3"
                try:
                    response = httpx.get(f"{url}/services", timeout=2.0)
                except httpx.HTTPError:
                    continue
                if response.status_code == 200 and "services" in response.text:
                    return Jaeger(url)
    return None
