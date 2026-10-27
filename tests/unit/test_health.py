from __future__ import annotations

import httpx
import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import Relation, Resource, WorldModel
from unbidden.observe.health import judge, localize
from unbidden.world.prometheus import Prometheus, ServiceHealth, observe, resolve_peer

pytestmark = pytest.mark.unit


def h(service: str, requests: float, errors: float = 0, p95: float | None = 10.0) -> ServiceHealth:
    return ServiceHealth(service, requests, errors, p95)


def test_errors_far_above_the_services_own_baseline_are_degraded() -> None:
    assert judge(h("payment", 40, 20), h("payment", 300, 0)).degraded
    assert not judge(h("payment", 40, 2), h("payment", 300, 0)).degraded  # under the minimum error count
    assert not judge(h("payment", 5, 5), h("payment", 300, 0)).degraded  # too few requests to say anything


def test_a_service_that_always_fails_this_much_is_chronic_not_an_anomaly() -> None:
    v = judge(h("quote", 60, 12), h("quote", 360, 72))
    assert v.chronic and not v.degraded


def test_latency_needs_both_a_ratio_and_an_absolute_step() -> None:
    assert judge(h("x", 50, p95=120), h("x", 300, p95=40)).degraded
    assert not judge(h("x", 50, p95=4), h("x", 300, p95=1.9)).degraded  # doubled, but by 2 ms


def world_with(*links: tuple[str, str, EpistemicStatus]) -> WorldModel:
    w = WorldModel(rev="r")
    names = {n for a, b, _ in links for n in (a, b)}
    for n in names:
        w.add(
            Resource(
                id=f"service:{n}",
                kind="service",
                name=n,
                status=EpistemicStatus.OBSERVED,
                confidence=1,
                evidence=[EvidenceRef(kind="config", locator=n)],
            )
        )
    for a, b, status in links:
        w.relate(
            Relation(
                src=f"service:{a}",
                dst=f"service:{b}",
                predicate="calls",
                status=status,
                confidence=1,
                evidence=[EvidenceRef(kind="config", locator=f"{a}->{b}")],
            )
        )
    return w


def test_the_suspect_is_the_degraded_service_whose_dependencies_are_healthy() -> None:
    obs = EpistemicStatus.OBSERVED
    w = world_with(("frontend", "checkout", obs), ("checkout", "payment", obs), ("checkout", "cart", obs))
    suspects = localize(w, {"frontend", "checkout", "payment"})
    assert [s.service for s in suspects] == ["payment"]
    assert sorted(suspects[0].effects) == ["checkout", "frontend"] and suspects[0].via == "observed"


def test_a_path_known_only_from_configuration_says_so() -> None:
    w = world_with(("frontend", "ad", EpistemicStatus.INFERRED))
    suspects = localize(w, {"frontend", "ad"})
    assert [(s.service, s.via) for s in suspects] == [("ad", "inferred")]


def test_peers_resolve_to_project_services_and_nothing_else() -> None:
    services = {"cart", "payment"}
    assert resolve_peer("cart", services, {}) == ("service", "cart")
    assert resolve_peer("192.168.155.20", services, {"192.168.155.20": "payment"}) == ("service", "payment")
    assert resolve_peer("metadata.google.internal.", services, {}) == ("external", "metadata.google.internal")
    assert resolve_peer("agent", services, {}) == ("unknown", "agent")


def test_other_projects_containers_in_a_host_wide_prometheus_are_never_taken_in() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/values"):
            return httpx.Response(200, json={"data": ["container_cpu_utilization_ratio"]})
        rows = [
            {"metric": {"container_name": "cart"}, "value": [0, "0.1"]},
            {"metric": {"container_name": "hosli-recs-api-1"}, "value": [0, "0.9"]},
        ]
        return httpx.Response(200, json={"status": "success", "data": {"result": rows}})

    w = WorldModel(rev="r")
    w.add(
        Resource(
            id="container:cart",
            kind="container",
            name="cart",
            attributes={"service": "cart"},
            status=EpistemicStatus.OBSERVED,
            confidence=1,
            evidence=[EvidenceRef(kind="config", locator="ps")],
        )
    )
    observe(Prometheus("http://p", transport=httpx.MockTransport(answer)), w, {})
    assert w.resources["container:cart"].attributes["resources"]["cpu_ratio"] == 0.1
    assert "hosli" not in w.model_dump_json()
