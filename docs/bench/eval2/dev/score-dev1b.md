# Evaluation v2: score-dev1b

## Policy `prev`: 4/9 as the oracle accepts, false L4 1

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-fk | needs_measurement | run_experiment | no |
| unread-logs | missing_capability | run_experiment | no |
| data-growth | world | ['declined'] | no |
| flaky-candidate | evaluator | 3 | yes |
| noise-improvement | evaluator | 2 | yes |
| suite-never-ran | evaluator | 4 | no |
| crash-shadowed-import/opp_813716aecab54c4b | planted | run_experiment | yes |
| hidden-duplicate-test/opp_ea1936107b2d4e8d | planted | run_experiment | yes |
| low-value-style/opp_fdc681a843f74279 | not_planted | run_experiment | no |

## Policy `cur`: 6/9 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-fk | needs_measurement | run_experiment | no |
| unread-logs | missing_capability | run_experiment | no |
| data-growth | world | ['open'] | yes |
| flaky-candidate | evaluator | 3 | yes |
| noise-improvement | evaluator | 2 | yes |
| suite-never-ran | evaluator | 3 | yes |
| crash-shadowed-import/opp_813716aecab54c4b | planted | run_experiment | yes |
| hidden-duplicate-test/opp_ea1936107b2d4e8d | planted | run_experiment | yes |
| low-value-style/opp_fdc681a843f74279 | not_planted | run_experiment | no |

## Policy `dev1`: 9/9 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-fk | needs_measurement | measure | yes |
| unread-logs | missing_capability | acquire_capability | yes |
| data-growth | world | ['open'] | yes |
| flaky-candidate | evaluator | 3 | yes |
| noise-improvement | evaluator | 2 | yes |
| suite-never-ran | evaluator | 3 | yes |
| crash-shadowed-import/opp_813716aecab54c4b | planted | run_experiment | yes |
| hidden-duplicate-test/opp_ea1936107b2d4e8d | planted | run_experiment | yes |
| low-value-style/opp_fdc681a843f74279 | not_planted | decline | yes |

## Policy `act-on-everything`: 2/5 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-fk | needs_measurement | run_experiment | no |
| unread-logs | missing_capability | run_experiment | no |
| crash-shadowed-import/opp_813716aecab54c4b | planted | run_experiment | yes |
| hidden-duplicate-test/opp_ea1936107b2d4e8d | planted | run_experiment | yes |
| low-value-style/opp_fdc681a843f74279 | not_planted | run_experiment | no |

