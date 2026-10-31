# Revalidation under perf-v4 at product 49d3259: fst and mealie

Frozen worktree `~/unbidden-ai-s10-49d3259`, `s10-dev`. Same protocol as v4-f9fe965.

- fst `opp_56f9d3d9ace0468f` (item.owner_id): **improved, L4 confirmed under perf-v4** (US$0.0287). GET
  /api/v1/items/: 12.68 -> 3.57 ms (+72%), p = 0.0286, interval [+69%, +73%]; mechanism observed (index scans in every
  candidate session); A/A control -1%; confirmation in 4 new sessions per side 12.42 -> 3.61 ms (+71%), p = 0.0286;
  the same 20 responses on both sides in every session; tests passed on both sides.
- mealie `opp_8f2cf46bd8864983` (shopping_list_items.food_id): **blocked, no valid workload** (US$0.1259). The
  fixtures are now visible and the workloads run, but in all 5 attempts the calls ran no statement reading
  shopping_list_items by food_id and 0 rows were inserted into shopping_list_items (the request returned `[]`). The
  original L4 is not confirmed under perf-v4; the block is the workload, recorded as found. Open.
