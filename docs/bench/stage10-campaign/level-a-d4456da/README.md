# Level A, run 3: the 20-repository corpus at product d4456da (tox, apt packages, script kinds), checks only

Worktree `~/unbidden-ai-s10-d4456da`, US$0, 2026-10-31 night. The tool's count: `{"checks_reproduced": 17, "of":
20}`; the honest count is **14 of 20**, with mealie pending one explanation. Records keep the failed round's last
output now (b01b6fa); the failure messages themselves arrive with fb34eac (run 4).

| Repository | Result | Reading |
|---|---|---|
| fst, conduit, spoolman, rich, sqlmodel | passed | reproduced |
| marshmallow, pyjwt | passed, **now from their CI jobs** (`build-release.yml > tests`, `main.yml > tests`: tox expanded) | reproduced |
| lnbits | 272 / 2, `test-api` again | reproduced; the 2 need the fiat-rate network (`Lightning Address fee wallet is not configured` is the same pair) |
| prefect | 1033 / 11 | reproduced; release-workflow tests, as always |
| codex-lb | 6422 / 34 | reproduced; `No such file or directory: 'git'`, as always |
| aegra | 2429 / 21 | reproduced; the same 21 |
| rag-api | 195 / 1 | reproduced; the one needs `nltk_data` (a download) |
| click | 2287 / 27, `tests.yaml > tests` (tox expanded, group `tests` installed) | reproduced; 24 are `test_echo_via_pager` and 3 `test_termui`: the sandbox has no pager binary; environment-bound, cause recorded |
| humanize | 878 / 15 errors, `test.yml > test` (tox expanded, extra `tests`, gettext installed: `msgfmt` ran) | 863 pass; the 15 errors are `tests/test_benchmarks.py`: `'Function' object has no attribute '_nodeid'`, a pytest plugin (benchmark/codspeed) against the pytest resolved today; environment-bound, **pending independent confirmation** of what the project's own CI gets |
| mealie | 3640 / **27** (18 before) | the 9 new are `test_ldap_*`, skipped unless `GITHUB_ACTIONS` is set (set since b01b6fa, as the job runs); the job's `ldap` service container is in the plan (`rroemhild/test-openldap`, ports 10389, 10636); why the tests still fail is read from the messages in run 4 |
| ctfd | 679 / 50 | the tail shows SQLAlchemy's `create_engine` arguments: a driver/engine argument rejected under the mariadb job's URL; messages in run 4 |
| timetracker | 603 / 50 (113 in run 2: `requirements-test.txt` now installed) | services (email, payment, comments) fail; messages in run 4 |
| starlette | infra_failed: `scripts/build` ran `uv build` (fetches hatchling, no network) | `script_kind` did not classify `zensical build` (fixed fb34eac: any tool's `build` command) |
| httpx | infra_failed: `scripts/check` ran (`mypy: not found`) | its nested `./scripts/sync-version` was not read (fixed fb34eac: a script's own scripts are read) |
| healthchecks | no_plan | class A, a limit |

Honest count: 14 (the first ten rows: 5 + 2 + lnbits, prefect, codex-lb, aegra, rag-api, click, humanize with its
caveat). Run 4 at fb34eac carries the two fixes and the messages.
