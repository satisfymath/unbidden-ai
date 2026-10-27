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
from pathlib import Path
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


# A candidate, not in use: designed after the faults of D-024 and to be calibrated before it may replace v1.
V2_MIN_OP_REQUESTS, V2_MIN_LATENCY_REQUESTS, V2_SIGMAS = 10, 50, 4.0
CRITERIA_V2_CANDIDATE: dict[str, str | float | int] = {
    "criteria_version": "health-v2-candidate",
    "window": WINDOW,
    "baseline": f"{BASELINE} ending where the window starts",
    "unit": "each operation (span name) of a service; a service is degraded when one of its operations is",
    "errors": f">= {V2_MIN_OP_REQUESTS} requests, >= {MIN_ERRORS} errors, ratio >= max({ERROR_FLOOR}, "
    f"baseline + {V2_SIGMAS} binomial standard deviations)",
    "latency": f">= {V2_MIN_LATENCY_REQUESTS} requests both sides, p95 >= max({LATENCY_FACTOR}x, "
    f"+{LATENCY_DELTA_MS} ms) baseline",
}


def judge_v2(now: ServiceHealth, baseline: ServiceHealth | None) -> bool:
    import math

    base = baseline.error_ratio if baseline and baseline.requests else 0.0
    spread = math.sqrt(max(base * (1 - base), 1e-9) / max(now.requests, 1.0))
    errors = (
        now.requests >= V2_MIN_OP_REQUESTS
        and now.errors >= MIN_ERRORS
        and now.error_ratio >= max(ERROR_FLOOR, base + V2_SIGMAS * spread)
    )
    latency = (
        baseline is not None
        and now.p95_ms is not None
        and baseline.p95_ms is not None
        and now.requests >= V2_MIN_LATENCY_REQUESTS
        and baseline.requests >= V2_MIN_LATENCY_REQUESTS
        and now.p95_ms >= max(LATENCY_FACTOR * baseline.p95_ms, baseline.p95_ms + LATENCY_DELTA_MS)
    )
    return errors or latency


def degraded_services(prom: Prometheus, criteria: str, at: float | None = None) -> set[str]:
    """Services judged degraded at `at` (or now) under criteria v1 or the v2 candidate; for calibrations."""
    if criteria == "health-v1":
        now, base = health(prom, WINDOW, at=at), health(prom, BASELINE, offset=WINDOW, at=at)
        return {name for name, h in now.items() if judge(h, base.get(name)).degraded}
    by = "service_name, span_name"
    now, base = health(prom, WINDOW, at=at, by=by), health(prom, BASELINE, offset=WINDOW, at=at, by=by)
    return {key.split("/", 1)[0] for key, h in now.items() if judge_v2(h, base.get(key))}


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


COMMON_CAUSE_MIN = 3


def common_cause(world: WorldModel, suspects: list[Suspect]) -> Suspect | None:
    """Several origins at once, none reaching another through any known link: more likely one cause they share (the
    host, the network, a shared resource) than as many independent failures."""
    if len(suspects) < COMMON_CAUSE_MIN:
        return None
    names = {s.service for s in suspects}
    linked = {
        (r.src.split(":", 1)[1], r.dst.split(":", 1)[1])
        for r in world.current_relations()
        if r.predicate in ("calls", "uses_database", "depends_on")
    }
    if any((a, b) in linked for a in names for b in names if a != b):
        return None
    effects = sorted({e for s in suspects for e in [s.service, *s.effects]})
    return Suspect("(common cause outside the service graph)", effects, "observed")


def plan(world: WorldModel, suspect: Suspect, *, traces: bool = False) -> list[dict[str, str]]:
    """What to look at next, in order, and whether Unbidden can already read it."""
    covered = {f.source for f in [*world.resources.values(), *world.relations]}
    if suspect.service.startswith("("):
        return [
            {
                "step": f"compare CPU and memory of {', '.join(suspect.effects[:6])} and of the host before and during",
                "source": "prometheus container metrics",
                "available": "containers yes; the host only if its own metrics are scraped",
            },
            {
                "step": "look for what else ran on the machine or network at that minute",
                "source": "host processes, other workloads",
                "available": "no: outside what this workspace may read",
            },
        ]
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


def proxy_errors(store: Store, world: WorldModel, wait_s: float = 10.0) -> dict[str, dict[str, float]]:
    """Errors each proxy saw per upstream over a few seconds, through stats readers Forge built: counters are read
    twice and only their growth counts."""
    import time

    from unbidden.forge import stats_build
    from unbidden.forge.stats import deltas, read

    readers = [
        (str(c.attributes.get("service")), e["url"], stats_build.usable(store, e["url"]))
        for c in world.of_kind("container")
        for e in c.attributes.get("text_endpoints", [])
    ]
    readers = [(s, u, a) for s, u, a in readers if a is not None]
    if not readers:
        return {}
    before = {u: stats_build.fetch(u) for _, u, _ in readers}
    time.sleep(wait_s)
    found: dict[str, dict[str, float]] = {}
    for service, url, adapter in readers:
        after = stats_build.fetch(url)
        assert adapter is not None
        metrics = {r.metric for r in read(adapter, after) if r.metric and ("5xx" in r.metric or "error" in r.metric)}
        for metric in sorted(metrics):
            grown = {e: d for e, d in deltas(adapter, before[url], after, metric).items() if d > 0}
            if grown:
                found[f"{service} {metric}"] = grown
    return found


