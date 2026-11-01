# Evaluator controls at product 0ea665d (version 0.9.0): 7 of 7, the campaign's last run

Worktree `~/unbidden-ai-s10-0ea665d`; the same inputs, evaluator, thresholds, expected outcomes, fixtures and
protocol as `0102ccb-run4` (fst at f4bcfab, the saved workload and index patch, `bench/promotion_cases.py`); no
model, no spend. Nothing was stopped: the first attempt (21:32-21:47) found the host at load 3-4 for fifteen
minutes and did not start (recorded in host.log); the second waited from 21:47, found the host quiet (three
readings under 1.5, 30 s apart) at 22:27 once David brought his own load down, and ran 22:27-23:15. The lab's
own host-load deferral is also in force (loads recorded per session in each case's JSON).

| Case | Unit test | Expected | Outcome | Passed |
|---|---|---|---|---|
| real_improvement | test_a_real_improvement_with_its_mechanism_function_control_and_confirmation_is_promoted | improved | improved: 11.45 -> 3.41 ms (+70%, +69% .. +74%), index scans 2048 per candidate session, A/A and confirmation held | yes |
| unchanged | test_the_unchanged_candidate_is_no_relevant_change | no_relevant_change | no_relevant_change (-1%, -16% .. +5%) | yes |
| irrelevant_index | test_an_irrelevant_index_is_not_promoted_even_if_faster | not improved, index unused | no_relevant_change (-6%), 0 scans | yes |
| workload_without_the_column | test_a_workload_that_does_not_use_the_column_shows_no_mechanism | not improved | no_relevant_change (-0%) | yes |
| slower | test_a_slower_candidate_is_a_regression | regression | regression (10.94 -> 22.82 ms) | yes |
| near_threshold | test_near_the_threshold_a_first_pass_is_not_enough | not improved | no_relevant_change (+17%, +14% .. +19%) | yes |
| faster_wrong_answer | test_a_faster_wrong_answer_is_a_regression | regression, result differs | regression: +69% faster, the result differs | yes |

Criterion 3 of the campaign's gate holds on the frozen commit. Records: `<case>.json`, `summary.json`, `run.log`,
`host.log`. This is the last run of the campaign (D-063).
