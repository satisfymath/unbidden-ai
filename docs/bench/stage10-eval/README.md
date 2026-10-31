# Stage 10's frozen evaluation: results

Product 0102ccb (`unbidden/` 577c03c), runner 0fe4ecd, protocol 2f3da12, worktree `~/unbidden-ai-s10-eval-fc76b24`
(every frozen hash verified before the runs). Envelope `s10-eval`: US$1.0010 of 8.50 (cumulative 24.2976 -> 25.2986
of 37.2945). All six runs completed (B-1 then A-1 per application, four cycles each, no interventions, no harness
failure); started 13:36, ended 14:04 on 2026-10-31. Host: load 1.7 - 3.1 (host.log); the Prefect lab service was
running (the controls' precaution was approved for the controls only). Records in `<app>/<run>/`, workspaces in
`~/unbidden-lab/<app>-runs/`.

## Outcome per application

| | codex-lb | Aegra | rag-api |
|---|---|---|---|
| Environment reproduced (dependency image) | yes | yes | yes |
| Project checks run | **no**: the CI step taken was `echo "Backend files unchanged; required pytest context satisfied."`, the branch of a step condition (`if:`) for unchanged files; nothing collected | **no**: `uv python install 3.12`, a step of its CI, refused in the sandbox ("Python downloads are not allowed") | **no**: collecting `tests/integration/conftest.py` raised `ModuleNotFoundError: testcontainers` (its test requirements not installed) |
| Opportunities | 1 performance (`proxy_pool_members.endpoint_id`), 7-8 consistency | 2 consistency | none (B); the goal only (A) |
| Workloads valid / experiments completed | 0 / 0 (experiments wait for the checks) | 0 / 0 | 0 / 0 |
| Improvements verified / false promotions | 0 / 0 | 0 / 0 | 0 / 0 |
| Consistency | blocked: the API integration was not validated (`/api/request-logs` read stopped at its 100,000-record bound; endpoints that accept only bearer tokens); plans that named fields the query lacked | **verified agreement**: `GET /assistants` total against the stored data, 0 of 200 keys differ; `/threads` inconclusive (SQL read cut at 1,000 rows) | goal inconclusive: 0 keys joined, SQL read cut at 1,000 rows |
| Outcome | technical block | technical block (checks); absence verified (assistants' total) | technical block |

**Reading:** no application of the evaluation reached an experiment: the project's own checks were not reproduced in
any of them, for three different reasons in Unbidden (step conditions not evaluated; an interpreter install step
the sandbox refuses; test requirements not installed). No false promotion, no change proposed. The one conclusion
reached is correct (independently recomputed below). By the protocol, a failure that needs a correction closes this
version: the corrections and any repeat are regressions, not part of this evaluation.

## Independent measurement (by the harness's author, after the runs)

- **Consistency recomputed:** Aegra's assistants: `POST /assistants/count` = 200, `SELECT count(*) FROM assistant` =
  200: Unbidden's "0 of 200 keys differ" holds.
- **Abstentions against the data** (single-column foreign keys without an index, on the seeded databases):
  codex-lb: seven, all on tables the seed left empty (the one Unbidden found, `proxy_pool_members.endpoint_id`,
  among them): nothing measurable at this data. Aegra: every foreign key indexed: no index opportunity, and Unbidden
  raised none. rag-api: `langchain_pg_embedding.collection_id` (one collection: an index would not help); its
  document read by `custom_id` is a sequential scan of 30,000 rows (6 ms here), not a foreign key: outside what
  Unbidden looks for, recorded as a possible miss at larger data.
- **L4s re-measured:** none (no promotion).
- **The projects' own tests as their CI runs them:** not run by the author in this pass (each needs its CI's own
  environment: codex-lb's frontend build, Aegra's interpreter install, rag-api's test requirements and Docker for
  testcontainers). Pending; the evaluation's outcome does not depend on it, since Unbidden ran no experiment.

## Closure (2026-10-31)

This evaluation is closed with its six original results, as recorded above; nothing later changes them.

- The three environments were prepared (human preparation, counted) and Unbidden built each dependency image, but
  **no project's test suite was reproduced**: zero experiments; three applications technically blocked.
- **Zero false promotions under these conditions does not show the evaluator's precision**: nothing reached the
  stage where a promotion could be made. Its precision rests on the controls (`stage10-controls/0102ccb-run4`),
  not on this evaluation.
- Aegra's agreement on 200 assistants is a **correct consistency result**, separate from the improvement criterion;
  it is not an improvement and not an experiment.
- The independent checks still pending stay pending until done (the projects' tests as their CI runs them); when
  done they say what each project requires and how that compares with what Unbidden tried, and do not change these
  results.
- The corrections that follow are development; their runs are regressions, recorded apart (`stage10-regression/`),
  never as part of this evaluation.

Budget after closing: cumulative US$25.2986 of US$37.2945. By David's instruction of 2026-10-31, US$5 of the unspent
`s10-eval` moved to `s10-dev` before any further spend (envelopes s10-dev 13.00, s10-eval 3.50, s10-close 3.80; total
US$20.30 and the cap unchanged; `~/.unbidden/budget-history.jsonl`).

## For v1.0

The criteria are not met: no valid experiment on any of the three new applications. Not declared.
