from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from unbidden.contracts.common import Contract, EpistemicStatus, EvidenceRef, utc_now

ResourceKind = Literal[
    "repo", "service", "container", "database", "table", "endpoint", "ci_job", "model", "deployment", "image"
]
Predicate = Literal[
    "depends_on",
    "uses_database",
    "reads",
    "writes",
    "serves",
    "defines",
    "tests",
    "references",
    "runs",
    "calls",
    "deploys",
    "runs_image",
]


class Fact(Contract):
    """Where a piece of knowledge comes from and for how long it holds.

    `source` is the connector that produced it (`compose-docker@1`); `valid_for` the code revision or deploy it
    describes; `obsolete_since` is set when the source that produced it ran again and no longer saw it.
    """

    status: EpistemicStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(min_length=1)
    source: str | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    environment: str = "local"
    valid_for: str | None = None
    expires_at: datetime | None = None
    obsolete_since: datetime | None = None


class Resource(Fact):
    """A thing in the observed system. Every resource says how it is known and from what evidence."""

    id: str  # stable, readable: "service:db", "table:item", "endpoint:GET /api/v1/items/"
    kind: ResourceKind
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class Relation(Fact):
    src: str
    dst: str
    predicate: Predicate

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.src, self.dst, self.predicate)


class BlindSpot(Contract):
    what: str
    why: str


CommitStatus = Literal["verified", "observed", "inferred", "unknown"]


class RunningContainer(Contract):
    service: str
    container_id: str
    name: str
    image_id: str
    image_created: str | None = None
    started_at: str | None = None
    revision_label: str | None = None  # org.opencontainers.image.revision, when the image carries it
    repo_digest: str | None = None  # set when the image was pulled from a registry rather than built here


class Deployment(Contract):
    """One set of running containers of the project, and what is known about the code it runs.

    `commit_status` says how the commit is known: `verified` when Unbidden ran the deploy steps and the images
    were built or the containers started inside that deploy; `observed` from an image revision label;
    `inferred` from the checkout's HEAD when first seen; `unknown` otherwise. A deploy's id is its index in the
    sequence, so a version deployed again is a deploy of its own.
    """

    id: str  # "3"
    index: int
    environment: str
    containers: list[RunningContainer]
    commit: str | None
    commit_status: CommitStatus
    commit_reason: str
    initiated_by: Literal["unbidden", "external", "unknown"]
    seen_at: datetime = Field(default_factory=utc_now)


class ConnectorSpec(Contract):
    """What a connector can learn, what it may change, what it needs and what it costs."""

    id: str
    version: int
    purpose: str
    discovers: list[str]
    measures: list[str] = Field(default_factory=list)
    modifies: list[str] = Field(default_factory=list)
    capability: str  # the Guardian capability every read goes through
    read_only: bool = True
    cost: str
    scope: str

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


RANK = {EpistemicStatus.OBSERVED: 3, EpistemicStatus.VERIFIED: 3, EpistemicStatus.INFERRED: 2,
        EpistemicStatus.HYPOTHESIS: 1, EpistemicStatus.OBSOLETE: 0}  # fmt: skip


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
        if current is None or RANK[resource.status] >= RANK[current.status]:
            if current is not None:
                resource = resource.model_copy(
                    update={
                        "attributes": {**current.attributes, **resource.attributes},
                        "evidence": [*current.evidence, *resource.evidence][-6:],
                    }
                )
            self.resources[resource.id] = resource

    def relate(self, relation: Relation) -> None:
        current = next((r for r in self.relations if r.key == relation.key), None)
        if current is not None and RANK[relation.status] < RANK[current.status]:
            return
        self.relations = [r for r in self.relations if r.key != relation.key] + [relation]

    def of_kind(self, kind: ResourceKind) -> list[Resource]:
        return sorted(
            (r for r in self.resources.values() if r.kind == kind and r.status is not EpistemicStatus.OBSOLETE),
            key=lambda r: r.id,
        )

    def current_relations(self) -> list[Relation]:
        return [r for r in self.relations if r.status is not EpistemicStatus.OBSOLETE]

    def stamp(self, source: str, *, valid_for: str | None = None, environment: str | None = None) -> None:
        """Attribute every fact that has no source yet to `source` (a connector that just ran)."""
        for fact in [*self.resources.values(), *self.relations]:
            if fact.source is None:
                fact.source = source
                if valid_for is not None and fact.valid_for is None:
                    fact.valid_for = valid_for
                if environment is not None:
                    fact.environment = environment
