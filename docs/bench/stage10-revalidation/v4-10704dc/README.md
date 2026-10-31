# Revalidation of mealie under perf-v4 at product 10704dc (the statement kept whole): measured, no relevant change

Worktree `~/unbidden-ai-s10-10704dc`, `s10-dev` (US$0.0254; cumulative 27.6945 -> 27.7199), 1516 s (27 host
deferrals, 0 - 360 s per session, loads 1.17 - 1.43 at measurement). mealie `opp_8f2cf46bd8864983`
(`shopping_list_items.food_id`, L4 at stage 8, L5 on SQLite in `docs/bench/2026-10-28-mealie-l5-result.md`).

- **The workload is valid at the first attempt** (after 2ea1fd1): 200,000 rows in shopping_list_items, 2,500 foods,
  20 lists; 20 measured calls of `GET /api/foods/empty`, HTTP 200 with data; the engine ran a statement reading
  shopping_list_items by food_id on every call. The validator read the statement whole.
- **Measured on PostgreSQL** (the job's own service, f9bc751), 4 sessions per arm, alternating: medians
  215.24 -> 207.14 ms, +4% faster, permutation p 0.029, 95% interval +1% .. +13%. The index was used (57,546 scans
  per candidate session, 0 at the base). **No change of 20% or more: `no_relevant_change`**, level 1 after.
  No A/A or confirmation (none is run without an improvement). The project's tests: 3640 collected, 18 failed on
  both sides (the NLP parser, pre-existing).
- **Reading.** The earlier result (10,934 -> 8.1 ms in the lab, 11.8 -> 2.2 ms live) was measured on SQLite with
  perf-v2/v3 and a different workload; on PostgreSQL with this workload the same index changes little: the planner
  does not depend on it for this query at this data. The L4 is **not confirmed under perf-v4 on PostgreSQL**; the
  SQLite result stands as what it was, on its engine, under its criteria. Under the campaign's rule (promotions
  affected by evaluator changes are revalidated), mealie counts as unconfirmed, not as an improvement.
- No action; nothing promoted; the record is kept (`mealie-10704dc.json`).
