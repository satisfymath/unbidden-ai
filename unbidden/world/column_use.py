"""Which endpoints reach code that filters a table by one column.

An unindexed foreign key costs only where something looks rows up by it: a query that filters by the column
(`ShoppingListItem.food_id == ...`), or the database checking it when a parent row is deleted. Endpoints that merely
read the table are not affected. This reads the code: the model class mapped to the table, the functions that filter
by `Class.column` (or `filter_by(column=...)`), and the endpoint handlers that call those functions.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from unbidden.contracts.world import WorldModel
from unbidden.world.relations import handler_source

_SKIP = re.compile(r"(^|/)(tests?|alembic|migrations|versions)/")
_DEF = re.compile(r"^(?P<indent>\s*)(?:async\s+)?def\s+(?P<name>\w+)\s*\(")


@dataclass(frozen=True)
class ColumnUse:
    file: str
    line: int
    function: str
    via: str = ""  # for SQL kept apart from the code: "comments.sql:8 get-comments-for-article-by-slug (join)"


# A condition: ON or WHERE, up to the next clause.
_CLAUSE = re.compile(
    r"\b(?P<kind>ON|WHERE)\b(?P<body>.*?)(?=\b(?:INNER|LEFT|RIGHT|JOIN|GROUP|ORDER|LIMIT|RETURNING)\b|;|$)", re.I | re.S
)
_SQL_NAME = re.compile(r"^--\s*(?:name:|:name)\s*(?P<name>[\w-]+)", re.M)


def sql_queries(sources: dict[str, str]) -> list[tuple[str, int, str, str]]:
    """Named queries kept in .sql files (`-- name: x`, the aiosql, yesql and pugsql convention): file, line, name,
    text. A file without names is one query named after the file."""
    found: list[tuple[str, int, str, str]] = []
    for path, text in sources.items():
        marks = list(_SQL_NAME.finditer(text))
        if not marks:
            found.append((path, 1, Path(path).stem, text))
            continue
        for i, mark in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            found.append((path, text[: mark.start()].count("\n") + 1, mark.group("name"), text[mark.start() : end]))
    return found


def sql_uses(queries: list[tuple[str, int, str, str]], table: str, column: str) -> list[tuple[str, int, str, str]]:
    """Queries that look rows of `table` up by `column`: the column in a WHERE or JOIN ... ON condition, qualified by
    the table or its alias (or bare, when the query reads only that table). Returns (file, line, name, kind)."""
    out = []
    for path, line, name, text in queries:
        aliases = {table} | {
            m.group("alias") for m in re.finditer(
                rf"\b(?:FROM|JOIN)\s+{re.escape(table)}(?:\s+(?:AS\s+)?(?P<alias>(?!WHERE|JOIN|ON|INNER|LEFT|RIGHT|USING)\w+))?",
                text, re.I) if m.group("alias")
        }  # fmt: skip
        if not re.search(rf"\b(?:FROM|JOIN)\s+{re.escape(table)}\b", text, re.I):
            continue
        qualified = "|".join(re.escape(a) for a in sorted(aliases))
        dotted = re.compile(rf"\b(?:{qualified})\.{re.escape(column)}\b", re.I)
        bare = re.compile(rf"(?<![.\w]){re.escape(column)}\s*(?:=|IN\b)", re.I)
        for clause in _CLAUSE.finditer(text):
            body = clause.group("body")
            # An unqualified column belongs to the table the condition's own FROM (or JOIN) reads: the nearest one
            # before it. `FROM favorites WHERE article_id = (SELECT id FROM articles ...)` is about favorites.
            before = list(re.finditer(r"\b(?:FROM|JOIN)\s+(\w+)", text[: clause.start()], re.I))
            owner = before[-1].group(1).lower() if before else ""
            if dotted.search(body) or (owner == table.lower() and bare.search(body.split("(SELECT")[0])):
                kind = "join" if clause.group("kind").upper() == "ON" else "filter"
                at = line + text[: clause.start()].count("\n")
                out.append((path, at, name, kind))
                break
    return out


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def _words(path: str) -> set[str]:
    """Words of a path below its top directory (every file shares the package), singular."""
    below = path.lower().split("/", 1)[-1]
    return {w.removesuffix("s") for w in re.split(r"[/_.\-]+", below) if len(w) > 2} - {"py"}


def mapped_classes(sources: dict[str, str], table: str) -> list[str]:
    """Classes mapped to `table`: SQLAlchemy's `__tablename__`, or a SQLModel `table=True` class of that name."""
    found: list[str] = []
    for text in sources.values():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(table)}[\"']", line):
                owner = next((lines[j] for j in range(i, -1, -1) if lines[j].startswith("class ")), "")
                if name := re.match(r"class\s+(\w+)", owner):
                    found.append(name.group(1))
        for match in re.finditer(r"^class\s+(\w+)\s*\(([^)]*)\)", text, re.MULTILINE):
            if match.group(1).lower() == table.lower() and "table=True" in match.group(2):
                found.append(match.group(1))
    return sorted(set(found))


