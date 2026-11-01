# Level A, run 4: the 20-repository corpus at product fb34eac (failure messages recorded), checks only

Worktree `~/unbidden-ai-s10-fb34eac`, US$0, 2026-11-01 early. The tool's count: 17 of 20; the honest count is
**14 of 20**, the same fourteen as run 3. What this run adds is the cause of every remaining failure, from the
JUnit messages now kept in each record (`failures` in `<repo>.json`).

| Repository | Result | Cause read from the messages | Class |
|---|---|---|---|
| mealie | 3640 / 27 | 9 `ldap.SERVER_DOWN: Can't contact LDAP server`: the job's `ldap` container was in the plan but **only database containers were started** (`data_kind` filter); 18 NLTK (pre-existing) | product gap, fixed 9c31b7e (every declared container starts; a port probe for those of no known kind) |
| ctfd | 679 / 50 | 20 `TypeError: Invalid argument(s) 'max_overflow' ... SQLiteDialect`: the tests ran on SQLite because `TESTING_DATABASE_URL` carried `${{ job.services.mariadb.ports[3306] }}` and **was dropped as an expression** | product gap, fixed 9c31b7e (the expression is the container's port) |
| timetracker | 733 / 49, 1301 s | 9 `TypeError: __init__() got an unexpected keyword argument 'total_amount'` on setup; two xdist workers crashed; one `peppol` assertion | the test code and the model disagree at this commit, and workers die: looks like the project's own state; **pending an independent run of its CI job** before it counts either way |
| starlette | infra_failed | `scripts/test` runs `uv run coverage run -m pytest`: **`uv run` inside a script synced the project** and fetched its build backend (no network) | product gap, fixed 9c31b7e (`UV_NO_SYNC=1` in the sandbox) |
| httpx | infra_failed | `coverage: not found`: `requirements.txt` (`-e .[cli]`, coverage, mypy) is what its CI installs, **ignored for a pyproject manifest** | product gap, fixed 9c31b7e (the CI's requirement files are installed after the sync, the project's own line left out) |
| humanize | 878 / 15 | `AttributeError: 'Function' object has no attribute '_nodeid'` on setup of the 15 benchmark tests: the benchmark plugin against the pytest resolved today | environment-bound; counted with the caveat (pending the project's own CI result) |
| click | 2287 / 27 | `Unexpected pager output`: no pager in the sandbox | environment-bound; counted |
| healthchecks | no_plan | Django's runner | limit |
| the other 12 | as run 3 | | reproduced |

Run 5 at 9c31b7e carries the four fixes; the whole corpus runs again (a fix for one repository has regressed another
twice in this series).
