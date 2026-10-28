# Evaluation v2: score-exp-0

## Policy `act-on-everything`: 2/5 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-fk | needs_measurement | run_experiment | no |
| unread-logs | missing_capability | run_experiment | no |
| crash-shadowed-import/opp_813716aecab54c4b | planted | run_experiment | yes |
| hidden-duplicate-test/opp_ea1936107b2d4e8d | planted | run_experiment | yes |
| low-value-style/opp_fdc681a843f74279 | not_planted | run_experiment | no |

## Product `prev` from the initial state

discovery recall 2/2, action precision 2/2, decisions ok 2/2, abstentions due 0/0, valid results 2, false l4 0, model calls 2, seconds 71.4

| Scenario | Kind | Found / truth | Acted (true) | Decision | Experiments | Valid | False L4 | s |
|---|---|---|---|---|---|---|---|---|
| crash-shadowed-import | planted_defect | 1/1 | 1 (1) | ok | L4 5 passed | 1 | 0 | 34.1 |
| hidden-duplicate-test | planted_defect | 1/1 | 1 (1) | ok | L4 4 passed | 1 | 0 | 37.3 |

## Product `cur` from the initial state

discovery recall 2/2, action precision 2/2, decisions ok 2/2, abstentions due 0/0, valid results 2, false l4 0, model calls 2, seconds 78.2

| Scenario | Kind | Found / truth | Acted (true) | Decision | Experiments | Valid | False L4 | s |
|---|---|---|---|---|---|---|---|---|
| crash-shadowed-import | planted_defect | 1/1 | 1 (1) | ok | L4 5 passed | 1 | 0 | 40.4 |
| hidden-duplicate-test | planted_defect | 1/1 | 1 (1) | ok | L4 4 passed | 1 | 0 | 37.8 |

