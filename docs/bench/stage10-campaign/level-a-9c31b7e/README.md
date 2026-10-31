# Level A, run 5: the 20-repository corpus at product 9c31b7e (all declared containers, service ports, UV_NO_SYNC, CI requirement files)

Worktree `~/unbidden-ai-s10-9c31b7e`, US$0, 2026-11-01. The tool's count: 18 of 20; the honest count is
**14 of 20**: starlette joins, mealie leaves (a regression of this commit), httpx and CTFd moved without arriving.

| Repository | Result | Reading |
|---|---|---|
| starlette | **passed 1416** from `main.yml > tests` (`scripts/test` under `UV_NO_SYNC=1`) | reproduced, from its own CI job now (run 1 had the fallback) |
| mealie | **infra_failed**: `ConnectionError: Database connection failed` at `tests/conftest.py` | **regression**: with the `ldap` container started too, `POSTGRES_SERVER: localhost` (no port) no longer mapped to the postgres sidecar (the rule mapped "the only service"); fixed 647d714 (the engine the variable names, then the only database) |
| httpx | 1 collected / 1 `collection failure`, `coverage run -m pytest` ran | coverage installed now; the collection fails for what `-e .[cli]` carried (its `cli` extra); fixed 647d714 (a project's extras named in a CI requirements line are synced) |
| ctfd | 679 / 636 failed, 306 s | 20 `OSError: Read-only file system: '/var/log/CTFd'` (its log directory; the sandbox root is read-only: fixed 647d714, `/var/log` is a tmpfs) and `Can't connect to MySQL server on 'mariadb' ... Temporary failure in name resolution` for the rest, with the mariadb and redis sidecars up on the sandbox's network (seen with `docker ps` during a probe run). The same image, flags and a mariadb sidecar resolve and connect from a shell (checked by hand): what differs under pytest is open; run 6 says whether it persists once the log directory is writable |
| timetracker | 113 / 1 `internal error`, 70 s (run 4: 733 / 49, 1301 s) | pytest's internal error under `-n auto`; the record keeps 600 characters of stdout, all Alembic logs: not enough (1500 from 647d714). Unstable between runs: **not counted** |
| humanize | 878 / 15 | as before; the project's CI is green at this commit (checked on GitHub): our resolution, counted with the caveat |
| click | 2287 / 27 | pager, as before |
| lnbits | 272 / 2 | the same two (fiat rate lookups) |
| the other 11 | as run 4 | reproduced |

Checker's observations (GitHub, by hand): humanize's CI green at 6b817b9; TimeTracker's "Full Test Suite" job
skipped at 7ae6440 and CTFd's test workflows not run at 5f345fb (only lint and docker): neither has a baseline
of its own to compare with.

Counting rule, stated: a repository counts when its suite passed, or when every failure is explained by the sandbox
(no git, no pager, no network, today's resolution) with the cause recorded; a failure caused by Unbidden's own
preparation, or unexplained, does not count. Run 6 at 647d714 follows.