def column_uses(sources: dict[str, str], classes: list[str], column: str) -> list[ColumnUse]:
    """Functions that filter by the column: `Class.column` or `filter_by(column=...)`, outside tests and migrations."""
    patterns = [rf"\b{re.escape(c)}\.{re.escape(column)}\b" for c in classes] + [
        rf"filter_by\([^)]*\b{re.escape(column)}\s*="
    ]
    pattern = re.compile("|".join(patterns))
    uses: list[ColumnUse] = []
    for path, text in sources.items():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not pattern.search(line) or stripped.startswith("#") or re.match(rf"{re.escape(column)}\s*:", stripped):
                continue
            function = next((m.group("name") for j in range(i, -1, -1) if (m := _DEF.match(lines[j]))), "")
            if function:
                uses.append(ColumnUse(path, i + 1, function))
    return uses


def _target(handler_file: str, definers: list[str], receiver: str = "") -> str | None:
    """The file whose function a handler's call reaches: the handler's own file, else the definer named most like it
    (`units.py` reaches `repository_units.py`), then the one whose path names the receiver (`self.repo.merge` reaches
    `repos/`, not `parser_utils/`), then sharing most path words. A tie, or no shared word, is unknown."""
    if receiver not in ("", "self"):  # `self.repo.get_empty()` from a handler also named get_empty is not itself
        definers = [d for d in definers if d != handler_file]
    elif handler_file in definers:
        return handler_file
    called_on = _words(receiver) if receiver else set()

    def rank(path: str) -> tuple[int, int, int]:
        named = len(_words(Path(path).name) & _words(Path(handler_file).name))
        return named, len(called_on & _words(path)), len(_words(path) & _words(handler_file))

    ranked = sorted(definers, key=rank, reverse=True)
    if not ranked or rank(ranked[0]) == (0, 0, 0) or (len(ranked) > 1 and rank(ranked[0]) == rank(ranked[1])):
        return None
    return ranked[0]


def column_users(repo: Path, rev: str, world: WorldModel, table: str, column: str) -> list[tuple[str, ColumnUse]]:
    """(endpoint, use) for each endpoint whose handler calls a function that filters `table` by `column`.

    A call is resolved to one definition first: a handler calling `merge()` reaches its own repository's `merge`, not
    every function of that name. Only then does it count if that definition filters by the column.
    """
    tracked = _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()
    paths = [p for p in tracked if p.endswith(".py") and not _SKIP.search(p)]
    sources = {p: _git(repo, "show", f"{rev}:{p}") for p in paths}
    uses = column_uses(sources, mapped_classes(sources, table), column)
    # SQL kept in .sql files and called by name from Python (`queries.get_comments_for_article_by_slug(...)`): the
    # functions that call such a query use the column as that query does.
    sql = {p: _git(repo, "show", f"{rev}:{p}") for p in tracked if p.endswith(".sql") and not _SKIP.search(p)}
    for qfile, qline, qname, kind in sql_uses(sql_queries(sql), table, column):
        called = re.compile(rf"\.{re.escape(qname.replace('-', '_'))}\s*\(")
        for path, text in sources.items():
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if not called.search(line):
                    continue
                function = next((m.group("name") for j in range(i, -1, -1) if (m := _DEF.match(lines[j]))), "")
                if function:
                    uses.append(ColumnUse(path, i + 1, function, f"{qfile}:{qline} {qname} ({kind})"))
    by_function: dict[str, list[ColumnUse]] = {}
    for use in uses:
        by_function.setdefault(use.function, []).append(use)
    definers = {
        name: [
            p for p, text in sources.items() if re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(", text, re.M)
        ]
        for name in by_function
    }
    found: list[tuple[str, ColumnUse]] = []
    for endpoint in world.of_kind("endpoint"):
        file, line = endpoint.attributes.get("file"), endpoint.attributes.get("line")
        if not file or not line:
            continue
        code = handler_source(repo, rev, str(file), int(str(line)))
        for name, named in sorted(by_function.items()):
            call = next(
                (
                    m
                    for m in re.finditer(rf"(?:(?P<receiver>\w+)\.|[\s(]){re.escape(name)}\(", code)
                    if not code[: m.start() + 1].rstrip().endswith("def")  # the handler's own `def get_empty(`
                ),
                None,
            )
            if call is None:
                continue
            target = _target(str(file), definers[name], call.group("receiver") or "")
            use = next((u for u in named if u.file == target), None)
            if use is not None:
                found.append((endpoint.name, use))
                break
    return sorted(found, key=lambda pair: pair[0])


_READ = re.compile(r"\b(?:FROM|JOIN)\s+(?P<table>\w+)", re.I)
_WRITE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?P<table>\w+)", re.I)


