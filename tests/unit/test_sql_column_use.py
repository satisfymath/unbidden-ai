"""Findings tied to the queries that use them (stage 8): SQL kept in .sql files, called by name from Python.

Found on Conduit (frozen run 9ef6a60): its SQL lives in aiosql files; Unbidden found no code reading
`commentaries.article_id` and explained the unindexed key by a parent delete only, missing the comments listing
(a join on it) and the favorites count (a filter on it)."""

from __future__ import annotations

import pytest

from unbidden.world.column_use import sql_queries, sql_uses

pytestmark = pytest.mark.unit
COMMENTS = """-- name: get-comments-for-article-by-slug
SELECT c.id, c.body
FROM commentaries c
         INNER JOIN articles a ON c.article_id = a.id AND (a.slug = :slug);

-- name: create-comment<!
INSERT INTO commentaries (body, author_id, article_id) VALUES (:body, :author_id, :article_id);
"""
FAVORITES = """-- name: get-favorites-count-for-article^
SELECT count(*) as favorites_count
FROM favorites
WHERE article_id = (SELECT id FROM articles WHERE slug = :slug);

-- name: get-articles-by-author
SELECT id FROM articles WHERE author_id = :author;
"""


def test_a_join_and_a_filter_are_found_and_an_insert_is_not() -> None:
    queries = sql_queries({"sql/comments.sql": COMMENTS, "sql/articles.sql": FAVORITES})
    assert sql_uses(queries, "commentaries", "article_id") == [
        ("sql/comments.sql", 4, "get-comments-for-article-by-slug", "join")
    ]  # the INSERT names the column but looks nothing up by it
    assert sql_uses(queries, "favorites", "article_id") == [
        ("sql/articles.sql", 4, "get-favorites-count-for-article", "filter")
    ]
    assert sql_uses(queries, "articles", "article_id") == []  # another table's column of that name


def test_a_file_without_names_is_one_query() -> None:
    (only,) = sql_queries({"report.sql": "SELECT * FROM favorites f WHERE f.article_id = 3"})
    assert only[2] == "report" and sql_uses([only], "favorites", "article_id")[0][3] == "filter"


def test_the_chain_reaches_the_endpoint_through_the_python_that_calls_the_query(tmp_path: object) -> None:
    import subprocess
    from pathlib import Path

    from unbidden.contracts.common import EpistemicStatus, EvidenceRef
    from unbidden.contracts.world import Resource, WorldModel
    from unbidden.world.column_use import column_users

    repo = Path(str(tmp_path))
    files = {
        "app/db/queries/sql/comments.sql": COMMENTS,
        "app/db/repositories/comments.py": (
            "class CommentsRepository:\n"
            "    async def get_comments_for_article(self, slug):\n"
            "        return await queries.get_comments_for_article_by_slug(self.conn, slug=slug)\n"
        ),
        "app/api/routes/comments.py": (
            "@router.get('/articles/{slug}/comments')\n"
            "async def list_comments(slug, repo):\n"
            "    return await repo.get_comments_for_article(slug)\n"
        ),
    }
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    name = "GET /articles/{slug}/comments"
    world.add(Resource(id=f"endpoint:{name}", kind="endpoint", name=name, status=EpistemicStatus.OBSERVED,
                       confidence=1.0, evidence=[EvidenceRef(kind="config", locator="openapi")],
                       attributes={"file": "app/api/routes/comments.py", "line": 2}))  # fmt: skip
    ((endpoint, use),) = column_users(repo, "HEAD", world, "commentaries", "article_id")
    assert endpoint == "GET /articles/{slug}/comments" and use.function == "get_comments_for_article"
    assert use.via == "app/db/queries/sql/comments.sql:4 get-comments-for-article-by-slug (join)"


def test_an_index_finding_states_its_cost_as_an_estimate() -> None:
    from unbidden.world.checks import index_tradeoffs

    cost = index_tradeoffs("commentaries", "article_id", 300_000, 60_000_000)
    assert 5_000_000 < cost["index_bytes_estimate"] < 6_000_000  # ~17.8 bytes per row
    assert "INSERT into commentaries" in cost["writes"] and "not measured" in cost["basis"]
    assert "storage unknown" in index_tradeoffs("t", "c", "?", None)["said"]


def test_tables_an_endpoint_reads_and_writes_come_from_the_queries_its_code_calls(tmp_path: object) -> None:
    """Stage 9: with the endpoint-to-table map from a model alone, a more cautious model lost Conduit's deletes and
    the cascade checks never ran. The named queries a handler's code calls say it without a model."""
    import subprocess
    from pathlib import Path

    from unbidden.contracts.common import EpistemicStatus, EvidenceRef
    from unbidden.contracts.world import Resource, WorldModel
    from unbidden.world.column_use import sql_table_access

    repo = Path(str(tmp_path))
    files = {
        "app/sql/articles.sql": "-- name: delete-article!\nDELETE FROM articles WHERE slug = :slug;\n\n"
        "-- name: get-article^\nSELECT a.id FROM articles a JOIN users u ON u.id = a.author_id WHERE slug = :slug;\n",
        "app/repo.py": (
            "class Articles:\n"
            "    async def delete(self, slug):\n        await queries.delete_article(self.conn, slug=slug)\n"
            "    async def get(self, slug):\n        return await queries.get_article(self.conn, slug=slug)\n"
        ),
        "app/routes.py": "@router.delete('/a/{slug}')\nasync def remove(slug, repo):\n    await repo.delete(slug)\n",
    }
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    seen = [EvidenceRef(kind="config", locator="x")]
    for table in ("articles", "users", "tags"):
        world.add(Resource(id=f"table:{table}", kind="table", name=table, status=EpistemicStatus.OBSERVED,
                           confidence=1.0, evidence=seen))  # fmt: skip
    world.add(Resource(id="endpoint:DELETE /a/{slug}", kind="endpoint", name="DELETE /a/{slug}",
                       status=EpistemicStatus.OBSERVED, confidence=1.0, evidence=seen,
                       attributes={"file": "app/routes.py", "line": 1}))  # fmt: skip
    found = sql_table_access(repo, "HEAD", world)
    assert [(t, p) for _, t, p, _ in found] == [("articles", "writes")]  # it calls delete, never get
    assert found[0][3] == "app/sql/articles.sql:1 delete-article"


def test_a_join_in_a_query_keyed_by_the_primary_key_is_not_a_lookup_by_the_column() -> None:
    """Stage 9 evaluation, Spoolman: `spool.filament_id` was said to be "filtered on" by queries that find the spool
    by its primary key and join the filament by its own: an index on filament_id is not what they use."""
    from unbidden.world.column_use import column_uses

    keyed = (
        "async def use_length(db, spool_id):\n"
        "    result = await db.execute(\n"
        "        sqlalchemy.select(models.Filament.diameter)\n"
        "        .join(models.Spool, models.Spool.filament_id == models.Filament.id)\n"
        "        .where(models.Spool.id == spool_id),\n"
        "    )\n"
    )
    by_column = (
        "async def of_filament(db, fid):\n    return await db.execute(select(Spool).where(Spool.filament_id == fid))\n"
    )
    found = column_uses({"a.py": keyed, "b.py": by_column}, ["Spool"], "filament_id")
    assert [(u.file, u.function) for u in found] == [("b.py", "of_filament")]
