# Stage 10 regressions, part 2: full cycles at product 06f189d, the evaluation's modes and data (development)

Worktree `~/unbidden-ai-s10-06f189d` (the checks corrections through cbf1ecf), `s10-dev` 7.31 -> 8.09 (US$0.79),
B-1 then A-1 per application, the lab clones and data of the frozen evaluation unchanged. Records in `<app>-reg/`.
Not evidence: the applications are development since the evaluation closed.

| | codex-lb | Aegra | rag-api |
|---|---|---|---|
| Checks reproduced (Unbidden, autonomous) | yes: 6422 collected, 34 failed (git/release-script tests, no `.git` in the snapshot) | yes: 2429 collected, 21 "needs network" | yes: 195 collected (CI's `--maxfail=1` stops at an NLTK download), integration left out (container runtime) |
| Experiments | 1 opportunity (`proxy_pool_members.endpoint_id`): **not measured, "no single Alembic head"** (merge migrations; fixed after in bbb0f83) | none: no index opportunity (every foreign key indexed) | none |
| Consistency | 10 investigations: blocked (API reads stopped at their 100,000-record bound; bearer-only endpoints; the integration not validated) | `GET /assistants` total: **agrees, 0 of 200 differ** (verified independently earlier); `/threads` inconclusive (SQL read cut at 1,000 rows) | goal inconclusive (0 keys joined, SQL read cut at 1,000 rows) |
| Wall / cost | 6 + 9 min, US$0.37 | 5 + 4 min, US$0.36 | 33 s + 69 s, US$0.06 |

Compared with the frozen evaluation (`../../stage10-eval/`): the three blocks on the checks are gone; what remains
is the next layer, now visible: codex-lb's migration graph (fixed in bbb0f83, to be repeated), the consistency
reads' bounds (1,000 SQL rows, 100,000 API records) and credential kinds (bearer), the goal's join at 0 keys on
rag-api. None of these produced a false conclusion; each is recorded with its reason.
