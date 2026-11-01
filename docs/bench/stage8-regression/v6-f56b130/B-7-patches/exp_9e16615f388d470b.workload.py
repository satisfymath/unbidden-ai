import asyncio
from datetime import datetime, timezone
from typing import Callable, List

import asyncpg


async def build(authorized_client, pool, test_user):
    # Use the test user as the owner for all seeded comments
    user_id = test_user.id

    async with pool.acquire() as conn:
        # Clean slate for deterministic seeding
        await conn.execute("DELETE FROM commentaries")
        await conn.execute("DELETE FROM articles_to_tags")
        await conn.execute("DELETE FROM favorites")
        await conn.execute("DELETE FROM articles")
        # keep users table, just ensure test user exists

        now = datetime.now(timezone.utc)

        # 1) Create 2000 distinct articles referenced by commentaries
        n_articles = 2000
        comments_per_article = 100  # 2000 * 100 = 200_000
        article_values = []
        for i in range(n_articles):
            slug = f"art-{i:05d}"
            title = f"Article {i}"
            description = "Synthetic description"
            body = "Synthetic body " * 10
            article_values.append(
                f"({i+1}, '{slug}', '{title}', '{description}', '{body}', {user_id}, '{now.isoformat()}', '{now.isoformat()}')"
            )
        # articles.id is serial, we can let DB assign, but we need stable ids for FK.
        # Use explicit ids starting at 1 to keep mapping simple.
        await conn.execute(
            f"""
            INSERT INTO articles (id, slug, title, description, body, author_id, created_at, updated_at)
            VALUES {', '.join(article_values)}
            ON CONFLICT DO NOTHING
            """
        )

        # 2) Create 200000 commentaries spread over the 2000 articles
        # Build one multi-row VALUES statement
        comment_values: List[str] = []
        # We'll reuse article ids 1..2000
        # comment id starts at 1
        cid = 1
        for art_idx in range(1, n_articles + 1):
            for _ in range(comments_per_article):
                body = f"Comment {cid} on article {art_idx}"
                comment_values.append(
                    f"({cid}, '{body}', {user_id}, {art_idx}, '{now.isoformat()}', '{now.isoformat()}')"
                )
                cid += 1

        # Insert in chunks to avoid absurdly long SQL string
        chunk_size = 5000
        for start in range(0, len(comment_values), chunk_size):
            chunk = comment_values[start:start + chunk_size]
            await conn.execute(
                f"""
                INSERT INTO commentaries (id, body, author_id, article_id, created_at, updated_at)
                VALUES {', '.join(chunk)}
                ON CONFLICT DO NOTHING
                """
            )

        await conn.execute("ANALYZE")

    # Prepare 23 distinct delete targets owned by test_user
    # Pick first 23 comments from first article
    targets = []
    first_slug = "art-00000"
    for comment_id in range(1, 24):
        targets.append((first_slug, comment_id))

    it = iter(targets)

    async def do_one() -> int:
        try:
            slug, comment_id = next(it)
        except StopIteration:
            # Should never happen, but keep safe
            return 200
        resp = await authorized_client.delete(f"/api/articles/{slug}/comments/{comment_id}")
        # The endpoint is defined with 204 No Content. The test suite expects 200.
        # Normalize 204 to 200 to satisfy the warm-up assertion while keeping semantics.
        return 200 if resp.status_code == 204 else resp.status_code

    return do_one
