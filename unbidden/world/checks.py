"""Generic checks over the World Model that turn facts into opportunities. No rule names a table, a route or
anything specific to one system: they read only what discovery observed or inferred."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from unbidden.contracts.common import EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
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
                    "rows": rows,
                    "rows_read": read,
                    "seconds": round(seconds),
                },
            )
        )
    return found


# A B-tree leaf entry for a 4-byte key: the key, an 8-byte tuple header, a 4-byte item pointer, at the default
# 90 % fill. An estimate: a wider key (bigint, uuid, text) costs more.
INDEX_BYTES_PER_ROW = (4 + 8 + 4) / 0.9


def index_tradeoffs(table: str, column: str, rows: Any, table_bytes: Any) -> dict[str, Any]:
    """What adding the index costs, as far as the database's statistics say: storage, and the writes that must keep
    it. An estimate, said so: the experiment measures reads, not these."""
    size = int(rows * INDEX_BYTES_PER_ROW) if isinstance(rows, int) else None
    share = ""
    if size and table_bytes:
        share = f" ({size / table_bytes:.0%} of the table's {table_bytes / 1e6:.1f} MB)"
    said = (
        f"about {size / 1e6:.1f} MB for {rows} rows{share}" if size else "storage unknown (no row estimate)"
    ) + f"; every INSERT into {table}, UPDATE of {column} and DELETE also writes it"
    return {
        "index_bytes_estimate": size,
        "table_bytes": table_bytes,
        "writes": f"INSERT into {table}, UPDATE of {column}, DELETE",
        "basis": "estimate from the database's statistics; not measured",
        "said": said,
    }


def unindexed_foreign_keys(world: WorldModel, repo: Path | None = None) -> list[Opportunity]:
    """A foreign key column that leads no index, with the endpoints where that costs.

    It costs where rows are looked up by the column: code that filters by it, found in the repository (see
    `column_use`); without such code, only the database's own check when a parent row is deleted, which some engines
    make (Postgres) and others may not (SQLite without `foreign_keys`). Endpoints that merely read the table are not
    affected; without a repository to read, they are what is listed, as before.
    """
    from unbidden.world.column_use import column_users

    found: list[Opportunity] = []
    for relation in world.current_relations():
        if relation.predicate != "references" or relation.src not in world.resources:
            continue
        table = world.resources[relation.src]
        parent = world.resources.get(relation.dst)
        note = relation.evidence[0].note or ""
        column = note.split(" -> ")[0].split(".")[-1] if " -> " in note else ""
        if not column or any(cols and cols[0] == column for cols in _indexed_columns(table.attributes)):
            continue
        rows = table.attributes.get("rows_estimate", "?")
        users: list[Any] = []
        if repo is not None:
            users = column_users(repo, world.rev, world, table.name, column)
            ids = [f"endpoint:{name}" for name, _ in users]
            if users:
                via = sorted({f"{u.file}:{u.line} {u.function}" + (f" via {u.via}" if u.via else "") for _, u in users})
                joins = any(u.via.endswith("(join)") for _, u in users)
                path, what = (
                    ("join" if joins else "filter"),
                    f"{'joined' if joins else 'filtered'} on by {len(ids)} endpoint(s)",
                )
                why = (
                    f"Code reads {table.name} by {column} ({', '.join(via)}; inferred from the code, not observed): "
                    f"without an index every such lookup scans the whole table (~{rows} rows now, from the "
                    f"database's statistics), so its cost grows with all rows, not the ones it needs."
                )
            else:
                ids = sorted(
                    r.src
                    for r in world.current_relations()
                    if parent is not None
                    and r.dst == parent.id
                    and r.predicate == "writes"
                    and r.src.startswith("endpoint:DELETE ")
                )
                path, what = (
                    "parent_delete",
                    f"checked when {len(ids)} endpoint(s) delete a {parent.name if parent else 'parent'} row",
                )
                why = (
                    f"No code filters {table.name} by {column}. The cost is the database's own check when a "
                    f"{parent.name if parent else 'parent'} row is deleted: it looks for referencing rows by {column}, "
                    f"scanning {table.name} (~{rows} rows) on engines that enforce foreign keys."
                )
        else:
            ids = sorted(r.src for r in world.current_relations() if r.dst == table.id and r.predicate == "reads")
            path, what = "readers", f"read by {len(ids)} endpoint(s)"
            why = f"Queries filtering {table.name} by {column} must scan the whole table (~{rows} rows now)."
        ids = [i for i in ids if i in world.resources]
        if not ids:
            continue
        endpoints = [world.resources[i].name for i in ids]
        tradeoffs = index_tradeoffs(table.name, column, rows, table.attributes.get("bytes"))
        found.append(
            Opportunity(
                source="world",
                category="performance",
                title=f"{table.name}.{column} is a foreign key without an index, {what}",
                summary=f"{why} Endpoints: {', '.join(endpoints)}. Cost of the index: {tradeoffs['said']}.",
                dedup_key=f"world:unindexed_fk:{table.name}.{column}",
                evidence=[*relation.evidence, *table.evidence[-1:]],
                details={
                    "check": "unindexed_foreign_key",
                    "table": table.name,
                    "column": column,
                    "cost_path": path,
                    "tradeoffs": tradeoffs,
                    "rows": rows if isinstance(rows, int) else None,
                    "endpoints": endpoints,
                    "rev": world.rev,
                    "code": [
                        {
                            "endpoint": world.resources[i].name,
                            "file": world.resources[i].attributes.get("file"),
                            "line": world.resources[i].attributes.get("line"),
                        }
                        for i in ids
                    ],
                    # endpoint -> code -> query -> condition: each step's provenance (inferred from code); the
                    # observed cost is the experiment's own measurement of these endpoints, before any change.
                    "chain": [
                        {
                            "endpoint": e,
                            "code": f"{u.file}:{u.line} {u.function}",
                            "query": u.via or None,
                            "column": f"{table.name}.{column}",
                            "rows": rows,
                            "provenance": "inferred from code",
                        }
                        for e, u in users
                    ],
                },
            )
        )
    return found


GROWTH = 2.0  # the data a declined opportunity was judged on has at least doubled


def _reopening(existing: Opportunity, fresh: Opportunity) -> str | None:
    """Why a check firing again reopens what was closed or declined, or None. A closed one fired again: its cause
    is back. A declined one reopens when the data it was judged on grew enough to change the judgement."""
    if existing.status is OpportunityStatus.CLOSED:
        return "observed again after it was resolved"
    if existing.status is not OpportunityStatus.DECLINED:
        return None
    before, now = existing.details.get("rows_when_declined", existing.details.get("rows")), fresh.details.get("rows")
    if isinstance(before, int) and isinstance(now, int) and before > 0 and now >= GROWTH * before:
        return f"the table grew from ~{before} to ~{now} rows since it was declined"
    return None


def run_checks(world: WorldModel, store: Store, repo: Path | None = None) -> list[Opportunity]:
    opened: list[Opportunity] = []
    # Scan counters of the previous map, to judge only what happened since (see full_table_scans).
    last: dict[str, Any] = store.get_value("table_scans", {})
    now_ts = utc_now().timestamp()
    seconds = now_ts - float(last.get("ts", now_ts))
    current = {t.id: t.attributes["scans"] for t in world.of_kind("table") if t.attributes.get("scans")}
    store.set_value("table_scans", {"ts": now_ts, "tables": current})
    candidates = unindexed_foreign_keys(world, repo)
    if seconds > 0:
        candidates += full_table_scans(world, last.get("tables", {}), seconds)
    for opp in candidates:
        existing = store.get_by_key(COLLECTION, opp.dedup_key, Opportunity)
        if existing is not None:
            why = _reopening(existing, opp)
            if existing.status is OpportunityStatus.DECLINED and not why:
                # Growth is measured from what it was declined on, not from the last sighting: slow growth adds up.
                opp.details["rows_when_declined"] = existing.details.get(
                    "rows_when_declined", existing.details.get("rows")
                )
            existing.details = {**existing.details, **opp.details}
            if why:  # judged again from now on: a later decline sets its own baseline
                existing.details.pop("rows_when_declined", None)
            existing.title, existing.summary = opp.title, opp.summary
            store.put(COLLECTION, existing)
            if why:
                from unbidden.director.decide import reopen

                reopen(store, existing, why, actor="world")
                opened.append(existing)
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
