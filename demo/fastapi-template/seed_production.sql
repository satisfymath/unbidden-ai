-- Scenario: the team's production holds real-looking data. Played by this script, declared as a scenario.
-- 2,000 users and 200,000 items, in the live database of the demo deployment.
INSERT INTO "user" (id, email, is_active, is_superuser, full_name, hashed_password, created_at)
SELECT gen_random_uuid(), 'customer' || g.i || '@example.com', true, false, 'Customer ' || g.i, 'x', now()
FROM generate_series(1, 2000) AS g(i)
ON CONFLICT DO NOTHING;

WITH owners AS (SELECT id, row_number() OVER (ORDER BY email) AS n FROM "user" WHERE email LIKE 'customer%')
INSERT INTO item (id, title, description, owner_id, created_at)
SELECT gen_random_uuid(), 'Item ' || g.i, 'seeded', o.id, now() - (g.i || ' seconds')::interval
FROM generate_series(1, 200000) AS g(i)
JOIN owners o ON o.n = 1 + (g.i % 2000);

ANALYZE "user";
ANALYZE item;
