"""Connections in the World Model: repository → service → database / API, with evidence, time and confidence.

Facts here carry the source `connections@1`, so reconcile treats them like any connector's: seen again, refreshed;
not seen, obsolete. A connection a check reached is `observed`, with the check as evidence; one only named in
configuration is `inferred` (confidence 0.5): the map says what is known about it and how.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from unbidden.contracts.common import EpistemicStatus, EvidenceRef, utc_now
from unbidden.contracts.connection import USABLE, Connection
from unbidden.contracts.world import Relation, Resource, ResourceKind, WorldModel
from unbidden.store import Store

SOURCE = "connections@1"
KIND: dict[str, ResourceKind] = {
    "postgres": "database",
    "http_api": "api",
    "github": "repo",
    "prometheus": "metrics",
    "jaeger": "metrics",
    "compose": "service",
}
STALE_AFTER = timedelta(hours=6)  # a check older than this no longer stands for the connection's state


def add_to_world(store: Store, repo: Path, connections: list[Connection]) -> WorldModel:
    world = store.get("world", "world", WorldModel) or WorldModel(rev="HEAD")
    world.resources = {k: v for k, v in world.resources.items() if v.source != SOURCE}
    world.relations = [r for r in world.relations if r.source != SOURCE]
    now = utc_now()
    repo_id = f"repo:{repo.name}"
    if repo_id not in world.resources:
        world.add(
            Resource(
                id=repo_id,
                kind="repo",
                name=repo.name,
                status=EpistemicStatus.OBSERVED,
                confidence=1.0,
                evidence=[EvidenceRef(kind="config", locator=str(repo))],
                source=SOURCE,
            )
        )
    for conn in connections:
        if conn.kind == "compose":
            continue
        checked = conn.state in USABLE and conn.checked_at is not None
        evidence = [EvidenceRef(kind="config", locator=e) for e in conn.discovered_by[:3]] or [
            EvidenceRef(kind="config", locator=conn.id)
        ]
        if checked:
            evidence.append(
                EvidenceRef(
                    kind="config", locator=f"check {conn.checked_at:%Y-%m-%d %H:%M}", note=conn.check_detail[:200]
                )
            )
        kind: ResourceKind = KIND.get(conn.kind, "service")
        rid = f"{kind}:{conn.id}"
        world.add(
            Resource(
                id=rid,
                kind=kind,
                name=conn.location,
                attributes={
                    "connection": conn.id,
                    "state": conn.state.value,
                    "environment": conn.environment.value,
                    "effective": conn.effective,
                    "granted": conn.requested,
                    "can_read": conn.can("read") or conn.can("measure"),
                    "can_write": conn.can("write"),
                },
                status=EpistemicStatus.OBSERVED if checked else EpistemicStatus.INFERRED,
                confidence=1.0 if checked else 0.5,
                evidence=evidence,
                source=SOURCE,
                environment=conn.environment.value,
                expires_at=(conn.checked_at + STALE_AFTER) if checked and conn.checked_at else None,
            )
        )
        for found in conn.discovered_by:
            service = found.split(" service ", 1)[1].split()[0] if " service " in found else None
            if service is None:
                continue
            sid = f"service:{service}"
            if sid not in world.resources:
                world.add(
                    Resource(
                        id=sid,
                        kind="service",
                        name=service,
                        status=EpistemicStatus.OBSERVED,
                        confidence=1.0,
                        evidence=[EvidenceRef(kind="config", locator=found)],
                        source=SOURCE,
                    )
                )
                world.relate(
                    Relation(
                        src=repo_id,
                        dst=sid,
                        predicate="defines",
                        status=EpistemicStatus.OBSERVED,
                        confidence=1.0,
                        evidence=[EvidenceRef(kind="config", locator=found)],
                        source=SOURCE,
                    )
                )
            world.relate(
                Relation(
                    src=sid,
                    dst=rid,
                    predicate="connects_to",
                    status=EpistemicStatus.INFERRED,
                    confidence=0.8,
                    evidence=[EvidenceRef(kind="config", locator=found)],
                    source=SOURCE,
                    observed_at=now,
                )
            )
    store.put("world", world)
    return world
