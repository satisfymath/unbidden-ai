# Evaluator controls, first run at product c9e359e: 3 of 7, two harness defects

`bench/promotion_cases.py` on full-stack-fastapi-template f4bcfab (`~/unbidden-lab/reval/fst-dec7ba2`), the saved
workload and index patch of the dec7ba2 revalidation; no model, no spend. Kept as found; not a verdict on the product.

| Case | Expected | Outcome | Passed |
|---|---|---|---|
| real_improvement | improved | not measured (alembic failed to load the migration) | no |
| unchanged | no_relevant_change | no_relevant_change (+4%, interval -1% .. +12%) | yes |
| irrelevant_index | not improved, index unused | no_relevant_change (-4%) | no (predicate) |
| workload_without_the_column | not improved | not measured (alembic) | no |
| slower | regression | regression (11.1 -> 22.3 ms) | yes |
| near_threshold | not improved | inconclusive (+19%, below 20%) | yes |
| faster_wrong_answer | regression, result differs | not measured (alembic) | no |

Harness defects, both fixed before the second run: the candidate files were rebuilt with v3's `added_files`, which
keeps only a patch's added lines, so the patch's modified `models.py` was broken (every case with the patch could not
start); the irrelevant-index predicate looked for the scan count in the reasons, which name it only for an
improvement — the outcome itself (not improved) was right; the predicate now reads the candidate sessions' index
scans.
