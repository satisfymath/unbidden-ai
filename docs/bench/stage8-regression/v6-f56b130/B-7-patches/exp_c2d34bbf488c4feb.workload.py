import datetime

N_USERS = 2000
N_ARTICLES = 200000

async def build(pool, authorized_client, test_user):
    follower_id = int(getattr(test_user, "id", 1))
    ts = "2024-01-01 00:00:00+00"

    # --- users bulk insert (one statement) ---
    # ids: avoid colliding with test_user id; start at 1_000_000
    base_uid = 1000000
    u_vals = []
    for i in range(N_USERS):
        uid = base_uid + i
        u_vals.append(
            f"({uid},'wu{uid}','wu{uid}@ex.com','s','h','b','{ts}','{ts}')"
        )
    users_sql = (
        "INSERT INTO users (id, username, email, salt, hashed_password, bio, created_at, updated_at) VALUES "
        + ",".join(u_vals)
    )

    # --- followers bulk insert (one statement): test_user follows all ---
    f_vals = [f"({follower_id},{base_uid + i})" for i in range(N_USERS)]
    foll_sql = (
        "INSERT INTO followers_to_followings (follower_id, following_id) VALUES "
        + ",".join(f_vals)
    )

    # --- articles bulk insert (one statement) ---
    # spread evenly: article j -> author base_uid + (j % N_USERS)
    a_vals = []
    for j in range(N_ARTICLES):
        aid_author = base_uid + (j % N_USERS)
        # short literals to keep statement small; slug must be unique
        a_vals.append(
            f"('ws{j}','t','d','b',{aid_author},'{ts}','{ts}')"
        )
    arts_sql = (
        "INSERT INTO articles (slug, title, description, body, author_id, created_at, updated_at) VALUES "
        + ",".join(a_vals)
    )

    conn_cm = pool.acquire()
    # pool.acquire() may be async context manager or coroutine returning one
    try:
        # try async with pattern
        async with pool.acquire() as conn:
            await conn.execute(users_sql)
            await conn.execute(foll_sql)
            await conn.execute(arts_sql)
            try:
                await conn.execute("ANALYZE")
            except Exception:
                pass
            # commit if backend needs it
            try:
                c = getattr(conn, "commit", None)
                if c is not None:
                    r = c()
                    if hasattr(r, "__await__"):
                        await r
            except Exception:
                pass
    except Exception:
        # fallback: acquire returns awaitable connection without context manager
        conn = await pool.acquire()
        try:
            await conn.execute(users_sql)
            await conn.execute(foll_sql)
            await conn.execute(arts_sql)
            try:
                await conn.execute("ANALYZE")
            except Exception:
                pass
            try:
                c = getattr(conn, "commit", None)
                if c is not None:
                    r = c()
                    if hasattr(r, "__await__"):
                        await r
            except Exception:
                pass
            try:
                rel = getattr(conn, "release", None)
                if rel is not None:
                    r = rel()
                    if hasattr(r, "__await__"):
                        await r
                else:
                    close = getattr(conn, "close", None)
                    if close is not None:
                        r = close()
                        if hasattr(r, "__await__"):
                            await r
            except Exception:
                pass
        except Exception:
            raise

    async def run():
        resp = await authorized_client.get("/api/articles/feed")
        return resp.status_code

    return run
