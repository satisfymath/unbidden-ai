# Evaluator controls, second run at product 1d847e8: 6 of 7, one harness defect

Same inputs as c9e359e; no model, no spend. Kept as found.

| Case | Expected | Outcome | Passed |
|---|---|---|---|
| real_improvement | improved | improved: 11.36 -> 3.53 ms (+69%), mechanism, A/A, confirmation | yes |
| unchanged | no_relevant_change | no_relevant_change (+3%, interval -1% .. +15%) | yes |
| irrelevant_index | not improved, index unused | no_relevant_change (-3%), 0 scans of item.title | yes |
| workload_without_the_column | not improved | not measured: the workload raised "normal test user not found" | no |
| slower | regression | regression (11.4 -> 22.4 ms) | yes |
| near_threshold | not improved | no_relevant_change (+15%, interval +12% .. +19%) | yes |
| faster_wrong_answer | regression, result differs | regression: +68% faster, "call 1.data: 100 items against 99" | yes |

Harness defect: the superuser variant of the saved workload dropped `normal_user_token_headers` from `build`, but
the workload looks that user up; without its fixture the user did not exist. Fixed: the variant keeps the fixture and
only the call uses the superuser's headers. All seven are run again on one commit.
