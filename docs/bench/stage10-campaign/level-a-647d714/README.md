# Level A, run 6: the 20-repository corpus at product 647d714, checks only, no model

Worktree `~/unbidden-ai-s10-647d714`, US$0, 2026-11-01. The tool's count: 19 of 20. The honest count, under the
rule stated in run 5's README (passed, or every failure explained as the sandbox's with the cause recorded):
**17 of 20**. Eight pass outright; nine run with explained, environment-bound failures; three do not count.

| Repository | Result | Reading |
|---|---|---|
| fst, conduit, spoolman, rich, marshmallow, pyjwt, starlette, sqlmodel | passed | reproduced outright (8) |
| mealie | 3640 / 18 | back to its 18 (NLTK data, pre-existing); the 9 LDAP tests pass against the job's `ldap` container, reached by name (647d714's mapping) |
| lnbits | 272 / 2 | fiat-rate lookups (network) |
| prefect | 1033 / 11 | release-workflow tests (no `.git`, no CI metadata) |
| codex-lb | 6422 / 34 | `git` absent from the snapshot |
| aegra | 2429 / 21 | the same 21, marked "needs network" |
| rag-api | 195 / 1 | `nltk_data` download |
| click | 2287 / 27 | no pager binary |
| humanize | 878 / 15 | benchmark plugin against today's pytest; the project's CI is green at this commit |
| httpx | **1418 / 4** (run 5: 1 collected) | 3 `ConnectError: Temporary failure in name resolution` (tests that reach real hosts) and one unraisable-exception warning; the `cli` extra and `coverage` are installed now |
| ctfd | 679 / 636, 692 s | 20 `PermissionError: /var/log/CTFd` (the tmpfs was root's; mode 1777 at 6e53da9) and the rest `Can't connect to MySQL server on 'mariadb' ... name resolution`. By hand, in a container with the sandbox's flags, the same image and a mariadb sidecar: `create_ctfd()` builds the app and migrates; one module passes serially and under xdist with the lab's exact script. The failure appears only over the whole suite: being isolated (a run with `--maxfail`), **not counted** |
| timetracker | 112 / 1 `internal error` | pytest's own crash, text not captured (fixed 6e53da9: the INTERNALERROR block is kept); **not counted** |
| healthchecks | no_plan | Django's runner: a declared limit |

Gate criterion 1 (at least 16 of 20 reproduce their required checks autonomously): **17 under the stated rule**,
8 by the strict reading. The rule and both numbers go into the campaign's status; the other criteria of the gate
(no false promotion or out-of-mandate action known; controls 7 of 7; repeatable cycles on three applications and
two families; every block classified) are judged apart.