UI_REFERENCE_EVERY_S = 3600.0


def web_page(world: WorldModel) -> str | None:
    """The project's own web page, preferring a proxy in front of the rest (what users reach)."""
    pages = [
        (str(c.attributes.get("service", "")), str(c.attributes["web_page"]))
        for c in world.of_kind("container")
        if c.attributes.get("web_page")
    ]
    pages.sort(key=lambda sp: (0 if "proxy" in sp[0] else 1, sp[0]))
    return pages[0][1] if pages else None


class UiCheck:
    """What the product's page looks like during an anomaly, against a reference taken while all was healthy."""

    def __init__(self, store: Store, world: WorldModel, artifacts: Path, key: str | None) -> None:
        self.store, self.world, self.artifacts, self.key = store, world, artifacts, key

    def refresh_reference(self) -> None:
        from unbidden.lab.ui import capture

        url = web_page(self.world)
        last = self.store.get_value("ui_reference")
        fresh = last and utc_now().timestamp() - float(last.get("ts", 0)) < UI_REFERENCE_EVERY_S
        if url is None or fresh:
            return
        capture(url, self.artifacts / "reference")
        self.store.set_value("ui_reference", {"url": url, "ts": utc_now().timestamp(), "at": utc_now().isoformat()})

    def judge(self, mandate: Any) -> dict[str, Any]:
        import json as _json

        from unbidden.lab.ui import Capture, browser_judge, capture, visual_judge

        ref = self.store.get_value("ui_reference")
        if not ref:
            return {"note": "no reference capture of the page yet"}
        ref_dir = self.artifacts / "reference"
        reference = Capture(
            ref["url"],
            (ref_dir / "screenshot.png").read_bytes(),
            _json.loads((ref_dir / "page.json").read_text()),
            ref_dir,
        )
        now = capture(ref["url"], self.artifacts / f"anomaly-{int(utc_now().timestamp())}")
        result: dict[str, Any] = {
            "url": ref["url"],
            "reference_at": ref["at"],
            "browser": browser_judge(now.page, reference.page),
        }
        if self.key and mandate.models.screenshots_to_frontier == "allow":
            result["visual"] = visual_judge(now, reference, store=self.store, mandate=mandate, key=self.key)
        else:
            result["visual"] = {"note": "screenshots may not leave under this mandate; browser judge only"}
        return result


@dataclass
class HealthWatcher:
    store: Store
    world: WorldModel
    prom: Prometheus
    log: Any = print
    traces: Jaeger | None = None
    ui: UiCheck | None = None
    mandate: Any = None

    def assess(self, at: datetime | None = None) -> dict[str, Any]:
        now_h = health(self.prom, WINDOW)
        base_h = health(self.prom, BASELINE, offset=WINDOW)
        services = {r.name for r in self.world.of_kind("service")} | {r.name for r in self.world.of_kind("database")}
        verdicts = [judge(h, base_h.get(name)) for name, h in sorted(now_h.items()) if name in services]
        degraded = {v.service for v in verdicts if v.degraded}
        suspects = localize(self.world, degraded)
        shared = common_cause(self.world, suspects)
        if shared is not None:
            suspects = [shared]
        return {
            "at": (at or utc_now()).isoformat(),
            "criteria": CRITERIA,
            "verdicts": verdicts,
            "degraded": sorted(degraded),
            "chronic": sorted(v.service for v in verdicts if v.chronic),
            "suspects": suspects,
            "unmeasured": sorted(services - set(now_h)),
            # Too few requests to say anything either way: not "healthy", unjudged.
            "unjudged": sorted(name for name, h in now_h.items() if name in services and h.requests < MIN_REQUESTS),
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
                "common_cause": name.startswith("("),
                "criteria": CRITERIA,
                "started": report["at"],
                "queries": self.prom.sent[-3:],
                "plan": plan(self.world, suspect, traces=self.traces is not None),
                "scope": scope(self.world, f"service:{name}").brief() if not name.startswith("(") else {},
            }
            if self.traces is not None:
                try:
                    record["traces"] = trace_check(self.traces, suspect)
                except JaegerError as exc:
                    record["traces"] = {"error": str(exc)}
            if self.ui is not None and self.mandate is not None:
                try:
                    record["ui"] = self.ui.judge(self.mandate)
                except Exception as exc:  # a failed capture is recorded, never blocks the anomaly
                    record["ui"] = {"error": str(exc)[:300]}
            try:
                record["proxies"] = proxy_errors(self.store, self.world)
            except Exception as exc:  # a reader that fails is recorded, never blocks the anomaly
                record["proxies"] = {"error": {str(exc)[:200]: 0.0}}
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
        if not open_ and self.ui is not None:
            try:
                self.ui.refresh_reference()
            except Exception as exc:
                self.log(f"reference capture failed: {exc}")
        return report