def sql_table_access(repo: Path, rev: str, world: WorldModel) -> list[tuple[str, str, str, str]]:
    """(endpoint, table, "reads" | "writes", where) for each endpoint whose handler calls a function that runs a named
    SQL query on a mapped table: SELECT/JOIN reads it, INSERT/UPDATE/DELETE writes it (stage 9: the endpoint-to-table
    map came from a model alone, and a more cautious model lost the deletes, so the cascade checks never ran). From
    code, inferred, no model; a query reached only through another layer the handler does not call is not seen."""
    tables = {t.name for t in world.of_kind("table")}
    tracked = _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()
    sql = {p: _git(repo, "show", f"{rev}:{p}") for p in tracked if p.endswith(".sql") and not _SKIP.search(p)}
    if not sql or not tables:
        return []
    sources = {p: _git(repo, "show", f"{rev}:{p}") for p in tracked if p.endswith(".py") and not _SKIP.search(p)}
    by_function: dict[str, list[tuple[str, str, str]]] = {}  # function -> (file, table, predicate)
    for qfile, qline, qname, text in sql_queries(sql):
        body = re.sub(r"--[^\n]*", "", text)
        writes = {m.group("table") for m in _WRITE.finditer(body)} & tables
        reads = ({m.group("table") for m in _READ.finditer(body)} & tables) - writes
        if not reads and not writes:
            continue
        called = re.compile(rf"\.{re.escape(qname.replace('-', '_'))}\s*\(")
        for path, code in sources.items():
            lines = code.splitlines()
            for i, line in enumerate(lines):
                if not called.search(line):
                    continue
                function = next((m.group("name") for j in range(i, -1, -1) if (m := _DEF.match(lines[j]))), "")
                if function:
                    for table, predicate in [*((t, "reads") for t in reads), *((t, "writes") for t in writes)]:
                        by_function.setdefault(function, []).append(
                            (path, table, f"{predicate}|{qfile}:{qline} {qname}")
                        )
    definers = {
        name: [
            p for p, text in sources.items() if re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(", text, re.M)
        ]
        for name in by_function
    }
    found: set[tuple[str, str, str, str]] = set()
    for endpoint in world.of_kind("endpoint"):
        file, line = endpoint.attributes.get("file"), endpoint.attributes.get("line")
        if not file or not line:
            continue
        code = handler_source(repo, rev, str(file), int(str(line)))
        for name, uses in by_function.items():
            for m in re.finditer(rf"(?:(?P<receiver>\w+)\.|[\s(]){re.escape(name)}\(", code):
                if code[: m.start() + 1].rstrip().endswith("def"):
                    continue
                target = _target(str(file), definers[name], m.group("receiver") or "")
                for path, table, how in uses:
                    if path == target:
                        predicate, where = how.split("|", 1)
                        found.add((endpoint.id, table, predicate, where))
    return sorted(found)
