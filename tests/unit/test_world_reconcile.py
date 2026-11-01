from __future__ import annotations

from datetime import timedelta

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef, utc_now
from unbidden.contracts.world import Relation, Resource, WorldModel
from unbidden.world.reconcile import KEEP_OBSOLETE, reconcile

pytestmark = pytest.mark.unit
DOCKER, STATIC = "compose-docker@1", "git-static@1"
OBS = EpistemicStatus.OBSERVED


def res(rid: str, source: str, **attrs: object) -> Resource:
    kind = rid.split(":", 1)[0]
    return Resource(
        id=rid,
        kind=kind,  # type: ignore[arg-type]
        name=rid.split(":", 1)[1],
        attributes=dict(attrs),
        status=OBS,
        confidence=1.0,
        evidence=[EvidenceRef(kind="config", locator=rid)],
        source=source,
    )


def rel(src: str, dst: str, source: str) -> Relation:
    return Relation(
        src=src,
        dst=dst,
        predicate="runs",
        status=OBS,
        confidence=1.0,
        evidence=[EvidenceRef(kind="config", locator=src)],
        source=source,
    )


def world(*facts: Resource | Relation) -> WorldModel:
    w = WorldModel(rev="r")
    for f in facts:
        w.add(f) if isinstance(f, Resource) else w.relate(f)
    return w


def test_a_container_the_docker_connector_no_longer_sees_becomes_obsolete_not_observed() -> None:
    before = world(
        res("service:api", STATIC), res("container:api-1", DOCKER), rel("container:api-1", "service:api", DOCKER)
    )
    after = world(res("service:api", STATIC))
    merged, diff = reconcile(before, after, {DOCKER, STATIC})
    gone = merged.resources["container:api-1"]
    assert gone.status is EpistemicStatus.OBSOLETE and gone.obsolete_since is not None
    assert "container:api-1" in diff.obsoleted
    assert merged.of_kind("container") == []  # obsolete facts are kept, never served as current
    assert all(r.status is EpistemicStatus.OBSOLETE for r in merged.relations)


def test_facts_of_a_source_that_did_not_run_are_carried_with_their_age() -> None:
    seen = utc_now() - timedelta(hours=3)
    old = res("container:api-1", DOCKER)
    old.observed_at = seen
    merged, diff = reconcile(world(old), world(), {STATIC})  # docker did not run (nothing running, or not allowed)
    kept = merged.resources["container:api-1"]
    assert kept.status is OBS and kept.observed_at == seen
    assert diff.carried == ["container:api-1"] and diff.obsoleted == []


def test_added_changed_and_revived_are_reported() -> None:
    first, _ = reconcile(None, world(res("service:api", STATIC, image="a")), {STATIC})
    second, diff = reconcile(first, world(res("service:api", STATIC, image="b"), res("service:db", STATIC)), {STATIC})
    assert diff.added == ["service:db"] and diff.changed == ["service:api"]
    third, _ = reconcile(second, world(res("service:api", STATIC, image="b")), {STATIC})
    assert third.resources["service:db"].status is EpistemicStatus.OBSOLETE
    fourth, diff = reconcile(third, world(res("service:api", STATIC, image="b"), res("service:db", STATIC)), {STATIC})
    assert diff.revived == ["service:db"] and fourth.resources["service:db"].status is OBS


def test_expired_facts_become_obsolete_and_old_obsolete_ones_are_dropped() -> None:
    now = utc_now()
    expiring = res("container:x", DOCKER)
    expiring.expires_at = now - timedelta(seconds=1)
    ancient = res("container:y", DOCKER)
    ancient.status = EpistemicStatus.OBSOLETE
    ancient.obsolete_since = now - KEEP_OBSOLETE - timedelta(seconds=1)
    merged, _ = reconcile(world(expiring, ancient), world(), set(), now=now)
    assert merged.resources["container:x"].status is EpistemicStatus.OBSOLETE
    assert "container:y" not in merged.resources


def test_facts_from_before_sources_were_recorded_are_judged_by_what_ran() -> None:
    legacy = res("container:api-1", DOCKER)
    legacy.source = None
    merged, _ = reconcile(world(legacy), world(), {STATIC})
    assert merged.resources["container:api-1"].status is EpistemicStatus.OBSOLETE


def test_model_inferred_links_from_before_sources_survive_a_map_without_the_model() -> None:
    legacy = Relation(
        src="endpoint:GET /items/",
        dst="table:item",
        predicate="reads",
        status=EpistemicStatus.INFERRED,
        confidence=0.6,
        evidence=[EvidenceRef(kind="file", locator="items.py:3")],
    )
    merged, diff = reconcile(world(legacy), world(), {STATIC, DOCKER})
    assert merged.relations[0].status is EpistemicStatus.INFERRED and diff.obsoleted == []
