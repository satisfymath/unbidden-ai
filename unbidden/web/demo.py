"""Demo fixtures: a fictional shop ("storefront-web") built through the engine's own contracts into an in-memory store.

Everything here is synthetic and labelled `demo` by the source; it exists so the interaction can be developed and
tested without a run. Numbers are generated from a fixed seed, so screenshots and tests are stable.
"""

from __future__ import annotations

import json
import random
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from unbidden.contracts.capability import CapabilityNeed, NeedStatus
from unbidden.contracts.common import Cost, EpistemicStatus, EvidenceLevel, EvidenceRef
from unbidden.contracts.connection import Ability, Connection, ConnectionState, Environment
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, Proposal, ProposalStatus, TestSummary
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.llm import ModelRun, Tier, Usage
from unbidden.contracts.opportunity import ActionKind, CandidateAction, Decision, Opportunity, OpportunityStatus
from unbidden.contracts.world import Deployment, Relation, Resource, RunningContainer, WorldModel
from unbidden.director.blocks import COLLECTION as BLOCKS
from unbidden.director.blocks import Block
from unbidden.store import Store
from unbidden.workspace import default_mandate

HEAD = "a3f1c9d2e4b56789012345678901234567890abcd"[:40].ljust(40, "0")
BASE = "0fbc1d2e3a4b5c6d7e8f9012345678901234abcd".ljust(40, "0")
COMMIT = "77aa11bb22cc33dd44ee55ff6677889900aabbcc".ljust(40, "0")
T0 = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def _at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _samples(rng: random.Random, centre: float, spread: float, n: int) -> list[float]:
    return [round(max(0.2, rng.gauss(centre, spread)), 3) for _ in range(n)]


def _sessions(rng: random.Random, before: float, after: float, n_per_arm: int, phase: str) -> list[dict[str, Any]]:
    out = []
    order = ["base", "candidate"] * n_per_arm
    rng.shuffle(order)
    for position, arm in enumerate(order):
        centre = before if arm == "base" else after
        samples = _samples(rng, centre, centre * 0.08, 20)
        out.append(
            {
                "arm": arm,
                "position": position,
                "samples_ms": samples,
                "median_ms": statistics.median(samples),
                "index_scans": 20 if arm == "candidate" else 0,
                "phase": phase,
            }
        )
    return out


