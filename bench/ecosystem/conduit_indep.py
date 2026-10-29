"""An independent check of the Conduit regression's index claims (stage 8, B-7), by the harness's author, no model.

    uv run python -m bench.ecosystem.conduit_indep

EXPLAIN ANALYZE of the endpoints' own SQL (Conduit's `app/db/queries/sql/*.sql`) on the lab's synthetic data,
without and with the index, each repetition in its own transaction, rolled back: the lab database is unchanged.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path

from bench.ecosystem.conduit_lab import COMPOSE, repo_dir

LAB = Path.home() / "unbidden-lab"
N = 15
DELETE_ARTICLE = (
    "DELETE FROM articles WHERE slug = 'article-1{i}7' "
    "AND author_id = (SELECT author_id FROM articles WHERE slug = 'article-1{i}7')"
)
CASES = {
    "commentaries.article_id / GET comments": (
        "",
        "CREATE INDEX ix_tmp ON commentaries (article_id)",
        "SELECT c.id, c.body, c.created_at, c.updated_at, (SELECT username FROM users WHERE id = c.author_id) "
        "FROM commentaries c INNER JOIN articles a ON c.article_id = a.id AND (a.slug = 'article-{i}5')",
    ),
    "favorites.article_id / DELETE article": ("", "CREATE INDEX ix_tmp ON favorites (article_id)", DELETE_ARTICLE),
    "favorites.article_id / DELETE article, comments indexed on both sides": (
        "CREATE INDEX ix_c ON commentaries (article_id)",
        "CREATE INDEX ix_tmp ON favorites (article_id)",
        DELETE_ARTICLE,
    ),
    "commentaries.author_id / DELETE comment": (
        "",
        "CREATE INDEX ix_tmp ON commentaries (author_id)",
        "DELETE FROM commentaries WHERE id = 1{i}3 "
        "AND author_id = (SELECT author_id FROM commentaries WHERE id = 1{i}3)",
    ),
}


def _psql(sql: str) -> str:
    argv = [*COMPOSE, "exec", "-T", "db", "psql", "-q", "-At", "-U", "postgres", "-d", "postgres"]
    return subprocess.run(argv, cwd=repo_dir(LAB), input=sql, text=True, capture_output=True, check=True).stdout


def timed(pre: str, index: str, query: str) -> list[float]:
    out: list[float] = []
    for i in range(N):
        steps = [s for s in (pre, index) if s]
        sql = "BEGIN;\n" + "".join(f"{s};\n" for s in steps)
        sql += f"EXPLAIN (ANALYZE, FORMAT JSON) {query.format(i=i)};\nROLLBACK;\n"
        text = _psql(sql)
        out.append(json.loads(text[text.index("[") : text.rindex("]") + 1])[0]["Execution Time"])
    return out


def main() -> None:
    for name, (pre, index, query) in CASES.items():
        before, after = timed(pre, "", query), timed(pre, index, query)
        print(f"{name}: median {statistics.median(before):.2f} ms -> {statistics.median(after):.2f} ms (n={N})")


if __name__ == "__main__":
    main()
