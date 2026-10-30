"""Synthetic data for a measurement, written by fixed code from the database's own catalog (stage 10).

The project's migrations create the schema; this reads it back from PostgreSQL (columns, types, defaults, foreign
keys, unique constraints, enum labels) and writes one `INSERT ... SELECT ... FROM generate_series` per table: the
measured table's rows spread evenly over the rows its foreign key references, every table they require filled first.
No model writes it, so it cannot invent a column, and every value is derived from the row number, so two sessions
seed exactly the same data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

Psql = Callable[[str], str]  # runs SQL in the measured database, returns psql's unaligned output (raises on error)


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # information_schema data_type
    udt: str
    nullable: bool
    default: str | None
    max_length: int | None
    identity: bool


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list[Column])
    foreign: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])  # column -> (table, col)
    unique: set[str] = field(default_factory=set[str])  # columns under a single-column unique constraint or the key
    primary: list[str] = field(default_factory=list[str])


def _rows(psql: Psql, sql: str) -> list[list[str]]:
    out = psql(sql)
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def catalog(psql: Psql) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for name, column, dtype, udt, nullable, default, length, identity in _rows(psql, (
        "SELECT table_name, column_name, data_type, udt_name, is_nullable, COALESCE(column_default, ''), "
        "COALESCE(character_maximum_length::text, ''), is_identity FROM information_schema.columns "
        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
    )):  # fmt: skip
        table = tables.setdefault(name, Table(name))
        table.columns.append(Column(column, dtype, udt, nullable == "YES", default or None,
                                    int(length) if length else None, identity == "YES"))  # fmt: skip
    for src, col, dst, dcol in _rows(psql, (
        "SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, af.attname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
        "JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1] "
        "WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1"
    )):  # fmt: skip
        if src.strip('"') in tables:
            tables[src.strip('"')].foreign[col] = (dst.strip('"'), dcol)
    for table, col, kind in _rows(psql, (
        "SELECT c.conrelid::regclass::text, a.attname, c.contype FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
        "WHERE c.contype IN ('p', 'u') AND array_length(c.conkey, 1) = 1"
    )):  # fmt: skip
        t = tables.get(table.strip('"'))
        if t is not None:
            t.unique.add(col)
            if kind == "p":
                t.primary.append(col)
    return tables


def _enum_labels(psql: Psql, udt: str) -> list[str]:
    return [r[0] for r in _rows(psql, f"SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                                      f"WHERE t.typname = '{udt}' ORDER BY e.enumsortorder")]  # fmt: skip


def _value(psql: Psql, table: Table, column: Column) -> str:
    """An expression of the row number `g` for a column with no default: unique where the column must be, within its
    declared length."""
    unique = column.name in table.unique
    t = column.type
    if t in ("integer", "bigint", "smallint"):
        return "g" if unique else "(g % 1000)"
    if t in ("numeric", "real", "double precision"):
        return "(g % 1000)::numeric / 10"
    if t == "boolean":
        return "(g % 2 = 0)"
    if t.startswith("timestamp") or t == "date":
        return "(TIMESTAMP '2026-01-01' - (g % 1000) * INTERVAL '1 hour')"
    if t == "uuid":
        return f"md5('{table.name}.{column.name}.' || g)::uuid"
    if t in ("json", "jsonb"):
        return f"'{{}}'::{t}"
    if t == "ARRAY":
        return "'{}'"
    if t == "bytea":
        return "'\\x00'::bytea"
    if t == "USER-DEFINED":
        labels = _enum_labels(psql, column.udt)
        if labels:
            array = "ARRAY[" + ", ".join("'" + x.replace("'", "''") + "'" for x in labels) + f"]::{column.udt}[]"
            return f"({array})[1 + (g % {len(labels)})]"
        return "NULL"
    text = f"'{column.name[:3]}' || g"
    return f"left({text}, {column.max_length})" if column.max_length else text


_VOLATILE = re.compile(
    r"now\(\)|current_(timestamp|date|time)|clock_timestamp|statement_timestamp|random\(|"
    r"gen_random_uuid|uuid_generate",
    re.I,
)


def _needed(column: Column) -> bool:
    """A value the seeder writes: a required column without a default, or one whose default changes from run to run
    (`now()`): two sessions must hold the same data, or their responses could not be compared."""
    if column.default is not None and _VOLATILE.search(column.default):
        return True
    has_default = column.default is not None or column.identity
    return not column.nullable and not has_default


@dataclass(frozen=True)
class SeedPlan:
    statements: list[str]
    counts: dict[str, int]
    target: tuple[str, str]  # (table, column) measured
    parent: str | None


def resources(tables: dict[str, Table], paths: list[str]) -> list[str]:
    """The tables the endpoints act on, named by their paths' literal segments (`/api/v1/spool/{id}/measure` acts on
    `spool`): an endpoint that loads a record of one table and joins the measured one answers 404 while that table is
    empty (stage 10, Spoolman: `PUT /spool/{id}/measure` with only `filament` seeded)."""
    found: list[str] = []
    for path in paths:
        for segment in re.findall(r"/([A-Za-z_][\w-]*)", path):
            for name in (segment, segment.replace("-", "_"), segment.rstrip("s"), segment.removesuffix("es")):
                if name in tables and name not in found:
                    found.append(name)
    return found


def plan_seed(psql: Psql, table: str, column: str, rows: int, owners: int, others: int = 50,
              paths: list[str] | None = None, context_rows: int = 2000) -> SeedPlan:  # fmt: skip
    """Rows for `table`, `column` spread evenly over `owners` rows of the table it references, the tables the
    endpoints act on (`context_rows` each, their own references spread the same way), and every table those require
    (a NOT NULL foreign key), in dependency order. Raises ValueError with the reason when the schema does not allow it
    (no such table, a required self-reference, a multi-column key)."""
    tables = catalog(psql)
    if table not in tables:
        raise ValueError(f"the database has no table {table} (its migrations may not have run)")
    context = [r for r in resources(tables, paths or []) if r != table]
    parent = tables[table].foreign.get(column, (None, None))[0]
    counts: dict[str, int] = {}
    order: list[str] = []

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if name in order:
            return
        if name in trail:
            raise ValueError(f"a required foreign key cycle through {' -> '.join((*trail, name))}")
        t = tables.get(name)
        if t is None:
            raise ValueError(f"table {name} is referenced but not in the public schema")
        for col, (dst, _) in t.foreign.items():
            needed = _needed(next(c for c in t.columns if c.name == col)) or (name == table and col == column)
            if needed and dst != name:
                visit(dst, (*trail, name))
            elif needed:
                raise ValueError(f"{name}.{col} is a required reference to its own table")
        order.append(name)

    visit(table, ())
    for name in context:
        visit(name, ())
    for name in order:
        counts[name] = (rows if name == table else owners if name == parent
                        else context_rows if name in context else others)  # fmt: skip
    statements: list[str] = []
    for name in order:
        t = tables[name]
        cols, exprs, joins = [], [], []
        for c in t.columns:
            ref = t.foreign.get(c.name)
            if ref is not None and (
                _needed(c)
                or (name == table and c.name == column)
                or (name in context and ref[0] in counts and ref[0] != name)
            ):
                alias = f"p_{len(joins)}"
                joins.append(f"(SELECT array_agg({ref[1]} ORDER BY {ref[1]}) AS ids FROM {ref[0]}) {alias}")
                cols.append(c.name)
                exprs.append(f"{alias}.ids[1 + (g % array_length({alias}.ids, 1))]")
            elif _needed(c):
                cols.append(c.name)
                exprs.append(_value(psql, t, c))
        target = ", ".join(f'"{c}"' for c in cols)
        source = " CROSS JOIN ".join([f"generate_series(1, {counts[name]}) AS g", *joins])
        if cols:
            statements.append(f'INSERT INTO "{name}" ({target}) SELECT {", ".join(exprs)} FROM {source};')
        else:
            statements.append(f'INSERT INTO "{name}" SELECT FROM generate_series(1, {counts[name]}) AS g;')
    statements.append("ANALYZE;")
    return SeedPlan(statements, counts, (table, column), parent)


def describe(plan: SeedPlan) -> dict[str, object]:
    return {"tables": plan.counts, "measured": f"{plan.target[0]}.{plan.target[1]}", "references": plan.parent,
            "distribution": "rows spread evenly over the referenced rows (row number modulo their count)",
            "written_by": "Unbidden's seeder from the engine's catalog (no model)"}  # fmt: skip


def data_check(psql: Psql, plan: SeedPlan) -> tuple[bool, str]:
    """Whether the seeded data is what the measurement needs: the rows are there and spread over the references."""
    table, column = plan.target
    got = _rows(psql, f'SELECT count(*), count(DISTINCT "{column}") FROM "{table}"')
    total, distinct = (int(x) for x in got[0]) if got else (0, 0)
    wanted = plan.counts.get(table, 0)
    ok = total >= wanted * 0.9 and (
        plan.parent is None or distinct >= min(plan.counts.get(plan.parent, 1), wanted) * 0.9
    )
    return ok, json.dumps({"rows": total, "distinct_references": distinct, "seeded": plan.counts})


_STATEMENT_COLUMN = re.compile(r'["\w.]+')


def reads_by(query: str, table: str, column: str) -> bool:
    """Whether a statement looks `table` up by `column`: a WHERE condition on it (`spool.filament_id = $1`, `IN`,
    `= ANY`), or a JOIN that brings `table` in on it (`JOIN spool ON spool.filament_id = filament.id`). A join that
    brings another table in by its key (`JOIN vendor ON vendor.id = filament.vendor_id`) looks that table up, not
    `table`: an index on `table.column` does not serve it (stage 10, Spoolman)."""
    q = re.sub(r"\s+", " ", query.lower().replace('"', ""))
    # PostgreSQL's own foreign-key checks: `FROM ONLY public.t x WHERE col OPERATOR(pg_catalog.=) $1`
    q = q.replace(" only ", " ").replace("operator(pg_catalog.=)", "=")
    names = {table}
    for m in re.finditer(rf"\b(?:from|join) (?:public\.)?{re.escape(table)}(?: as)? (\w+)", q):
        if m.group(1) not in (
            "on",
            "where",
            "join",
            "left",
            "inner",
            "right",
            "full",
            "cross",
            "group",
            "order",
            "limit",
        ):
            names.add(m.group(1))
    if not re.search(rf"\b(from|join|update|delete from) (public\.)?{re.escape(table)}\b", q):
        return False
    ref = "(?:" + "|".join(re.escape(n) for n in names) + rf")\.{re.escape(column)}"
    on_column = rf"(?:\b{ref}\b|(?<![\w.]){re.escape(column)}\b) ?(?:=|in\b|= ?any)|(?:=|in\b) ?\(?(?:\b{ref}\b)"
    # WHERE clauses (and UPDATE/DELETE conditions)
    for clause in re.findall(r"\bwhere (.*?)(?=\b(?:group by|order by|limit|offset|returning|union)\b|$)", q):
        if re.search(on_column, clause):
            return True
    # JOINs that bring `table` (or an alias of it) in
    for joined, alias, condition in re.findall(
        r"\bjoin (?:public\.)?(\w+)(?:(?: as)? (\w+))? on (.*?)(?=\b(?:left|right|"
        r"inner|full|cross)? ?join\b|\bwhere\b|\bgroup by\b|\border by\b|$)",
        q,
    ):
        if joined == table and re.search(
            rf"\b(?:{re.escape(alias or table)}|{re.escape(table)})\.{re.escape(column)}\b", condition
        ):
            return True
    return False


def statements_using(psql: Psql, table: str, column: str, calls: int) -> list[dict[str, object]]:
    """The statements the measured calls ran that read `table` by `column` (a filter or a join on it), from
    pg_stat_statements: what the engine itself says the operation did."""
    mean = (
        "mean_exec_time"
        if _rows(
            psql,
            "SELECT 1 FROM information_schema.columns WHERE table_name = "
            "'pg_stat_statements' AND column_name = 'mean_exec_time'",
        )
        else "mean_time"
    )
    rows = _rows(psql, f"SELECT calls, round({mean}::numeric, 3), regexp_replace(query, '\\s+', ' ', 'g') "
                       "FROM pg_stat_statements WHERE query NOT ILIKE '%pg_stat_statements%' ORDER BY calls DESC "
                       "LIMIT 200")  # fmt: skip
    out: list[dict[str, object]] = []
    for count, mean, query in rows:
        if reads_by(query, table, column):
            out.append({"calls": int(count), "mean_ms": float(mean), "query": query[:400]})
    return [s for s in out if int(s["calls"]) >= calls] or out  # type: ignore[call-overload]
