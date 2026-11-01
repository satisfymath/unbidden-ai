# Revalidation under perf-v4 at product f9fe965: fst and mealie

Frozen worktree `~/unbidden-ai-s10-f9fe965`, `s10-dev`. Isolated clones in `~/unbidden-lab/reval/`, workspaces in
`~/unbidden-lab/reval-runs/`; the original repositories and stores only read.

- fst `opp_56f9d3d9ace0468f` (item.owner_id, L4 before): **inconclusive, level 1 after** (US$0.0255, 255 s). GET
  /api/v1/items/: session medians 12.31 -> 3.43 ms (+72%), p = 0.0286, mechanism observed (index scans in every
  candidate session); tests passed on both sides. Not improved because "the functional result was not observed on
  both sides": each session's 20 responses were identical, but every session, base included, had another digest —
  the workload creates its data through the application, which gives uuid4 ids and creation times. Fixed in the next
  commit (values shaped as a uuid or a timestamp compare as "generated").
- mealie `opp_8f2cf46bd8864983` (shopping_list_items.food_id, L4 before): **blocked, no valid workload** (US$0.1694,
  230 s). Workloads refused before running: `build` asked for `unique_user`, taken as invisible; mealie's conftest
  loads it through `from tests.fixtures import *` and the package's `from .fixture_users import *`. One attempt ran
  and failed with a 422. Fixed in the next commit (fixture visibility follows packages and their relative re-exports).

Neither original L4 is confirmed under perf-v4 yet; both are rerun after the fixes.
