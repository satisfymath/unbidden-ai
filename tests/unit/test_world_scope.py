from __future__ import annotations

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import BlindSpot, Relation, Resource, WorldModel
from unbidden.world.scope import scope

pytestmark = pytest.mark.unit
OBS, INF = EpistemicStatus.OBSERVED, EpistemicStatus.INFERRED


def add(w: WorldModel, rid: str, status: EpistemicStatus = OBS, kind: str = "", **attrs: object) -> None:
    prefix, name = rid.split(":", 1)
    kind = kind or prefix
    w.add(
        Resource(
            id=rid,
            kind=kind,  # type: ignore[arg-type]
            name=name,
            attributes=dict(attrs),
            status=status,
            confidence=1.0,
            evidence=[EvidenceRef(kind="config", locator=rid)],
            source="test@1",
        )
    )


def link(w: WorldModel, src: str, predicate: str, dst: str, status: EpistemicStatus = OBS) -> None:
    w.relate(
        Relation(
            src=src,
            dst=dst,
            predicate=predicate,  # type: ignore[arg-type]
            status=status,
            confidence=0.6 if status is INF else 1.0,
            evidence=[EvidenceRef(kind="file", locator=f"{src}->{dst}")],
            source="test@1",
        )
    )


@pytest.fixture
def world() -> WorldModel:
    w = WorldModel(rev="r")
    add(w, "endpoint:GET /items/")
    add(w, "service:backend")
    add(w, "service:worker")
    add(w, "service:db", kind="database")
    add(w, "container:fst-backend-1")
    add(w, "image:5b90bcb9b7af")
    add(w, "deployment:3", commit="a" * 40, commit_status="inferred", commit_reason="HEAD when first seen")
    add(w, "table:item", INF)
    add(w, "table:user")
    link(w, "service:backend", "serves", "endpoint:GET /items/")
    link(w, "container:fst-backend-1", "runs", "service:backend")
    link(w, "container:fst-backend-1", "runs_image", "image:5b90bcb9b7af")
    link(w, "deployment:3", "deploys", "service:backend")
    link(w, "endpoint:GET /items/", "reads", "table:item", INF)
    link(w, "service:backend", "uses_database", "service:db")
    link(w, "service:worker", "uses_database", "service:db")
    link(w, "service:db", "defines", "table:user")
    w.blind_spots.append(BlindSpot(what="endpoints of worker", why="no OpenAPI"))
    return w


def test_an_endpoint_leads_to_its_service_container_deploy_image_and_tables(world: WorldModel) -> None:
    s = scope(world, "endpoint:GET /items/")
    ids = {r.id: r.hops for r in s.resources}
    assert ids["service:backend"] == 1 and ids["table:item"] == 1
    assert ids["container:fst-backend-1"] == 2 and ids["deployment:3"] == 2 and ids["image:5b90bcb9b7af"] == 3
    assert all(r.source == "test@1" for r in s.resources)


def test_a_shared_database_does_not_pull_in_every_other_service_that_uses_it(world: WorldModel) -> None:
    ids = {r.id for r in scope(world, "endpoint:GET /items/").resources}
    assert "service:db" in ids and "service:worker" not in ids


def test_what_cannot_be_seen_is_listed_not_guessed(world: WorldModel) -> None:
    gaps = {b.what: b.why for b in scope(world, "endpoint:GET /items/").blind_spots}
    assert "HEAD when first seen" in gaps["code running in deployment:3"]
    assert "metrics" in gaps and "traces" in gaps
    assert any("inferred from code" in why for why in gaps.values())
    assert "endpoints of worker" not in gaps


def test_an_unknown_root_says_so() -> None:
    s = scope(WorldModel(rev="r"), "endpoint:GET /nope")
    assert not s.found and s.resources == []
