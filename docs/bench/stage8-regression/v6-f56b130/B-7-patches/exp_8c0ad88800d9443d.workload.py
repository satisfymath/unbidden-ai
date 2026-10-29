import sys
sys.path.insert(0, "/work/.")
from datetime import datetime, timezone
from typing import Callable

async def build(authorized_client, pool, test_user):
    # Use the test user's id for article authorship and comment authorship
    user_id = test_user.id

    async with pool.acquire() as conn:
        # Determine starting ids to avoid collisions
        article_max = await conn.fetchval("SELECT COALESCE(MAX(id),0) FROM articles")
        comment_max = await conn.fetchval("SELECT COALESCE(MAX(id),0) FROM commentaries")

        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S%z")

        # Create 2000 distinct articles
        n_articles = 2000
        article_values = []
        for i in range(n_articles):
            aid = article_max + 1 + i
            slug = f"workload-article-{i}"
            title = f"Workload Article {i}"
            # id, slug, title, description, body, author_id, created_at, updated_at
            article_values.append(
                f"({aid}, '{slug}', '{title}', 'desc {i}', 'body {i}', {user_id}, '{now_str}', '{now_str}')"
            )
        articles_sql = (
            "INSERT INTO articles (id, slug, title, description, body, author_id, created_at, updated_at) VALUES "
            + ",".join(article_values)
        )
        await conn.execute(articles_sql)

        # Create 200000 commentaries spread over the 2000 articles (100 per article)
        n_comments = 200_000
        comments_per_article = n_comments // n_articles
        comment_values = []
        cid = comment_max + 1
        for i in range(n_articles):
            aid = article_max + 1 + i
            for _ in range(comments_per_article):
                comment_values.append(
                    f"({cid}, 'comment body', {user_id}, {aid}, '{now_str}', '{now_str}')"
                )
                cid += 1
        comments_sql = (
            "INSERT INTO commentaries (id, body, author_id, article_id, created_at, updated_at) VALUES "
            + ",".join(comment_values)
        )
        await conn.execute(comments_sql)

        await conn.execute("ANALYZE")

    # Prepare 23 distinct targets for repeated calls
    slugs = [f"workload-article-{i}" for i in range(23)]
    idx = 0

    async def _call() -> int:
        nonlocal idx
        slug = slugs[idx % len(slugs)]
        idx += 1
        resp = await authorized_client.get(f"/api/articles/{slug}/comments")
        return resp.status_code

    return _call
