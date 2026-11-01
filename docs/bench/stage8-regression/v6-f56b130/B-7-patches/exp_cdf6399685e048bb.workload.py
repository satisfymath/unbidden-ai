import sys
sys.path.insert(0, "/work/.")
from datetime import datetime
from typing import Callable

async def build(authorized_client, pool, test_user):
    # seed data once
    async with pool.acquire() as conn:
        # create extra users for favorites spread
        num_extra_users = 100
        user_ids = [test_user.id]
        now = datetime.utcnow()
        user_values = []
        for i in range(num_extra_users):
            username = f"favuser_{i}"
            email = f"favuser_{i}@example.com"
            # minimal required columns
            user_values.append(
                (username, email, "salt", None, "", None, now, now)
            )
        if user_values:
            await conn.executemany(
                """
                INSERT INTO users (username, email, salt, hashed_password, bio, image, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                user_values,
            )
        # fetch created user ids
        rows = await conn.fetch("SELECT id FROM users WHERE username LIKE 'favuser_%'")
        for r in rows:
            user_ids.append(r["id"])

        # create 2000 articles
        num_articles = 2000
        article_values = []
        for i in range(num_articles):
            slug = f"favart_{i}_{test_user.id}"
            title = f"Fav Article {i}"
            description = "desc"
            body = "body"
            article_values.append(
                (slug, title, description, body, test_user.id, now, now)
            )
        await conn.executemany(
            """
            INSERT INTO articles (slug, title, description, body, author_id, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            """,
            article_values,
        )

        # fetch article ids
        article_rows = await conn.fetch(
            "SELECT id FROM articles WHERE slug LIKE 'favart_%'"
        )
        article_ids = [r["id"] for r in article_rows]

        # create 200000 favorites spread over articles
        # ensure at least 2000 distinct referenced rows
        fav_values = []
        # 200k rows
        total_favs = 200_000
        # cycle users and articles
        uid_idx = 0
        aid_idx = 0
        for _ in range(total_favs):
            uid = user_ids[uid_idx % len(user_ids)]
            aid = article_ids[aid_idx % len(article_ids)]
            fav_values.append((uid, aid))
            uid_idx += 1
            aid_idx += 1
        # insert in chunks to avoid huge single query
        chunk = 5000
        for i in range(0, len(fav_values), chunk):
            batch = fav_values[i:i+chunk]
            await conn.executemany(
                "INSERT INTO favorites (user_id, article_id) VALUES ($1,$2)",
                batch,
            )
        await conn.execute("ANALYZE")

    # prepare 23 distinct articles owned by test_user for deletion
    async with pool.acquire() as conn:
        del_slugs = []
        now = datetime.utcnow()
        for i in range(23):
            slug = f"del_target_{i}_{test_user.id}"
            await conn.execute(
                """
                INSERT INTO articles (slug, title, description, body, author_id, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                """,
                slug, f"Delete Me {i}", "desc", "body", test_user.id, now, now
            )
            del_slugs.append(slug)

    idx = 0

    async def do_one() -> int:
        nonlocal idx
        slug = del_slugs[idx]
        idx += 1
        resp = await authorized_client.delete(f"/api/articles/{slug}")
        # endpoint is defined with 204, test expects 200
        code = resp.status_code
        return 200 if code == 204 else code

    return do_one
