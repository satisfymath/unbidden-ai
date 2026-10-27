"""Service health from the project's own metrics: detect a degradation, find where it starts, say how to look.

Detection compares each service's last window with a baseline that ends where the window starts. The criteria are
fixed here and recorded with every anomaly; they were set before any fault was injected to test them.

Localization follows observed calls (and, failing those, inferred ones): a degraded service whose dependencies are
degraded too is an effect; one whose dependencies are healthy is where the problem starts. That is a hypothesis
about where to look, not a cause, and is recorded as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from unbidden.contracts.common import EpistemicStatus, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.world import WorldModel
from unbidden.store import Store
from unbidden.world.jaeger import Jaeger, JaegerError, origins
from unbidden.world.prometheus import Prometheus, ServiceHealth, health
from unbidden.world.scope import scope

WINDOW, BASELINE, MIN_REQUESTS, MIN_ERRORS = "5m", "30m", 8, 3
ERROR_FLOOR, ERROR_FACTOR = 0.05, 3.0
LATENCY_FACTOR, LATENCY_DELTA_MS = 2.0, 50.0
CHRONIC_REQUESTS = 30

CRITERIA: dict[str, str | float | int] = {
    "criteria_version": "health-v1",
    "window": WINDOW,
    "baseline": f"{BASELINE} ending where the window starts",
    "errors": f">= {MIN_REQUESTS} requests, >= {MIN_ERRORS} errors, "
    f"ratio >= max({ERROR_FLOOR}, {ERROR_FACTOR}x baseline)",
    "latency": f">= {MIN_REQUESTS} requests both sides, p95 >= max({LATENCY_FACTOR}x, +{LATENCY_DELTA_MS} ms) baseline",
    "chronic": f"baseline ratio >= {ERROR_FLOOR} with >= {CHRONIC_REQUESTS} requests: reported, not an anomaly",
}


@dataclass(frozen=True)
class Verdict:
    service: str
    degraded: bool
    chronic: bool
    reasons: tuple[str, ...]
    now: ServiceHealth
    baseline: ServiceHealth | None


def judge(now: ServiceHealth, baseline: ServiceHealth | None) -> Verdict:
    reasons: list[str] = []
    base_ratio = baseline.error_ratio if baseline and baseline.requests else 0.0
    chronic = bool(baseline and baseline.requests >= CHRONIC_REQUESTS and base_ratio >= ERROR_FLOOR)
    if (
        now.requests >= MIN_REQUESTS
        and now.errors >= MIN_ERRORS
        and now.error_ratio >= max(ERROR_FLOOR, ERROR_FACTOR * base_ratio)
    ):
        reasons.append(
            f"errors {now.error_ratio:.0%} of {now.requests:.0f} requests in {WINDOW} (baseline {base_ratio:.1%})"
        )
    if (
        baseline is not None
        and now.p95_ms is not None
        and baseline.p95_ms is not None
        and now.requests >= MIN_REQUESTS
        and baseline.requests >= MIN_REQUESTS
        and now.p95_ms >= max(LATENCY_FACTOR * baseline.p95_ms, baseline.p95_ms + LATENCY_DELTA_MS)
    ):
        reasons.append(f"p95 {baseline.p95_ms:.0f} -> {now.p95_ms:.0f} ms")
    return Verdict(now.service, bool(reasons), chronic, tuple(reasons), now, baseline)


@dataclass
class Suspect:
    service: str
    effects: list[str]  # degraded services that depend on it, directly or not
    via: str  # "observed" when the path is in traffic, "inferred" when only configuration says so
    evidence: list[str] = field(default_factory=list[str])


def _downstream(world: WorldModel, service: str) -> dict[str, str]:
    """service -> status of the call link, for what `service` calls or uses."""
    links: dict[str, str] = {}
    for r in world.current_relations():
        if r.src == f"service:{service}" and r.predicate in ("calls", "uses_database"):
            name = r.dst.split(":", 1)[1]
            if links.get(name) != EpistemicStatus.OBSERVED.value:
                links[name] = r.status.value
    return links


def localize(world: WorldModel, degraded: set[str]) -> list[Suspect]:
    """Degraded services none of whose dependencies is degraded, with what they explain."""
    roots: dict[str, Suspect] = {}
    for service in sorted(degraded):
        seen: set[str] = set()
        frontier = [(service, "observed")]
        found: list[tuple[str, str]] = []
        while frontier:
            node, via = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            bad = [(d, s) for d, s in _downstream(world, node).items() if d in degraded and d not in seen]
            if not bad and node in degraded:
                found.append((node, via))
            for d, status in bad:
                frontier.append((d, "observed" if via == "observed" and status == "observed" else "inferred"))
        for root, via in found:
            suspect = roots.setdefault(root, Suspect(root, [], via))
            if service != root:
                suspect.effects.append(service)
            if via == "inferred":
                suspect.via = "inferred"
    return sorted(roots.values(), key=lambda s: (-len(s.effects), s.via != "observed", s.service))


def plan(world: WorldModel, suspect: Suspect, *, traces: bool = False) -> list[dict[str, str]]:
    """What to look at next, in order, and whether Unbidden can already read it."""
    covered = {f.source for f in [*world.resources.values(), *world.relations]}
    container = next(
        (c.name for c in world.of_kind("container") if c.attributes.get("service") == suspect.service), None
    )
    steps = [
        {
            "step": f"compare {suspect.service}'s errors and latency per operation before and during the anomaly",
            "source": "prometheus span metrics",
            "available": "yes" if any(s and s.startswith("prometheus") for s in covered) else "no",
        },
        {
            "step": f"read {suspect.service}'s error lines in the window",
            "source": f"docker logs {container}" if container else "container logs",
            "available": "yes, read-only" if container else "no container known",
        },
        {
            "step": f"follow failing requests from {', '.join(suspect.effects[:3]) or 'callers'} "
            f"into {suspect.service}",
            "source": "traces",
            "available": "yes: done below, from the project's Jaeger" if traces else "no: no trace connector reachable",
        },
        {
            "step": f"check what changed in {suspect.service}: deploy, image, configuration, feature flags",
            "source": "deploy ledger, compose, flags",
            "available": "deploys and compose yes; feature-flag state no",
        },
    ]
    return steps


def trace_check(traces: Jaeger, suspect: Suspect) -> dict[str, Any]:
    """Where failing requests through the furthest-upstream affected service actually fail, from their traces."""
    entry = suspect.effects[0] if suspect.effects else suspect.service
    counts, seen, failing = origins(traces.spans(entry))
    top = counts.most_common(1)[0][0] if counts else None
    return {
        "through": entry,
        "traces": seen,
        "failing_traces": failing,
        "origins": dict(counts.most_common(5)),
        "agrees": top == suspect.service if top else None,
    }


@dataclass
class HealthWatcher:
    store: Store
    world: WorldModel
    prom: Prometheus
    log: Any = print
    traces: Jaeger | None = None

    def assess(self, at: datetime | None = None) -> dict[str, Any]:
        now_h = health(self.prom, WINDOW)
        base_h = health(self.prom, BASELINE, offset=WINDOW)
        services = {r.name for r in self.world.of_kind("service")} | {r.name for r in self.world.of_kind("database")}
        verdicts = [judge(h, base_h.get(name)) for name, h in sorted(now_h.items()) if name in services]
        degraded = {v.service for v in verdicts if v.degraded}
        suspects = localize(self.world, degraded)
        return {
            "at": (at or utc_now()).isoformat(),
            "criteria": CRITERIA,
            "verdicts": verdicts,
            "degraded": sorted(degraded),
            "chronic": sorted(v.service for v in verdicts if v.chronic),
            "suspects": suspects,
            "unmeasured": sorted(services - set(now_h)),
        }

    def tick(self) -> dict[str, Any]:
        """Assess, and record anomalies that begin or end. One open anomaly per suspect at a time."""
        report = self.assess()
        open_: dict[str, dict[str, Any]] = self.store.get_value("open_anomalies", {})
        current = {s.service: s for s in report["suspects"]}
        verdicts = {v.service: v for v in report["verdicts"]}
        for name, suspect in current.items():
            if name in open_:
                continue
            record = {
                "suspect": name,
                "status": EpistemicStatus.HYPOTHESIS.value,
                "statement": f"the degradation starts in {name}"
                + (f" and reaches {', '.join(suspect.effects)}" if suspect.effects else ""),
                "via": suspect.via,
                "reasons": {s: list(verdicts[s].reasons) for s in [name, *suspect.effects] if s in verdicts},
                "criteria": CRITERIA,
                "started": report["at"],
                "queries": self.prom.sent[-3:],
                "plan": plan(self.world, suspect, traces=self.traces is not None),
                "scope": scope(self.world, f"service:{name}").brief(),
            }
            if self.traces is not None:
                try:
                    record["traces"] = trace_check(self.traces, suspect)
                except JaegerError as exc:
                    record["traces"] = {"error": str(exc)}
            open_[name] = record
            self.store.append_event(
                Event(type=EventType.ANOMALY_DETECTED, actor="observer", entity_id=f"service:{name}", payload=record)
            )
            self.log(f"anomaly: {record['statement']} ({'; '.join(verdicts[name].reasons)})")
        for name in [n for n in open_ if n not in current]:
            record = open_.pop(name)
            self.store.append_event(
                Event(
                    type=EventType.ANOMALY_RESOLVED,
                    actor="observer",
                    entity_id=f"service:{name}",
                    payload={"suspect": name, "started": record["started"], "ended": report["at"]},
                )
            )
            self.log(f"anomaly over: {name}")
        self.store.set_value("open_anomalies", open_)
        return report
