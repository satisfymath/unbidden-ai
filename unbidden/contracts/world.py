from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from unbidden.contracts.common import Contract, EpistemicStatus, EvidenceRef, utc_now

ResourceKind = Literal["repo", "service", "container", "database", "table", "endpoint", "ci_job", "model"]


class Resource(Contract):
    """A thing in the observed system. Every resource says how it is known and from what evidence."""

    id: str  # stable, readable: "service:db", "table:item", "endpoint:GET /api/v1/items/"
    kind: ResourceKind
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: EpistemicStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)


class Relation(Contract):
    src: str
    dst: str
    predicate: Literal[
        "depends_on", "uses_database", "reads", "writes", "serves", "defines", "tests", "references", "runs"
    ]
    status: EpistemicStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)


class BlindSpot(Contract):
    what: str
    why: str


class WorldModel(Contract):
    id: str = "world"
    rev: str
    resources: dict[str, Resource] = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list[Relation])
    blind_spots: list[BlindSpot] = Field(default_factory=list[BlindSpot])
    updated_at: datetime = Field(default_factory=utc_now)

    def add(self, resource: Resource) -> None:
        """Keep the best-known version: an observation replaces an inference, never the reverse."""
        current = self.resources.get(resource.id)
        rank = {EpistemicStatus.OBSERVED: 3, EpistemicStatus.VERIFIED: 3, EpistemicStatus.INFERRED: 2,
                EpistemicStatus.HYPOTHESIS: 1, EpistemicStatus.OBSOLETE: 0}  # fmt: skip
        if current is None or rank[resource.status] >= rank[current.status]:
            if current is not None:
                resource = resource.model_copy(
                    update={
                        "attributes": {**current.attributes, **resource.attributes},
                        "evidence": [*current.evidence, *resource.evidence][-6:],
                    }
                )
            self.resources[resource.id] = resource

    def relate(self, relation: Relation) -> None:
        key = (relation.src, relation.dst, relation.predicate)
        self.relations = [r for r in self.relations if (r.src, r.dst, r.predicate) != key] + [relation]

    def of_kind(self, kind: ResourceKind) -> list[Resource]:
        return sorted((r for r in self.resources.values() if r.kind == kind), key=lambda r: r.id)
