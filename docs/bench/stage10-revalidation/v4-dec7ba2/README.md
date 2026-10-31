# Revalidation of fst under perf-v4 at product dec7ba2: the corrected functional comparison

49d3259 confirmed fst's L4 with a comparison that set aside any uuid- or timestamp-shaped value and sorted every
list; that comparison could have hidden a changed owner, exchanged dates or another order, so its confirmation is
kept as recorded but not relied on. dec7ba2 compares the content call by call, lists in order, through one
correspondence per session of the ids and times the application generated (one to one, order of times kept), with
adversarial controls in tests/unit/test_workload_validation.py and tests/unit/test_equivalence.py.

- fst `opp_56f9d3d9ace0468f` (item.owner_id): **improved, L4 confirmed** (US$0.0292). GET /api/v1/items/:
  11.74 -> 3.65 ms (+69%), p = 0.0286, interval [+67%, +70%]; mechanism observed; A/A control -2%; confirmation
  11.66 -> 3.61 ms (+69%), p = 0.0286; "the same 20 responses on both sides, in every session, up to one
  correspondence per session of the ids and times the application generated".
- mealie `opp_8f2cf46bd8864983`: stays **blocked** (v4-49d3259: no valid workload); its L4 is not confirmed.
