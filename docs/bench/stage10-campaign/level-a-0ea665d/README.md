# Level A, run 7: the 20-repository corpus at product 0ea665d, checks only, no model

Worktree `~/unbidden-ai-s10-0ea665d`, US$0, 2026-11-01. The tool's count: 19 of 20. The honest count under the
stated rule: **18 of 20**; **10 pass outright**.

| Repository | Result | Reading |
|---|---|---|
| fst, conduit, spoolman, rich, marshmallow, pyjwt, starlette, sqlmodel | passed | as run 6 |
| **ctfd** | **passed 679**, `mariadb.yml > build` (mariadb and redis sidecars), 340 s | the name-resolution failures of runs 5-6 were a cascade of the read-only `/var/log` (writable since 6e53da9); the 11 left were the compose file's application environment (`UPLOAD_FOLDER=/var/uploads`, `DATABASE_URL=...@db`) reaching the CI job's tests, kept out since 0ea665d |
| **aegra** | **passed 2429** (21 failed in every earlier run) | the same change: its compose environment no longer overrides the job's; the 21 "needs network" were that |
| mealie | 3640 / 18 | NLTK data (pre-existing) |
| lnbits | 272 / 2 | fiat-rate lookups (network) |
| prefect | 1033 / 11 | release-workflow tests (no `.git`) |
| codex-lb | 6422 / 34 | `git` absent |
| rag-api | 195 / 1 | `nltk_data` download |
| click | 2287 / 27 | no pager |
| humanize | 878 / 15 | benchmark plugin against today's pytest (the project's CI is green) |
| httpx | 1418 / 4 | tests reaching real hosts |
| timetracker | 560 / 28, 711 s; the first attempt crashed an xdist worker (`Broken pipe`, now recorded), the retry with one worker still lost a worker, with SQLite foreign-key teardown errors and assertion failures | unstable and unexplained; the project's own CI skipped its full suite at this commit: **not counted** |
| healthchecks | no_plan | Django's runner: a declared limit |

Honest 18 = 10 outright + 8 with every failure explained as the sandbox's (no git, no pager, no network, today's
resolution, NLTK data). Gate criterion 1 (16) is met under the stated rule and, at 10, not under the strict one;
both numbers stand in the campaign's status.

What seven runs taught, as rules: a planner fix for one repository is measured on the whole corpus; a suite that ran
is not a project's checks reproduced until every failure is read; a failure's message is kept with its name; the
compose file's environment belongs to the application container, the job's to its tests.
