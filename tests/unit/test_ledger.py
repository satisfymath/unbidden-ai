from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from unbidden.contracts.world import RunningContainer
from unbidden.operate import ledger
from unbidden.store import Store

pytestmark = pytest.mark.unit
A, B = "a" * 40, "b" * 40
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def inspected(cid: str, project: str, service: str, image: str, started: str, **labels: str) -> dict[str, Any]:
    return {
        "Id": cid,
        "Name": f"/{project}-{service}-1",
        "Image": image,
        "State": {"StartedAt": started},
        "Config": {"Labels": {"com.docker.compose.project": project, "com.docker.compose.service": service, **labels}},
    }


def container(cid: str, image: str, created: datetime | None, label: str | None = None) -> RunningContainer:
    return RunningContainer(
        service="backend",
        container_id=cid,
        name=f"fst-backend-{cid}",
        image_id=image,
        image_created=created.isoformat() if created else None,
        started_at=None,
        revision_label=label,
    )


def test_docker_timestamps_with_nanoseconds_and_offsets_parse() -> None:
    assert ledger.parse_ts("2026-10-27T01:29:07.723889263Z") == datetime(2026, 10, 27, 1, 29, 7, 723889, tzinfo=UTC)
    parsed = ledger.parse_ts("2026-10-26T21:15:24.543943617-03:00")
    assert parsed is not None and parsed.astimezone(UTC).hour == 0
    assert ledger.parse_ts("0001-01-01T00:00:00Z") is None


def test_a_container_of_another_compose_project_is_never_read() -> None:
    rows = [{"ID": "c1", "Project": "fst"}]
    found = ledger.containers_from(
        rows,
        [
            inspected("c1", "fst", "backend", "sha256:i1", "2026-10-27T01:29:07Z"),
            inspected("c9", "hosli-recs", "api", "sha256:i9", "2026-10-27T01:29:07Z"),
        ],
        [{"Id": "sha256:i1", "Created": "2026-10-27T01:29:06Z"}],
    )
    assert [c.container_id for c in found] == ["c1"]
    assert found[0].image_created == "2026-10-27T01:29:06Z"


def test_an_image_revision_label_is_observed() -> None:
    commit, status, _ = ledger.resolve([container("c1", "i1", T0, label=A)], {}, head=B)
    assert (commit, status) == (A, "observed")


def test_an_image_built_during_unbiddens_deploy_is_verified(store: Store) -> None:
    built = container("c1", "i1", T0 + timedelta(seconds=40))
    record = ledger.bind(store, [built], A, started=T0)
    assert record["backend"]["verified"] is True
    commit, status, _ = ledger.resolve([built], store.get_value("image_bindings", {}), head=B)
    assert (commit, status) == (A, "verified")


def test_a_restart_on_an_older_image_binds_nothing_verified(store: Store) -> None:
    stale = container("c1", "i1", T0 - timedelta(days=1))
    ledger.bind(store, [stale], A, started=T0)
    commit, status, reason = ledger.resolve([stale], store.get_value("image_bindings", {}), head=B)
    assert (commit, status) == (A, "inferred") and "not rebuilt" in reason


def test_containers_nobody_accounts_for_are_head_inferred_and_external(store: Store) -> None:
    d = ledger.observe(store, [container("c1", "i1", T0)], head=B, now=T0)
    assert d is not None and (d.commit, d.commit_status, d.initiated_by) == (B, "inferred", "external")
    assert "HEAD" in d.commit_reason
    assert store.get_value("deploy_sequence") == [B]


def test_unbiddens_own_deploy_is_attributed_and_found_by_commit(store: Store) -> None:
    built = container("c1", "i1", T0 + timedelta(seconds=40))
    ledger.bind(store, [built], A, started=T0)
    store.set_value("deployed_by_unbidden", {"commit": A, "at": (T0 + timedelta(seconds=50)).isoformat()})
    d = ledger.observe(store, [built], head=B, now=T0 + timedelta(minutes=1))
    assert d is not None and (d.commit_status, d.initiated_by) == ("verified", "unbidden")
    assert ledger.is_attributable(d)
    assert [(x.id, why) for x, why in ledger.ran_commit(store, A[:12])] == [("0", "runs exactly this commit")]


def test_recreated_containers_on_the_same_code_are_the_same_deploy_and_a_rollback_is_a_new_one(store: Store) -> None:
    first = ledger.observe(store, [container("c1", "i1", T0, label=A)], head=None, now=T0)
    same = ledger.observe(store, [container("c2", "i1", T0, label=A)], head=None, now=T0)
    other = ledger.observe(store, [container("c3", "i2", T0, label=B)], head=None, now=T0)
    back = ledger.observe(store, [container("c4", "i1", T0, label=A)], head=None, now=T0)
    assert first and same and other and back
    assert (first.index, same.index, other.index, back.index) == (0, 0, 1, 2)
    assert store.get_value("deploy_sequence") == [A, B, A]


def test_an_unknown_version_gets_an_image_derived_tag(store: Store) -> None:
    d = ledger.observe(store, [container("c1", "sha256:0123456789abcdef", T0)], head=None, now=T0)
    assert d is not None and d.commit is None and d.commit_status == "unknown"
    assert ledger.version_of(d) == "unknown-0123456789ab"
    assert not ledger.is_attributable(d)
