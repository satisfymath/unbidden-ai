# Revalidation of mealie under perf-v4 at product f9bc751 (the matrix entry on the job's database): blocked, next cause found

Worktree `~/unbidden-ai-s10-f9bc751`, `s10-dev` (US$0.1459), 246 s. mealie `opp_8f2cf46bd8864983`
(shopping_list_items.food_id, L4 before): **blocked, no valid workload** — but no longer for the earlier reason.

- The suite now runs on Postgres (matrix entry `Database=postgres`, f9bc751): every attempt seeded **200,000 rows**
  into shopping_list_items and `GET /api/foods/empty` answered with data (before: 0 rows, `[]`).
- Four of five attempts were refused as "the calls did not run a statement that reads shopping_list_items by
  food_id on every call"; one failed on a DeprecationWarning the suite treats as an error.
- Reproduced offline with the fifth workload (no model): the engine ran, on all 23 calls, a statement reading
  shopping_list_items by food_id (an EXISTS subquery about 500 characters in), but the record kept the statement's
  first 400 characters and the validator re-read that cut. A defect of the lab's (fixed in 2ea1fd1: the statement is
  kept whole, up to 8,000 characters). The L4 stays unconfirmed; rerun from a worktree at 2ea1fd1.
