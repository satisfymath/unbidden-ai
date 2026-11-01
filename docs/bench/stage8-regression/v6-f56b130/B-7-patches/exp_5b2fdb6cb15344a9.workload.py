import datetime
import inspect

NUM_USERS = 2000
NUM_ARTICLES = 200000
USER_ID_BASE = 100000
ARTICLE_ID_BASE = 2000000


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


async def _maybe(v):
    if inspect.isawaitable(v):
        return await v
    return v


async def build(pool, authorized_client, test_user):
    pool = await _maybe(pool)
    authorized_client = await _maybe(authorized_client)
    test_user = await _maybe(test_user)

    try:
        follower_id = int(test_user.id)
    except Exception:
        try:
            follower_id = int(test_user["id"])
        except Exception:
            follower_id = int(getattr(test_user, "get", lambda k: 1)("id"))

    now = datetime.datetime.now(datetime.timezone.utc)
    # format timestamp literal usable by both postgres and sqlite
    ts = now.strftime("%Y-%m-%d %H:%M:%S.%f+00")

    # ---- users: one multi-row INSERT ----
    user_vals = []
    for i in range(NUM_USERS):
        uid = USER_ID_BASE + i
        username = f"seeduser{i:05d}"
        email = f"seeduser{i:05d}@example.com"
        user_vals.append(
            f"({uid},{_q(username)},{_q(email)},{_q('s')},{_q('h')},{_q('bio')},NULL,{_q(ts)},{_q(ts)})"
        )
    users_sql = (
        "INSERT INTO users (id, username, email, salt, hashed_password, bio, image, created_at, updated_at) VALUES "
        + ",".join(user_vals)
    )

    # ---- followers: test_user follows all seeded users, one statement ----
    fol_vals = [f"({follower_id},{USER_ID_BASE + i})" for i in range(NUM_USERS)]
    fol_sql = (
        "INSERT INTO followers_to_followings (follower_id, following_id) VALUES "
        + ",".join(fol_vals)
    )

    # ---- articles: 200k rows spread over 2000 users, one statement ----
    per = NUM_ARTICLES // NUM_USERS
    art_vals = []
    aid = ARTICLE_ID_BASE
    for i in range(NUM_USERS):
        author = USER_ID_BASE + i
        for j in range(per):
            slug = f"seed-slug-{aid}"
            art_vals.append(
                f"({aid},{_q(slug)},{_q('title x')},{_q('desc x')},{_q('body body body')},{author},{_q(ts)},{_q(ts)})"
            )
            aid += 1
    # remainder if any
    while len(art_vals) < NUM_ARTICLES:
        slug = f"seed-slug-{aid}"
        art_vals.append(
            f"({aid},{_q(slug)},{_q('title x')},{_q('desc x')},{_q('body body body')},{USER_ID_BASE},{_q(ts)},{_q(ts)})"
        )
        aid += 1
    articles_sql = (
        "INSERT INTO articles (id, slug, title, description, body, author_id, created_at, updated_at) VALUES "
        + ",".join(art_vals)
    )

    async with pool.acquire() as conn:
        await conn.execute(users_sql)
        await conn.execute(fol_sql)
        await conn.execute(articles_sql)
        # commit if the engine needs it
        try:
            commit = getattr(conn, "commit", None)
            if callable(commit):
                r = commit()
                if inspect.isawaitable(r):
                    await r
        except Exception:
            pass
        try:
            await conn.execute("ANALYZE")
        except Exception:
            pass

    async def run() -> int:
        resp = await authorized_client.get("/api/articles/feed")
        return resp.status_code

    return run
