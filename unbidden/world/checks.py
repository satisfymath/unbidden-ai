"""Generic checks over the World Model that turn facts into opportunities. No rule names a table, a route or
anything specific to one system: they read only what discovery observed or inferred."""

from __future__ import annotations

from typing import Any

from unbidden.contracts.common import EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.opportunity import Opportunity
from unbidden.contracts.world import WorldModel
from unbidden.store import Store

COLLECTION = "opportunities"


def _indexed_columns(attributes: dict[str, object]) -> list[list[str]]:
    indexes = attributes.get("indexes") or []
    columns: list[list[str]] = []
    for index in indexes if isinstance(indexes, list) else []:
        if isinstance(index, dict):
            raw = str(index.get("columns", ""))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            columns.append([c.strip().strip('"').split(" ")[0] for c in raw.split(",") if c.strip()])
    return columns


MIN_ROWS, MIN_NEW_SCANS, WHOLE_TABLE = 10_000, 10, 0.5


def full_table_scans(world: WorldModel, previous: dict[str, Any], seconds: float) -> list[Opportunity]:
    """A large table read whole, again and again, since the last map: queries no index serves. Counters are
    cumulative, so only their growth since the previous map counts (scans from before a fix are history)."""
    found: list[Opportunity] = []
    for table in world.of_kind("table"):
        now, before = table.attributes.get("scans"), previous.get(table.id)
        rows = int(table.attributes.get("rows_estimate") or 0)
        if not now or not before or rows < MIN_ROWS:
            continue
        scans, read = now["seq"] - before["seq"], now["seq_rows"] - before["seq_rows"]
        if scans < MIN_NEW_SCANS or read / scans < WHOLE_TABLE * rows:
            continue
        readers = sorted(r.src for r in world.current_relations() if r.dst == table.id and r.predicate == "reads")
        endpoints = [world.resources[r].name for r in readers if r in world.resources]
        if not endpoints:
            continue
        found.append(
            Opportunity(
                source="world",
                category="performance",
                title=f"{table.name} ({rows} rows) was read whole {scans} times in the last {seconds / 60:.0f} minutes",
                summary=(
                    f"Sequential scans read {read} rows of {table.name} in {scans} scans since the previous map "
                    f"(~{read // scans} rows each, of {rows}): some query filters or orders by something no index "
                    f"serves. Which query is not observed (no per-query statistics); endpoints that read the table: "
                    f"{', '.join(endpoints)}."
                ),
                dedup_key=f"world:full_scans:{table.name}",
                evidence=[EvidenceRef(kind="config", locator=f"pg_stat_user_tables#{table.name}", note=str(now))],
                details={
                    "check": "full_table_scans",
                    "table": table.name,
                    "endpoints": endpoints,
                    "rev": world.rev,
                    "scans": scans,
                    "rows_read": read,
                    "seconds": round(seconds),
                },
            )
        )
    return found


def unindexed_foreign_keys(world: WorldModel) -> list[Opportunity]:
    """A foreign key column that leads no index, on a table some endpoint reads.

    Filtering or joining on such a column scans the whole table, so the cost grows with all rows in the
    system rather than with the rows a request needs.
    """
    found: list[Opportunity] = []
    for relation in world.current_relations():
        if relation.predicate != "references" or relation.src not in world.resources:
            continue
        table = world.resources[relation.src]
        note = relation.evidence[0].note or ""
        column = note.split(" -> ")[0].split(".")[-1] if " -> " in note else ""
        if not column or any(cols and cols[0] == column for cols in _indexed_columns(table.attributes)):
            continue
        readers = sorted(r.src for r in world.current_relations() if r.dst == table.id and r.predicate == "reads")
        if not readers:
            continue
        endpoints = [world.resources[r].name for r in readers if r in world.resources]
        found.append(
            Opportunity(
                source="world",
                category="performance",
                title=f"{table.name}.{column} is a foreign key without an index, read by {len(endpoints)} endpoint(s)",
                summary=(
                    f"Queries filtering {table.name} by {column} must scan the whole table, so their cost grows with "
                    f"every row in it, not with the rows a request needs (the live table holds "
                    f"~{table.attributes.get('rows_estimate', '?')} rows now). Read by: {', '.join(endpoints)}."
                ),
                dedup_key=f"world:unindexed_fk:{table.name}.{column}",
                evidence=[*relation.evidence, *table.evidence[-1:]],
                details={
                    "check": "unindexed_foreign_key",
                    "table": table.name,
                    "column": column,
                    "endpoints": endpoints,
                    "rev": world.rev,
                    "code": [
                        {
                            "endpoint": world.resources[r].name,
                            "file": world.resources[r].attributes.get("file"),
                            "line": world.resources[r].attributes.get("line"),
                        }
                        for r in readers
                        if r in world.resources
                    ],
                },
            )
        )
    return found


CHECKS = (unindexed_foreign_keys,)


def run_checks(world: WorldModel, store: Store) -> list[Opportunity]:
    opened: list[Opportunity] = []
    # Scan counters of the previous map, to judge only what happened since (see full_table_scans).
    last: dict[str, Any] = store.get_value("table_scans", {})
    now_ts = utc_now().timestamp()
    seconds = now_ts - float(last.get("ts", now_ts))
    current = {t.id: t.attributes["scans"] for t in world.of_kind("table") if t.attributes.get("scans")}
    store.set_value("table_scans", {"ts": now_ts, "tables": current})
    candidates = [opp for check in CHECKS for opp in check(world)]
    if seconds > 0:
        candidates += full_table_scans(world, last.get("tables", {}), seconds)
    for opp in candidates:
        existing = store.get_by_key(COLLECTION, opp.dedup_key, Opportunity)
        if existing is not None:
            existing.details = {**existing.details, **opp.details}
            existing.summary = opp.summary
            store.put(COLLECTION, existing)
            continue
        store.put(COLLECTION, opp, key=opp.dedup_key)
        store.append_event(
            Event(
                type=EventType.OPPORTUNITY_OPENED,
                actor="world",
                entity_id=opp.id,
                correlation_id=opp.id,
                payload={"title": opp.title, "check": opp.details["check"]},
            )
        )
        opened.append(opp)
    return opened
