"""The scope of a resource: what it is connected to, how each link is known, and what cannot be seen from it.

Used to explain an anomaly before anyone touches the system: a degraded endpoint leads to its service, the
containers and deploy that serve it, the code version they hold, the tables it reads and the services it calls.
Each fact keeps its status, source and age; what no connector covers is listed rather than guessed.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, EpistemicStatus, utc_now
from unbidden.contracts.world import BlindSpot, Fact, Relation, WorldModel
from unbidden.world.connectors import NOT_COVERED

DEFAULT_DEPTH = 3


class ScopeFact(Contract):
    id: str
    what: str  # a resource kind, or a relation predicate
    status: str
    confidence: float
    source: str | None
    observed_at: datetime
    age_s: int
    valid_for: str | None
    hops: int
    evidence: list[str]
    attributes: dict[str, Any] = Field(default_factory=dict)


class Scope(Contract):
    root: str
    found: bool
    resources: list[ScopeFact] = Field(default_factory=list)
    relations: list[ScopeFact] = Field(default_factory=list)
    blind_spots: list[BlindSpot] = Field(default_factory=list)

    def chain(self, kinds: tuple[str, ...] = ("endpoint", "service", "container", "deployment", "image")) -> list[str]:
        return [f"{r.id} ({r.status})" for r in sorted(self.resources, key=lambda r: r.hops) if r.what in kinds]

    def brief(self) -> dict[str, Any]:
        """What travels with an incident: the components and the gaps, not every attribute."""
        return {
            "root": self.root,
            "components": [
                {"id": r.id, "status": r.status, "source": r.source, "hops": r.hops, "age_s": r.age_s}
                for r in self.resources
            ][:40],
            "deployment": next(
                (
                    {k: r.attributes.get(k) for k in ("commit", "commit_status", "commit_reason", "initiated_by")}
                    for r in self.resources
                    if r.what == "deployment"
                ),
                None,
            ),
            "blind_spots": [f"{b.what}: {b.why}" for b in self.blind_spots],
        }


def _fact(fid: str, what: str, fact: Fact, hops: int, now: datetime, attributes: dict[str, Any]) -> ScopeFact:
    return ScopeFact(
        id=fid,
        what=what,
        status=fact.status.value,
        confidence=fact.confidence,
        source=fact.source,
        observed_at=fact.observed_at,
        age_s=max(0, int((now - fact.observed_at).total_seconds())),
        valid_for=fact.valid_for,
        hops=hops,
        evidence=[e.locator for e in fact.evidence][-3:],
        attributes=attributes,
    )


USERS_OF = ("uses_database", "reads", "writes", "depends_on", "calls")


def _peer(world: WorldModel, node: str, relation: Relation) -> bool:
    """A link that leads from a component of the scope to its peers rather than to what it rests on: other users of
    a shared data store or service, or the other endpoints a service serves. Not followed past the root."""
    resource = world.resources.get(node)
    if resource is None:
        return False
    if relation.dst == node and relation.predicate in USERS_OF:
        return True
    return relation.src == node and relation.predicate == "serves"


def scope(world: WorldModel, root: str, *, depth: int = DEFAULT_DEPTH, now: datetime | None = None) -> Scope:
    now = now or utc_now()
    if root not in world.resources:
        return Scope(
            root=root,
            found=False,
            blind_spots=[BlindSpot(what=root, why="not in the World Model (never observed, or a different id)")],
        )
    live = world.current_relations()
    hops = {root: 0}
    queue = deque([root])
    used: list[tuple[int, Relation]] = []
    while queue:
        node = queue.popleft()
        if hops[node] >= depth:
            continue
        for relation in live:
            if node not in (relation.src, relation.dst):
                continue
            other = relation.dst if relation.src == node else relation.src
            if hops[node] > 0 and _peer(world, node, relation):
                continue
            used.append((hops[node], relation))
            if other not in hops:
                hops[other] = hops[node] + 1
                queue.append(other)

    result = Scope(root=root, found=True)
    for rid, distance in sorted(hops.items(), key=lambda kv: (kv[1], kv[0])):
        resource = world.resources.get(rid)
        if resource is None:
            result.blind_spots.append(BlindSpot(what=rid, why="referenced by a relation but never observed itself"))
            continue
        result.resources.append(_fact(rid, resource.kind, resource, distance, now, resource.attributes))
    seen: set[tuple[str, str, str]] = set()
    for distance, relation in used:
        if relation.key in seen:
            continue
        seen.add(relation.key)
        label = f"{relation.src} -{relation.predicate}-> {relation.dst}"
        result.relations.append(_fact(label, relation.predicate, relation, distance, now, {}))

    names = {r.name for rid in hops if (r := world.resources.get(rid)) is not None}
    result.blind_spots.extend(b for b in world.blind_spots if any(n and n in b.what for n in names))
    for fact in result.resources:
        if fact.what == "deployment" and fact.attributes.get("commit_status") not in ("verified", "observed"):
            result.blind_spots.append(
                BlindSpot(
                    what=f"code running in {fact.id}",
                    why=f"commit {fact.attributes.get('commit_status')}: {fact.attributes.get('commit_reason')}",
                )
            )
    inferred_links = [r for r in result.relations if r.status == EpistemicStatus.INFERRED.value]
    if inferred_links:
        result.blind_spots.append(
            BlindSpot(
                what=f"{len(inferred_links)} link(s) in this scope",
                why="inferred from code or configuration, never seen in traffic: "
                + ", ".join(r.id for r in inferred_links[:4]),
            )
        )
    result.blind_spots.extend(BlindSpot(what=k, why=v) for k, v in NOT_COVERED.items())
    return result
