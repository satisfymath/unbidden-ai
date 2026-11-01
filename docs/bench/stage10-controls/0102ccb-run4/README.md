# Evaluator controls, fourth run at product 0102ccb: 7 of 7, on a quiet host

The same frozen worktree (`~/unbidden-ai-s10-0102ccb`), inputs, evaluator, thresholds, expected outcomes, fixtures
and protocol as the third run; no model, no spend. Approved by David: the two Prefect lab containers were stopped for
the run and restored (host.log). Both belong only to the `prefect-staging` compose project
(`~/unbidden-lab/prefect/docker-compose.lab.yml`): their own network with no other member, ports on 127.0.0.1 only,
no host-side connection, the database's clients only the Prefect server. Original state running; stopped 12:41:15;
quiet (1-minute load below 1.5 three times, 30 s apart) at 12:53:16; controls 12:53 - 13:07; both restored running at
13:07:33. Nothing deleted.

| Case | Unit test | Expected | Outcome | Passed |
|---|---|---|---|---|
| real_improvement | test_a_real_improvement_with_its_mechanism_function_control_and_confirmation_is_promoted | improved | improved: 11.33 -> 3.41 ms (+70%), mechanism, A/A, confirmation | yes |
| unchanged | test_the_unchanged_candidate_is_no_relevant_change | no_relevant_change | no_relevant_change (-0%, interval -7% .. +4%) | yes |
| irrelevant_index | test_an_irrelevant_index_is_not_promoted_even_if_faster | not improved, index unused | no_relevant_change (-8%), 0 scans | yes |
| workload_without_the_column | test_a_workload_that_does_not_use_the_column_shows_no_mechanism | not improved | no_relevant_change (-2%) | yes |
| slower | test_a_slower_candidate_is_a_regression | regression | regression (11.3 -> 22.6 ms) | yes |
| near_threshold | test_near_the_threshold_a_first_pass_is_not_enough | not improved | no_relevant_change (+12%, +10% .. +17%) | yes |
| faster_wrong_answer | test_a_faster_wrong_answer_is_a_regression | regression, result differs | regression: +69% faster, one item missing | yes |

This run does not erase the third: on a host that was not quiet the A/A case was inconclusive (0102ccb/README.md),
which is what the criteria should do, and is reported with it. The controls depend on a quiet host; the evaluation's
runs are made with the same precaution recorded.
