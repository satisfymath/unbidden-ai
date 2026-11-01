# Evaluator controls, third run at product 0102ccb: 6 of 7, the A/A case too noisy

Same inputs as the earlier runs; no model, no spend. Kept as found.

| Case | Expected | Outcome | Passed |
|---|---|---|---|
| real_improvement | improved | improved (see real_improvement.json) | yes |
| unchanged | no_relevant_change | inconclusive: -5%, 95% interval -32% .. +13% | no |
| irrelevant_index | not improved, index unused | inconclusive (+2%, -27% .. +24%), 0 scans | yes |
| workload_without_the_column | not improved | inconclusive (-3%) | yes |
| slower | regression | regression (12.2 -> 21.6 ms) | yes |
| near_threshold | not improved | no_relevant_change (+17%, +13% .. +20%) | yes |
| faster_wrong_answer | regression, result differs | regression: +72% faster, one item missing | yes |

The A/A case's sessions ranged 10.9 .. 15.6 ms (11.0 .. 11.6 in the first two runs): the host was not quiet. The
Prefect lab service (`prefect-staging-server-1`, `prefect-staging-db-1`) ran at about 28% CPU throughout (load
average 3.4). The criteria are not loosened: a noisy A/A is inconclusive, as it should be. The controls have not
passed on one commit yet; the freeze waits. Stopping that service was refused by this session's permission
classifier; it is the person's decision.
