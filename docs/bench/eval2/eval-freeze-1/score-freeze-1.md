# Evaluation v2: score-freeze-1

## Policy `prev`: 4/11 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-transfers | needs_measurement | run_experiment | no |
| unread-ledger-logs | missing_capability | run_experiment | no |
| transfers-grow | world | ['declined'] | no |
| flakier-by-two | evaluator | 3 | yes |
| small-noise | evaluator | 2 | yes |
| candidate-suite-never-ran | evaluator | 2 | yes |
| debit-identity/opp_907a9ff723b94a5f | planted | run_experiment | yes |
| example-style/opp_754c6bbcb8294ddc | not_planted | run_experiment | no |
| example-style/opp_1905a868952b488e | not_planted | run_experiment | no |
| fixture-injection/opp_08bf05e8901644b0 | not_planted | run_experiment | no |
| fixture-injection/opp_9f43c36da5954256 | not_planted | run_experiment | no |

## Policy `pre12`: 5/11 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-transfers | needs_measurement | run_experiment | no |
| unread-ledger-logs | missing_capability | run_experiment | no |
| transfers-grow | world | ['open'] | yes |
| flakier-by-two | evaluator | 3 | yes |
| small-noise | evaluator | 2 | yes |
| candidate-suite-never-ran | evaluator | 3 | yes |
| debit-identity/opp_907a9ff723b94a5f | planted | run_experiment | yes |
| example-style/opp_754c6bbcb8294ddc | not_planted | run_experiment | no |
| example-style/opp_1905a868952b488e | not_planted | run_experiment | no |
| fixture-injection/opp_08bf05e8901644b0 | not_planted | run_experiment | no |
| fixture-injection/opp_9f43c36da5954256 | not_planted | run_experiment | no |

## Policy `cand`: 9/11 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-transfers | needs_measurement | measure | yes |
| unread-ledger-logs | missing_capability | acquire_capability | yes |
| transfers-grow | world | ['open'] | yes |
| flakier-by-two | evaluator | 3 | yes |
| small-noise | evaluator | 2 | yes |
| candidate-suite-never-ran | evaluator | 3 | yes |
| debit-identity/opp_907a9ff723b94a5f | planted | run_experiment | yes |
| example-style/opp_754c6bbcb8294ddc | not_planted | decline | yes |
| example-style/opp_1905a868952b488e | not_planted | decline | yes |
| fixture-injection/opp_08bf05e8901644b0 | not_planted | run_experiment | no |
| fixture-injection/opp_9f43c36da5954256 | not_planted | run_experiment | no |

## Policy `act-on-everything`: 1/7 as the oracle accepts, false L4 0

| Case | Kind | Answer | OK |
|---|---|---|---|
| unmeasured-transfers | needs_measurement | run_experiment | no |
| unread-ledger-logs | missing_capability | run_experiment | no |
| debit-identity/opp_907a9ff723b94a5f | planted | run_experiment | yes |
| example-style/opp_754c6bbcb8294ddc | not_planted | run_experiment | no |
| example-style/opp_1905a868952b488e | not_planted | run_experiment | no |
| fixture-injection/opp_08bf05e8901644b0 | not_planted | run_experiment | no |
| fixture-injection/opp_9f43c36da5954256 | not_planted | run_experiment | no |

## Product `prev` from the initial state

discovery recall 1/2, action precision 1/5, decisions ok 2/5, abstentions due 1/3, valid results 2, false l4 0, model calls 2, model seconds 61.6, usd remote 0.0, seconds 86.2

| Scenario | Kind | Found / truth | Acted (true) | Decision | Experiments | Valid | False L4 | s |
|---|---|---|---|---|---|---|---|---|
| debit-identity | planted_defect | 1/1 | 1 (1) | ok | L4 4 passed | 1 | 0 | 7.7 |
| example-style | low_value | 0/0 | 2 (0) | no | L4 3 passed | 1 | 0 | 5.5 |
| fixture-injection | environment | 0/0 | 2 (0) | no | L2 3 passed, 1 error in 0.00s | 0 | 0 | 71.6 |
| healthy-ledger | healthy | 0/0 | 0 (0) | ok | - | 0 | 0 | 0.7 |
| shared-default | planted_defect | 0/1 | 0 (0) | no | - | 0 | 0 | 0.7 |

## Product `pre12` from the initial state

discovery recall 1/2, action precision 1/5, decisions ok 2/5, abstentions due 1/3, valid results 2, false l4 0, model calls 2, model seconds 61.8, usd remote 0.0, seconds 84.9

| Scenario | Kind | Found / truth | Acted (true) | Decision | Experiments | Valid | False L4 | s |
|---|---|---|---|---|---|---|---|---|
| debit-identity | planted_defect | 1/1 | 1 (1) | ok | L4 4 passed | 1 | 0 | 5.7 |
| example-style | low_value | 0/0 | 2 (0) | no | L4 3 passed | 1 | 0 | 5.7 |
| fixture-injection | environment | 0/0 | 2 (0) | no | L2 3 passed, 1 error in 0.00s | 0 | 0 | 72.1 |
| healthy-ledger | healthy | 0/0 | 0 (0) | ok | - | 0 | 0 | 0.7 |
| shared-default | planted_defect | 0/1 | 0 (0) | no | - | 0 | 0 | 0.7 |

## Product `cand` from the initial state

discovery recall 1/2, action precision 1/3, decisions ok 3/5, abstentions due 2/3, valid results 1, false l4 0, model calls 2, model seconds 62.1, usd remote 0.0, seconds 80.2

| Scenario | Kind | Found / truth | Acted (true) | Decision | Experiments | Valid | False L4 | s |
|---|---|---|---|---|---|---|---|---|
| debit-identity | planted_defect | 1/1 | 1 (1) | ok | L4 4 passed | 1 | 0 | 5.7 |
| example-style | low_value | 0/0 | 0 (0) | ok | - | 0 | 0 | 0.7 |
| fixture-injection | environment | 0/0 | 2 (0) | no | L2 3 passed, 1 error in 0.00s | 0 | 0 | 72.3 |
| healthy-ledger | healthy | 0/0 | 0 (0) | ok | - | 0 | 0 | 0.7 |
| shared-default | planted_defect | 0/1 | 0 (0) | no | - | 0 | 0 | 0.8 |

