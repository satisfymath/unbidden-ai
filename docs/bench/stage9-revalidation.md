# Stage 9: the false L4, reproduced, and every affected promotion re-judged under perf-v3

**Reproduced.** Stage 8's B-7 promoted `commentaries.author_id` (Conduit, `DELETE .../comments/{id}`) to L4 on
2.5 -> 2.0 ms. From its recorded samples, criteria v1 (one session per side, 20 samples each, a one-sided
Mann-Whitney test per sample, >= 20%) promote it again (`tests/unit/test_perf_sessions.py`). The independent query
plan said why it cannot be real: the delete finds its row by primary key.

**Criteria v3** (`unbidden/lab/perfstats.py`, committed in 92d9361 before any measurement under them): four
sessions per side, alternating, which side goes first drawn from a seed; each session a fresh database with the same
image, data, limits, warm-up (3 calls) and samples (20); the unit is the session median; an exact one-sided
permutation test (alpha 0.05); improvement needs >= 20%; for an index, the engine must show the index used on at
least every measured call of every candidate session (`pg_stat_user_indexes`), else a speed-up is not attributed
to it; a regression is >= 10% slower by the same test; "no relevant change" when the 95% bootstrap interval of the
effect lies inside +-20%; otherwise inconclusive; fewer than two sessions per side is blocked. The project's own
checks still run three rounds on each side. Development fixtures cover session noise, small irrelevant gains,
regressions, real gains and a speed-up without its mechanism.

**Re-measured** offline, no model, from B-7's saved workloads and patches (`bench/perf_v3_replay.py`), raw sessions
in `stage9-revalidation/*.json`:

| Case | v3 outcome | Session medians, base -> candidate | Index scans per candidate session | Checks |
|---|---|---|---|---|
| A/A control (no change), comments listing | no relevant change | 24.0 -> 24.9 ms (interval -11% .. +2%) | - | passed |
| irrelevant index (`commentaries.created_at`), comments listing | no relevant change | 24.3 -> 24.4 ms (interval -6% .. +4%) | 0 | passed |
| `favorites.article_id`, `DELETE /api/articles/{slug}` | **improved, L4** | 9.7 -> 1.6 ms (83%), p = 0.029 | 46 | passed |
| `commentaries.author_id`, `DELETE .../comments/{id}` (the B-7 false L4) | inconclusive | 2.1 -> 2.3 ms (no effect) | 0 | passed |
| `commentaries.article_id`, `GET /api/articles/{slug}/comments` | inconclusive | 25.6 -> 21.1 ms (18%), p = 0.029 | 35 | passed |

**Decided.** `favorites.article_id` keeps L4 (revalidated). `commentaries.author_id`'s L4 is revoked (an artifact).
`commentaries.article_id`'s L4 (B-7 and A-8) is revoked too: the index is used and its query drops 8.43 -> 0.06 ms,
but the endpoint improves 18%, below the practical threshold fixed before measuring; the threshold is not moved to
let it through. Revocations keep the verdict, the experiment and the history (`unbidden/lab/revoke.py`); they are
applied to copies of the archived workspaces (`~/unbidden-lab/conduit-runs/reg8f-*-after-v3`), the originals kept
as recorded.

**Other promotions judged by criteria v1**, not re-measured in this stage: full-stack-fastapi-template's
`item.owner_id` (D-010) and mealie's lab L4 under its L5 (D-035, D-041). Both are listed as **pending revalidation
under perf-v3**; their large effects (13.0 -> 4.1 ms; 10,934 -> 8.1 ms) make them likely to hold, which is not the
same as shown. Rich's L4 (D-018) is a crash fix judged by FixLab, not by these criteria.
