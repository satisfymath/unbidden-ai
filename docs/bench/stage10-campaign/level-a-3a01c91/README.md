# Level A, run 2: the 20-repository corpus at product 3a01c91 (classes C-F fixed), checks only, no model

Worktree `~/unbidden-ai-s10-3a01c91`, US$0, 2026-10-31 night. The tool's count: `{"checks_reproduced": 16, "of":
20}`; the honest count is **12 of 20**: four of the sixteen ran something other than the project's checks, one of
them a regression of this very commit. Kept as found; what it taught is fixed at b01b6fa and d4456da (run 3).

## What changed against run 1

| Repository | Run 1 | Run 2 | Reading |
|---|---|---|---|
| sqlmodel | 378 / 50 (postgres entry, no database) | **passed 268** (ubuntu 3.11 entry, sqlite) | class D fixed: reproduced |
| timetracker | infra_failed (`flask` not found) | 113 collected / 1 failed: `pytest::internal` | class F fixed (requirements.txt installed); the one failure is pytest's own internal error, cause not recorded (the record kept names only; from b01b6fa a failed round keeps its last output): **not counted** until explained |
| ctfd | 1 collected (fallback) | 679 collected / 50 failed, `mariadb.yml > build` (services mariadb, redis) | class E fixed (the CI job runs); the 50 failures spread over admin, API and CSV tests, cause not recorded: **not counted** until explained (the author's own run of that job is pending) |
| httpx | `scripts/install` offline | `scripts/check` failed (ruff format, mypy) | class C fixed (install left out); the lint script ran next: a check script is not the tests (fixed b01b6fa: scripts that only check, build or report are left out) |
| **lnbits** | 272 / 2 (test-api) | **36 / 20, `regtest` job** | **regression of 3a01c91**: the relaxed `sudo` rule let `sudo chmod -R a+rwx .` through, and the regtest job (bitcoin regtest over compose) was taken; fixed b01b6fa (`sudo` only on system paths is runner preparation): not counted |
| **starlette** | 1416 / 0 (fallback pytest) | 121 / 0, `benchmark.yml > benchmarks` | the install-script rule made its test job and its benchmark job both plannable, and the benchmark job ranked first; fixed b01b6fa (benchmark jobs last): not counted |
| humanize, click | tox not expanded | same | class B, fixed after this commit (a36fdd9: tox; 5c281a0: gettext from the job's apt step) |
| healthchecks | no_plan | no_plan | class A, a limit |
| the other 11 | reproduced | reproduced, same numbers | fst, mealie, conduit, spoolman, prefect, codex-lb, aegra, rag-api, rich, marshmallow, pyjwt |

## Reading

The tool's count overstates: "a suite ran and reported" is not "the project's checks were reproduced". Run 3 at
d4456da carries every fix above and the records keep the failed round's last output; its count is read the same way.
A class-E or class-C fix that widens what the planner accepts needs the whole corpus, not the repository that asked
for it: lnbits and starlette regressed under fixes for CTFd and httpx, and only the corpus showed it.
