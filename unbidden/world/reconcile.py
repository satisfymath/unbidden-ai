"""Reconcile a fresh map with the previous one instead of forgetting everything at each map.

- A fact seen again keeps the time it was first observed in its evidence and is refreshed.
- A fact whose source ran again and did not see it becomes `obsolete` (kept, with `obsolete_since`), never left
  as `observed`. It is dropped once it has been obsolete longer than `KEEP_OBSOLETE`.
- A fact whose source did not run this time (no permission, nothing running, unreachable) is carried over as it
  was, with its original `observed_at`: nothing is promoted, and its age says how old the knowledge is.
- A fact past its `expires_at` becomes obsolete whatever its source.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, EpistemicStatus, utc_now
from unbidden.contracts.world import Fact, Relation, Resource, WorldModel

KEEP_OBSOLETE = timedelta(days=7)
OBSOLETE = EpistemicStatus.OBSOLETE


class WorldDiff(Contract):
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    obsoleted: list[str] = Field(default_factory=list)
    revived: list[str] = Field(default_factory=list)
    carried: list[str] = Field(default_factory=list)  # kept from sources that did not run

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.obsoleted or self.revived)

    def summary(self) -> dict[str, Any]:
        return {k: v[:50] for k, v in self.model_dump().items() if v} | {
            f"n_{k}": len(v) for k, v in self.model_dump().items()
        }


def _relation_id(relation: Relation) -> str:
    return f"{relation.src} -{relation.predicate}-> {relation.dst}"


def _retire(fact: Fact, now: datetime) -> None:
    fact.status = OBSOLETE
    fact.obsolete_since = fact.obsolete_since or now


def _carry(old: Fact, ran: set[str], now: datetime, label: str, diff: WorldDiff) -> Fact | None:
    """What becomes of a fact the fresh map does not contain. None drops it."""
    if old.status is OBSOLETE:
        return old if old.obsolete_since and now - old.obsolete_since < KEEP_OBSOLETE else None
    # A fact from before sources were recorded is judged by whatever ran now.
    unseen = old.source in ran or (old.source is None and bool(ran))
    if unseen or (old.expires_at is not None and old.expires_at <= now):
        _retire(old, now)
        diff.obsoleted.append(label)
        return old
    diff.carried.append(label)
    return old


def _attributes_changed(old: Resource, new: Resource) -> bool:
    return old.attributes != new.attributes or old.status != new.status


def reconcile(
    previous: WorldModel | None, fresh: WorldModel, ran: set[str], *, now: datetime | None = None
) -> tuple[WorldModel, WorldDiff]:
    """Merge `fresh` (what the sources in `ran` just saw) into `previous`. Returns the world to store and the diff."""
    now = now or utc_now()
    diff = WorldDiff()
    if previous is None:
        diff.added = sorted(fresh.resources) + [_relation_id(r) for r in fresh.relations]
        return fresh, diff

    for rid, resource in fresh.resources.items():
        old = previous.resources.get(rid)
        if old is None:
            diff.added.append(rid)
        elif old.status is OBSOLETE:
            diff.revived.append(rid)
        elif _attributes_changed(old, resource):
            diff.changed.append(rid)
    for rid, old in previous.resources.items():
        if rid in fresh.resources:
            continue
        kept = _carry(old, ran, now, rid, diff)
        if kept is not None:
            fresh.resources[rid] = kept  # type: ignore[assignment]

    fresh_keys = {r.key for r in fresh.relations}
    old_keys = {r.key: r for r in previous.relations}
    for relation in fresh.relations:
        old = old_keys.get(relation.key)
        if old is None:
            diff.added.append(_relation_id(relation))
        elif old.status is OBSOLETE:
            diff.revived.append(_relation_id(relation))
    for key, old in old_keys.items():
        if key in fresh_keys:
            continue
        kept = _carry(old, ran, now, _relation_id(old), diff)
        if kept is not None:
            fresh.relations.append(kept)  # type: ignore[arg-type]

    # A relation cannot be more current than the things it joins.
    for relation in fresh.relations:
        if relation.status is OBSOLETE:
            continue
        ends = [fresh.resources.get(relation.src), fresh.resources.get(relation.dst)]
        if any(end is not None and end.status is OBSOLETE for end in ends):
            _retire(relation, now)
            diff.obsoleted.append(_relation_id(relation))

    # Blind spots describe this map only; those of sources that did not run say so themselves.
    return fresh, diff
