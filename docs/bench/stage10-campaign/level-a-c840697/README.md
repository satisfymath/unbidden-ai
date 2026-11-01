# Level A, run 1: the 20-repository corpus at product c840697 (checks only, no model)

Worktree `~/unbidden-ai-s10-c840697`, `bench/level_a.py` on `bench/repos/campaign-v1.yaml`, US$0 (no model call),
2026-10-31 evening, host load 1.4 - 3.0 at the starts. Records: `<repo>.json`, `summary.json`, `level_a.log`.
The tool's own count: `{"checks_reproduced": 15, "of": 20}`; the honest count, after reading each record, is
**13 of 20** (the gate asks 16): two of the fifteen ran a suite that was not the project's checks (CTFd collected
one test; sqlmodel's entry had no database).

## Per repository

| Repository | Shape | Status | Collected / failed | Plan source | Reading |
|---|---|---|---|---|---|
| fst | app | passed | 58 / 0 | CI test-backend | reproduced |
| mealie | app | failed | 3640 / 18 | CI nightly > tests (postgres) | reproduced; the 18 are the NLP parser, pre-existing (same as every earlier run) |
| conduit | app | passed | 90 / 0 | CI tests > lint (postgres) | reproduced |
| lnbits | app | failed | 272 / 2 | CI test-api (postgres) | reproduced; 2 marked "needs network" (fiat rates) |
| spoolman | app | passed | 278 / 0 | fallback pytest | reproduced |
| prefect | app | failed | 1033 / 11 | CI run-canonical-tests, split 1 of 18 | reproduced for its group; the 11 are release-workflow tests reading `.git`/CI metadata the snapshot lacks |
| codex-lb | app | failed | 6422 / 34 | CI ci.yml > test | reproduced; the 34 are git/release-script tests (no `.git`), as at 6f48b39 and in the full cycles |
| aegra | app | failed | 2429 / 21 | CI test-api | reproduced; all 21 marked "needs network" |
| rag-api | app | failed | 195 / 1 | CI build-and-test, without its container-runtime tests | reproduced; the 1 (`test_lazy_load[md]`) also failed in the author's own run |
| healthchecks | app | no_plan | — | — | **block A: not a pytest project** (`python manage.py test`, Django's runner); outside the campaign's declared scope (pytest) |
| rich | library | passed | 981 / 0 | CI build | reproduced |
| marshmallow | library | passed | 1192 / 0 | fallback pytest | reproduced |
| pyjwt | library | passed | 476 / 0 | fallback pytest | reproduced |
| humanize | library | infra_failed | — | CI benchmark.yml > benchmarks | **block B: tox not expanded** (its test job runs `uvx tox -e py`), so the benchmark job was taken; its translation script needs `msgfmt` (gettext, an apt step) |
| starlette | library | passed | 1416 / 0 | fallback pytest | reproduced |
| click | library | infra_failed | — | CI nightly.yaml > flask-tests | **block B: tox not expanded** (`uv run tox run` with `TOX_ENV`); the job taken checks out Flask, not click, and its line became `-- pytest` |
| httpx | library | infra_failed | — | CI test-suite > tests | **block C: an install script run offline** (`scripts/install`: `pip install -r requirements.txt`, no network in the sandbox) |
| sqlmodel | library | failed | 378 / 50 | CI test > test, entry 1 of 9 (postgres) | **block D: the matrix entry whose database a `docker compose up` step starts** was taken; its 50 failures are connection failures, not the project's |
| ctfd | app | failed | 1 / 1 | fallback pytest | **block E: the CI job rejected for `sudo`** (`sudo rm -f /etc/boto.cfg`, `sudo yarn install`), so the fallback ran without `development.txt` (pytest plugins, moto): one collection error |
| timetracker | app | infra_failed | — | CI ci.yml > test (postgres) | **block F: a pyproject.toml of tool settings only taken for the manifest**; its requirements.txt (Flask) never installed: `flask: command not found` |

## Classification of the blocks

| Class | Repositories | Cause in Unbidden | Fix |
|---|---|---|---|
| A. Test runner other than pytest | healthchecks | the plan and the lab know pytest only | outside the declared scope; recorded as a limit (`unbidden doctor` says it) |
| B. tox environments not expanded | humanize, click | `tox -e py` / `tox run` are not read from tox.ini or `[tool.tox]` | next development task (C2): read the environment's commands, deps and extras; prefer the test job over a benchmark or another project's suite |
| C. Install scripts run offline | httpx | a repository script was run as a step, its pip calls included | fixed next: a script that only installs is left out and its `-r` files are the job's requirement files |
| D. Matrix entry needing a compose-started engine | sqlmodel | entries were ranked by service containers only | fixed next: entries naming an engine a `docker compose up` step starts come after those that need none; Linux entries before Windows/macOS |
| E. `sudo` lines editing the runner | ctfd | any `sudo` made the job irreproducible | fixed next: a `sudo` edit of a system path is left out and said; `sudo yarn install` is the install without sudo |
| F. pyproject.toml without a project | timetracker | pyproject.toml always won over requirements.txt | fixed next: a pyproject.toml that declares nothing to install, next to requirements.txt, is not the manifest |

Fixes C-F are general (no repository named in code), each with a unit test that failed before
(`tests/unit/test_level_a_blocks.py`); run 2 of level A measures them. B is development still to do; A stays a limit.