class DemoTicker:
    """Appends one synthetic event per call, so the live stream can be exercised in demo mode (labelled demo)."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.n = 0

    def tick(self) -> Event:
        self.n += 1
        kinds = [
            (
                EventType.MODEL_CALLED,
                "brain",
                {
                    "purpose": "research.step",
                    "tier": "local",
                    "model": "muse-glimmer:30b",
                    "ok": True,
                    "tokens_in": 900 + self.n,
                    "tokens_out": 120,
                    "usd": 0.0,
                },
            ),
            (EventType.LOG_SIGNAL, "observer", {"service": "api", "kind": "error_after_deploy", "lines": 2}),
            (EventType.WORLD_CHANGED, "world", {"diff": {"n_added": 0, "n_carried": 41, "n_changed": 1}}),
        ]
        type_, actor, payload = kinds[self.n % len(kinds)]
        return self.store.append_event(Event(type=type_, actor=actor, payload={**payload, "demo": True}))


def build_demo(store: Store | None = None) -> Any:
    """The demo source: the fixtures in an in-memory store (or the store given, for a development workspace)."""
    from unbidden.web.sources import Source

    store = store if store is not None else Store(None)
    spend_rows, observed = populate(store)
    mandate = Mandate.model_validate(default_mandate("storefront-web", "acme/storefront-web", "main")["mandate"])
    source = Source(
        id="demo:storefront-web",
        name="storefront-web",
        mode="demo",
        store=store,
        mandate=mandate,
        observed_at=observed,
        notes=["demo: synthetic records built through the engine's contracts"],
        spend_fixture=spend_rows,
        streams=True,
    )
    source.ticker = DemoTicker(store)  # type: ignore[attr-defined]
    return source


def populate(store: Store) -> tuple[list[dict[str, Any]], datetime]:
    """Write the fixtures into `store` through the engine's contracts. Returns the spend rows and the record's time."""
    rng = random.Random(7)
    ev: list[Event] = []

    def event(
        minutes: float,
        type_: EventType,
        actor: str,
        payload: dict[str, Any],
        *,
        entity: str | None = None,
        correlation: str | None = None,
    ) -> None:
        ev.append(
            Event(
                ts=_at(minutes), type=type_, actor=actor, entity_id=entity, correlation_id=correlation, payload=payload
            )
        )

    store.set_value("head", HEAD)
    store.set_value(
        "last_scan",
        {
            "rev": HEAD,
            "at": _at(3).isoformat(),
            "languages": ["python"],
            "reports": 2,
            "problems": [],
            "blind_spots": ["no OpenAPI served at the probe port"],
        },
    )
    store.set_value(
        "baseline_checks",
        {
            "rev": HEAD,
            "at": _at(6).isoformat(),
            "status": "passed",
            "collected": 142,
            "failed": [],
            "partial": False,
            "command": "bash -c 'cd /work && pytest -q'",
            "scope": "tests/",
        },
    )
    event(0, EventType.WORKSPACE_INITIALIZED, "cli", {"repo": "storefront-web"})
    event(0.5, EventType.HEAD_MOVED, "observer", {"from": None, "to": HEAD})
    event(2, EventType.ANALYZER_RAN, "observer", {"tool": "ruff", "findings": 3, "completeness": "complete"})
    event(2.5, EventType.ANALYZER_RAN, "observer", {"tool": "pyright", "findings": 0, "completeness": "complete"})

    # Opportunities ----------------------------------------------------------------------------------------------
    exp1 = Experiment(
        id="exp_demo000000000001",
        opportunity_id="opp_demo000000000001",
        base_sha=HEAD,
        candidate_patch_sha256="c" * 64,
        rounds=3,
        baseline_tests=TestSummary(
            rounds=3,
            failed_per_round=[[], [], []],
            round_status=["ran"] * 3,
            collected_per_round=[142] * 3,
            infra_why=[None] * 3,
        ),
        candidate_tests=TestSummary(
            rounds=3,
            failed_per_round=[[], [], []],
            round_status=["ran"] * 3,
            collected_per_round=[142] * 3,
            infra_why=[None] * 3,
        ),
        samples_before_ms=_samples(rng, 18.4, 1.4, 80),
        samples_after_ms=_samples(rng, 11.2, 0.9, 80),
        workload_sha256="w" * 64,
        sessions=_sessions(rng, 18.4, 11.2, 4, "measured"),
        control=_sessions(rng, 18.4, 18.4, 2, "control"),
        confirmation=_sessions(rng, 18.4, 11.3, 2, "confirmation"),
        spec_id="spec_demo0000000001",
        provenance={"engine": "demo", "images": {"python": "unbidden-deps-python:demo"}},
        cost=Cost(tokens_in=18_400, tokens_out=2_100, usd_remote=0.0412),
        started_at=_at(12),
    )
    exp2 = Experiment(
        id="exp_demo000000000002",
        opportunity_id="opp_demo000000000002",
        base_sha=HEAD,
        candidate_patch_sha256="d" * 64,
        rounds=3,
        baseline_tests=TestSummary(
            rounds=3,
            failed_per_round=[["tests/test_cart.py::test_remove_expired"], [], []],
            round_status=["ran"] * 3,
            collected_per_round=[142] * 3,
            infra_why=[None] * 3,
        ),
        candidate_tests=TestSummary(
            rounds=3,
            failed_per_round=[[], ["tests/test_cart.py::test_remove_expired"], []],
            round_status=["ran"] * 3,
            collected_per_round=[142] * 3,
            infra_why=[None] * 3,
        ),
        samples_before_ms=_samples(rng, 9.1, 0.8, 80),
        samples_after_ms=_samples(rng, 8.7, 0.8, 80),
        workload_sha256="x" * 64,
        sessions=_sessions(rng, 9.1, 8.7, 4, "measured"),
        spec_id="spec_demo0000000002",
        provenance={"engine": "demo"},
        cost=Cost(tokens_in=15_900, tokens_out=1_800, usd_remote=0.0355),
        started_at=_at(40),
    )
    verdict1 = {
        "experiment_id": exp1.id,
        "improved": True,
        "evidence_level": 4,
        "outcome": "improved",
        "criteria": {"version": "perf-v4", "alpha": 0.05, "min_median_improvement": 0.2},
        "tests": "passed",
        "reasons": [
            "session medians 18.4 -> 11.2 ms (+39% faster)",
            "exact permutation test p = 0.014",
            "the index used on every call",
        ],
        "scope": "GET /api/orders/{id} on 20k orders / 180k items, PostgreSQL 16, this machine",
    }
    verdict2 = {
        "experiment_id": exp2.id,
        "improved": False,
        "evidence_level": 3,
        "outcome": "no_relevant_change",
        "criteria": {"version": "perf-v4", "alpha": 0.05, "min_median_improvement": 0.2},
        "tests": "pre_existing",
        "reasons": ["session medians 9.1 -> 8.7 ms: within ±20%"],
        "caveats": ["tests/test_cart.py::test_remove_expired fails once on each side (pre-existing)"],
    }
    opps = [
        Opportunity(
            id="opp_demo000000000001",
            source="world",
            category="performance",
            title="order_item.order_id is a foreign key without an index, joined on by 2 endpoint(s)",
            summary="GET /api/orders/{id} and GET /api/orders join order_item on order_id; PostgreSQL plans a "
            "sequential scan on 180k rows. An index on order_item(order_id) was measured in the lab.",
            dedup_key="fk-index:order_item.order_id",
            evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
            status=OpportunityStatus.PROPOSED,
            evidence=[
                EvidenceRef(kind="analyzer_report", locator="world:table:order_item", note="catalog read"),
                EvidenceRef(kind="sandbox_run", locator="explain:GET /api/orders/{id}", note="Seq Scan on order_item"),
                EvidenceRef(kind="experiment", locator=exp1.id),
            ],
            details={
                "rev": HEAD,
                "experiment_id": exp1.id,
                "verdict": verdict1,
                "attempts": 1,
                "decision": {
                    "chosen": "propose_change",
                    "reason": "L4 reached: the project's suite passed on both sides and the measurement passed perf-v4",
                    "level": 4,
                },
                "sql": {
                    "query": "SELECT * FROM order_item WHERE order_id = $1",
                    "plan": "Seq Scan on order_item (cost=0.00..3921.00 rows=9 width=48)\n  Filter: (order_id = $1)",
                },
            },
            priority_score=0.82,
            created_at=_at(4),
            updated_at=_at(31),
        ),
        Opportunity(
            id="opp_demo000000000002",
            source="world",
            category="performance",
            title="cart_item.product_id is a foreign key without an index, checked when 1 endpoint(s) delete a product "
            "row",
            summary="DELETE /api/products/{id} checks cart_item.product_id; the table is small (6k rows), the gain "
            "was within noise.",
            dedup_key="fk-index:cart_item.product_id",
            evidence_level=EvidenceLevel.LAB_IMPROVEMENT,
            status=OpportunityStatus.EXPERIMENTING,
            evidence=[
                EvidenceRef(kind="analyzer_report", locator="world:table:cart_item"),
                EvidenceRef(kind="experiment", locator=exp2.id),
            ],
            details={
                "rev": HEAD,
                "experiment_id": exp2.id,
                "verdict": verdict2,
                "attempts": 1,
                "decision": {
                    "chosen": "wait",
                    "reason": "no relevant change at this data size; measured again when the table grows",
                    "level": 3,
                },
            },
            priority_score=0.31,
            created_at=_at(5),
            updated_at=_at(58),
        ),
        Opportunity(
            id="opp_demo000000000003",
            source="robustness",
            category="crash",
            title="split_price('') raises IndexError in storefront/pricing.py",
            summary="A property test over split_price found that the empty string reaches lines[-1] with no lines.",
            dedup_key="crash:split_price:IndexError",
            evidence_level=EvidenceLevel.REPRODUCTION,
            status=OpportunityStatus.OPEN,
            evidence=[
                EvidenceRef(kind="sandbox_run", locator="probe:storefront.pricing", note="hypothesis, 200 examples"),
                EvidenceRef(kind="file", locator="storefront/pricing.py:42"),
            ],
            details={
                "rev": HEAD,
                "attempts": 0,
                "decision": {
                    "chosen": "run_experiment",
                    "reason": "a reproduced crash with a minimal case; a fix is cheap to try",
                    "level": 2,
                },
                "minimal_case": {
                    "language": "python",
                    "code": "from storefront.pricing import split_price\n\n# minimal case, reduced by "
                    'Hypothesis\ntext = ""\nsplit_price(text)\n',
                    "error": "IndexError: list index out of range",
                    "trace": 'File "storefront/pricing.py", line 42, in split_price\n    return lines[-1]',
                },
            },
            priority_score=0.64,
            created_at=_at(9),
            updated_at=_at(9),
        ),
        Opportunity(
            id="opp_demo000000000004",
            source="ruff",
            category="lint",
            title="ruff F401: `os` imported but unused in storefront/legacy.py",
            summary="The project's CI runs ruff only on storefront/api; legacy.py is outside that scope.",
            dedup_key="ruff:F401:storefront/legacy.py",
            evidence_level=EvidenceLevel.REASONABLE_SUSPICION,
            status=OpportunityStatus.DECLINED,
            evidence=[EvidenceRef(kind="analyzer_report", locator="ruff:storefront/legacy.py:3")],
            details={
                "rev": HEAD,
                "decision": {
                    "chosen": "decline",
                    "reason": "outside the CI's lint scope "
                    "(storefront/api only); the team does not run this check here",
                    "level": 1,
                },
            },
            priority_score=0.05,
            created_at=_at(3),
            updated_at=_at(3.5),
        ),
        Opportunity(
            id="opp_demo000000000005",
            source="world",
            category="consistency",
            title="GET /api/products reports a count that may differ from the stored rows",
            summary="The API answers a total of 4,812 products; the catalog counts 4,819 rows. A read of every key is "
            "needed to say which, and the integration for the API is still awaiting approval.",
            dedup_key="consistency:products:count",
            evidence_level=EvidenceLevel.REASONABLE_SUSPICION,
            status=OpportunityStatus.OPEN,
            evidence=[
                EvidenceRef(kind="sandbox_run", locator="http:GET /api/products?limit=1", note="total 4812"),
                EvidenceRef(kind="analyzer_report", locator="sql:SELECT count(*) FROM product", note="4819"),
            ],
            details={
                "rev": HEAD,
                "decision": {
                    "chosen": "wait",
                    "reason": "needs the API integration a person must approve (`unbidden forge approve cap_demo0001`)",
                    "level": 1,
                },
            },
            priority_score=0.4,
            created_at=_at(20),
            updated_at=_at(20),
        ),
        Opportunity(
            id="opp_demo000000000006",
            source="world",
            category="performance",
            title="GET /api/orders issues one query per order item (N+1)",
            summary="The ORM loads items lazily inside the serializer; 1 + n queries per request.",
            dedup_key="n+1:GET /api/orders",
            evidence_level=EvidenceLevel.REASONABLE_SUSPICION,
            status=OpportunityStatus.OPEN,
            evidence=[EvidenceRef(kind="file", locator="storefront/api/orders.py:77")],
            details={
                "rev": HEAD,
                "decision": {"chosen": "run_experiment", "reason": "a cheap lab change", "level": 1},
                "blocked": {
                    "rev": HEAD,
                    "why": "provisioning python dependencies: psycopg needs pg_config from "
                    "deb.debian.org, which the mandate's package registries do not list",
                },
            },
            priority_score=0.55,
            created_at=_at(22),
            updated_at=_at(26),
        ),
    ]
    for o in opps:
        store.put("opportunities", o, key=o.dedup_key)
        event(
            (o.created_at - T0).total_seconds() / 60,
            EventType.OPPORTUNITY_OPENED,
            "director",
            {"title": o.title, "source": o.source, "level": int(o.evidence_level)},
            entity=o.id,
            correlation=o.id,
        )
        d = o.details.get("decision") or {}
        event(
            (o.created_at - T0).total_seconds() / 60 + 0.3,
            EventType.DECISION_MADE,
            "director",
            {"chosen": d.get("chosen"), "reason": d.get("reason"), "level": d.get("level")},
            entity=o.id,
            correlation=o.id,
        )
        store.put(
            "decisions",
            Decision(
                id=f"dec_{o.id[-16:]}",
                opportunity_id=o.id,
                evidence_level=o.evidence_level,
                candidates=[
                    CandidateAction(
                        kind=ActionKind(d.get("chosen", "wait")),
                        p_success=0.6,
                        value=4.0,
                        cost_usd=0.05,
                        risk=0.1,
                        utility=2.2,
                        reason=str(d.get("reason", "")),
                    )
                ],
                chosen=ActionKind(d.get("chosen", "wait")),
                reason=str(d.get("reason", "")),
                decided_at=o.created_at,
            ),
        )
    store.put("experiments", exp1)
    store.put("experiments", exp2)
    event(
        12,
        EventType.EXPERIMENT_STARTED,
        "lab",
        {"experiment": exp1.id, "mode": "served"},
        entity=exp1.id,
        correlation=opps[0].id,
    )
    event(30, EventType.VERDICT_RECORDED, "lab", verdict1, entity=exp1.id, correlation=opps[0].id)
    event(
        40,
        EventType.EXPERIMENT_STARTED,
        "lab",
        {"experiment": exp2.id, "mode": "served"},
        entity=exp2.id,
        correlation=opps[1].id,
    )
    event(57, EventType.VERDICT_RECORDED, "lab", verdict2, entity=exp2.id, correlation=opps[1].id)
    proposal = Proposal(
        id="prop_demo00000000001",
        opportunity_id=opps[0].id,
        experiment_id=exp1.id,
        branch="unbidden/order-item-order-id-index-4f2a",
        base_sha=HEAD,
        commit_sha=COMMIT,
        title="perf: index order_item.order_id · GET /api/orders/{id}: session medians 18.4 -> 11.2 ms (+39% faster)",
        body_md="## Evidence\n\n- the project's suite: 142 passed on both sides, 3 rounds each\n- perf-v4: 4 sessions "
        "per arm, p = 0.014\n\n```sql\nCREATE INDEX CONCURRENTLY ix_order_item_order_id ON order_item (order_id);\n```",
        evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
        status=ProposalStatus.READY,
        created_at=_at(31),
    )
    store.put("proposals", proposal, key=proposal.opportunity_id)
    event(
        31,
        EventType.PROPOSAL_READY,
        "publisher",
        {"title": proposal.title, "branch": proposal.branch},
        entity=proposal.id,
        correlation=opps[0].id,
    )

    # World, connections, needs, blocks ------------------------------------------------------------------------
    world = WorldModel(rev=HEAD, updated_at=_at(8))

    def res(id_: str, kind: Any, name: str, status: str, locator: str, **attrs: Any) -> None:
        world.add(
            Resource(
                id=id_,
                kind=kind,
                name=name,
                status=EpistemicStatus(status),
                confidence=0.9 if status == "observed" else 0.6,
                evidence=[EvidenceRef(kind="config", locator=locator)],
                source="compose-docker@1",
                observed_at=_at(8),
                attributes=attrs,
            )
        )

    def rel(src: str, dst: str, predicate: Any, status: str, locator: str) -> None:
        world.relate(
            Relation(
                src=src,
                dst=dst,
                predicate=predicate,
                status=EpistemicStatus(status),
                confidence=0.9 if status == "observed" else 0.6,
                evidence=[EvidenceRef(kind="file", locator=locator)],
                source="compose-docker@1",
                observed_at=_at(8),
            )
        )

    res("repo:storefront-web", "repo", "storefront-web", "observed", "git", languages=["python"])
    res("service:api", "service", "api", "observed", "docker-compose.yml:3", port=8001)
    res("service:db", "service", "db", "observed", "docker-compose.yml:18", image="postgres:16")
    res("database:shop", "database", "shop", "observed", "pg_catalog", tables=12)
    res("table:order", "table", "order", "observed", "pg_catalog", rows=20_000)
    res("table:order_item", "table", "order_item", "observed", "pg_catalog", rows=180_000)
    res("table:product", "table", "product", "observed", "pg_catalog", rows=4_819)
    res("table:cart_item", "table", "cart_item", "observed", "pg_catalog", rows=6_100)
    res("endpoint:GET /api/orders/{id}", "endpoint", "GET /api/orders/{id}", "observed", "openapi.json")
    res("endpoint:GET /api/products", "endpoint", "GET /api/products", "observed", "openapi.json")
    res("ci_job:test-backend", "ci_job", "test-backend", "observed", ".github/workflows/test.yml")
    res("metrics:prometheus", "metrics", "prometheus", "inferred", "docker-compose.yml:41")
    rel("service:api", "service:db", "depends_on", "observed", "docker-compose.yml:9")
    rel("service:api", "database:shop", "uses_database", "observed", "storefront/db.py:12")
    rel("service:api", "endpoint:GET /api/orders/{id}", "serves", "observed", "storefront/api/orders.py:31")
    rel("service:api", "endpoint:GET /api/products", "serves", "observed", "storefront/api/products.py:18")
    rel("endpoint:GET /api/orders/{id}", "table:order", "reads", "observed", "storefront/api/orders.py:40")
    rel("endpoint:GET /api/orders/{id}", "table:order_item", "reads", "observed", "storefront/api/orders.py:44")
    rel("endpoint:GET /api/products", "table:product", "reads", "observed", "storefront/api/products.py:22")
    rel("database:shop", "table:order_item", "defines", "observed", "pg_catalog")
    rel("ci_job:test-backend", "repo:storefront-web", "tests", "observed", ".github/workflows/test.yml:14")
    rel("metrics:prometheus", "service:api", "reads", "inferred", "docker-compose.yml:44")
    store.put("world", world)
    event(
        8, EventType.WORLD_CHANGED, "world", {"diff": {"n_added": 12, "n_carried": 0}, "blind_spots": 1}, entity="world"
    )
    connections = [
        Connection(
            id="compose:compose",
            project="storefront-web",
            kind="compose",
            protocol="docker",
            location="compose",
            environment=Environment.LOCAL,
            discovered_by=["the map's compose connector"],
            abilities=[Ability(kind="read", operations=["ps", "inspect", "logs"], known_by="checked: docker ps")],
            state=ConnectionState.CONNECTED,
            checked_at=_at(7),
            effective=["read"],
        ),
        Connection(
            id="postgres:127.0.0.1:5433/shop",
            project="storefront-web",
            kind="postgres",
            protocol="postgres",
            location="127.0.0.1:5433/shop",
            environment=Environment.LOCAL,
            grant="shop-db",
            credential_ref="SHOP_DB_RO",
            discovered_by=["docker-compose.yml:18"],
            requested=["read"],
            effective=["read"],
            abilities=[
                Ability(
                    kind="read", operations=["schema", "explain", "count"], known_by="checked: SELECT on pg_catalog"
                )
            ],
            state=ConnectionState.CONNECTED,
            checked_at=_at(7),
        ),
        Connection(
            id="http_api:http://127.0.0.1:8001",
            project="storefront-web",
            kind="http_api",
            protocol="http",
            location="http://127.0.0.1:8001",
            environment=Environment.LOCAL,
            grant="shop-api",
            discovered_by=["docker-compose.yml:3"],
            requested=["read"],
            state=ConnectionState.NEEDS_CAPABILITY,
            checked_at=_at(7),
            capability_id=None,
            next_step="approve the API client Forge built (`unbidden forge approve cap_demo0001`)",
        ),
        Connection(
            id="github:acme/storefront-web",
            project="storefront-web",
            kind="github",
            protocol="https",
            location="acme/storefront-web",
            environment=Environment.PRODUCTION,
            discovered_by=["git remote origin"],
            state=ConnectionState.DISCOVERED,
            next_step="set egress.github.repository to acme/storefront-web to read its checks",
        ),
    ]
    for c in connections:
        store.put("connections", c)
        event(7, EventType.CONNECTION_CHANGED, "connect", {"state": c.state.value, "kind": c.kind}, entity=c.id)
    need = CapabilityNeed(
        id="need_demo0000000001",
        kind="api_client",
        source="http_api:http://127.0.0.1:8001",
        why="read GET /api/products completely to compare its count with the stored rows",
        status=NeedStatus.AWAITING_APPROVAL,
        capability_id="cap_demo0001",
        attempts=1,
        purposes=["consistency of /api/products"],
        notes=["built and validated by the oracle: 200 of 200 records read"],
        created_at=_at(21),
        updated_at=_at(27),
    )
    store.put("needs", need)
    event(
        21,
        EventType.CAPABILITY_NEEDED,
        "director",
        {"kind": need.kind, "source": need.source},
        entity=need.id,
        correlation=opps[4].id,
    )
    event(27, EventType.CAPABILITY_BUILT, "forge", {"capability": "cap_demo0001", "oracle": "200/200"}, entity=need.id)
    block = Block(
        id="blk_demo0000000001",
        operation="provision python dependencies for an experiment on opp_demo000000000006",
        kind="pending_person",
        evidence="error: pg_config executable not found; the build needs libpq-dev from "
        "deb.debian.org, which the mandate's package registries do not list",
        needs="add deb.debian.org to egress.package_registries (system build tools: a compiler and the C headers a "
        "package builds against)",
        continues="the experiment on GET /api/orders (N+1)",
        at=_at(26),
        waiting=["lab.experiment opp_demo000000000006"],
        jobs=["job_demo1"],
    )
    store.put(BLOCKS, block)
    event(
        26,
        EventType.POLICY_DENIED,
        "guardian",
        {
            "rule": "egress.package_registries",
            "reasons": ["destination deb.debian.org is not in the mandate's allowlist"],
            "purpose": "sandbox.provision",
        },
        correlation=opps[5].id,
    )

    # Deploys and probes --------------------------------------------------------------------------------------
    for index, commit, minute, status in ((1, BASE, 60, "verified"), (2, COMMIT, 120, "verified")):
        dep = Deployment(
            id=str(index),
            index=index,
            environment="local",
            commit=commit,
            commit_status=status,  # type: ignore[arg-type]
            commit_reason="built by Unbidden's own deploy steps"
            if index == 2
            else "built from the checkout at the first observation",
            initiated_by="unbidden" if index == 2 else "external",
            seen_at=_at(minute),
            containers=[
                RunningContainer(
                    service="api",
                    container_id=f"c{index}a",
                    name=f"storefront-api-{index}",
                    image_id=f"sha256:{index:02d}" + "ab" * 10,
                    started_at=_at(minute).isoformat(),
                    revision_label=commit,
                )
            ],
        )
        store.put("deployments", dep)
        event(
            minute,
            EventType.DEPLOYMENT_OBSERVED,
            "operate",
            {"index": index, "commit": commit[:12], "commit_status": status},
            entity=dep.id,
        )
    store.set_value("deploy_sequence", 2)
    for i in range(60):
        deploy = 1 if i < 30 else 2
        centre = 18.4 if deploy == 1 else 11.2
        lat = _samples(rng, centre, centre * 0.07, 5)
        st = [200] * 5 if rng.random() > 0.05 else [200, 200, 503, 200, 200]
        store._conn.execute(
            "INSERT INTO rounds (ts, target, version, statuses, latencies, deploy) VALUES (?, ?, ?, ?, ?, ?)",
            (
                _at(62 + i * 2).isoformat(),
                "GET /api/orders/{id}",
                BASE if deploy == 1 else COMMIT,
                json.dumps(st),
                json.dumps(lat),
                deploy,
            ),
        )
        store._conn.execute(
            "INSERT INTO rounds (ts, target, version, statuses, latencies, deploy) VALUES (?, ?, ?, ?, ?, ?)",
            (
                _at(62 + i * 2).isoformat(),
                "GET /api/products",
                BASE if deploy == 1 else COMMIT,
                json.dumps([200] * 5),
                json.dumps(_samples(rng, 9.0, 0.6, 5)),
                deploy,
            ),
        )
    event(
        126,
        EventType.ANOMALY_DETECTED,
        "observer",
        {
            "kind": "latency",
            "why": "p95 of GET /api/products 9.1 -> 14.8 ms over 8 requests",
            "criteria_version": "health-v1",
        },
        entity="service:api",
    )
    event(
        134,
        EventType.ANOMALY_RESOLVED,
        "observer",
        {"kind": "latency", "why": "back under the baseline for 8 requests"},
        entity="service:api",
    )
    store.set_value("open_anomalies", {})

    # Model calls and spend -------------------------------------------------------------------------------------
    spend_rows: list[dict[str, Any]] = []
    calls = [
        ("research.step", Tier.LOCAL, "ollama", "muse-glimmer:30b-mxfp8-dflash", 1800, 240, 0.0, 10),
        ("lab.workload", Tier.CODE, "meta", "muse-spark-1.3", 6200, 900, 0.0116, 13),
        ("lab.perf_candidate", Tier.CODE, "meta", "muse-spark-1.3", 7400, 1100, 0.0139, 15),
        ("research.step", Tier.LOCAL, "ollama", "muse-glimmer:30b-mxfp8-dflash", 2100, 300, 0.0, 23),
        ("forge.api_client", Tier.CODE, "meta", "muse-spark-1.3", 9100, 1800, 0.0190, 24),
        ("forge.tests", Tier.LOCAL, "ollama", "muse-glimmer:30b-mxfp8-dflash", 2500, 600, 0.0, 25),
        ("lab.workload", Tier.CODE, "meta", "muse-spark-1.3", 5900, 800, 0.0108, 41),
        ("lab.perf_candidate", Tier.CODE, "meta", "muse-spark-1.3", 7100, 1000, 0.0131, 43),
        ("research.robustness", Tier.CODE, "meta", "muse-spark-1.3", 4800, 1300, 0.0115, 9),
        ("director.goal_plan", Tier.LOCAL, "ollama", "muse-glimmer:30b-mxfp8-dflash", 3000, 400, 0.0, 20),
    ]
    for i, (purpose, tier, provider, model, tin, tout, usd, minute) in enumerate(calls):
        run = ModelRun(
            id=f"run_demo{i:013d}",
            purpose=purpose,
            tier=tier,
            provider=provider,
            model=model,
            attempt=1,
            ok=True,
            usage=Usage(prompt_tokens=tin, completion_tokens=tout, duration_s=4.0 + i),
            cost=Cost(tokens_in=tin, tokens_out=tout, usd_remote=usd, usd_local=0.0 if tier.remote else 0.0006),
            route_reason=f"profile local-first; {purpose} is {'heavy' if tier.remote else 'light'}",
            created_at=_at(minute),
        )
        store.put("model_runs", run)
        event(
            minute,
            EventType.MODEL_CALLED,
            "brain",
            {
                "purpose": purpose,
                "tier": tier.value,
                "model": model,
                "attempt": 1,
                "ok": True,
                "tokens_in": tin,
                "tokens_out": tout,
                "usd": usd,
            },
            entity=run.id,
        )
        if tier.remote:
            event(
                minute - 0.1,
                EventType.EGRESS_ALLOWED,
                "brain",
                {"purpose": purpose, "destination": "api.meta.ai", "bytes": tin * 4, "reasons": []},
            )
            spend_rows.append(
                {
                    "id": f"spend_demo{i}",
                    "created_at": _at(minute).isoformat(),
                    "workspace": "storefront-web",
                    "run": "demo-run-1" if minute < 30 else "demo-run-2",
                    "purpose": purpose,
                    "provider": provider,
                    "model": model,
                    "attempt": 1,
                    "status": "settled",
                    "est_usd": usd * 3,
                    "usd": usd,
                    "charged": usd,
                    "tokens_in": tin,
                    "tokens_out": tout,
                    "usage_reported": 1,
                    "envelope": "demo",
                }
            )
    for e in sorted(ev, key=lambda e: e.ts):
        store.append_event(e)
    return spend_rows, _at(140)
