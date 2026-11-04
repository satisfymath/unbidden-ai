# Campaign 13, final pass

Generated 2026-11-04T23:26+00:00 from the records in this directory (`bench/campaign13/evidence.py`).

Unbidden ran on its own, frontier models only, over the 39 repositories of the corpus. It worked on copies
under `github.com/satisfymath`, and nothing went upstream. It found improvements and measured them, opened pull
requests and merged them. It merged only when the team's own CI was green on the pull request's exact head.
The apps it brought up itself it then deployed and verified.

## In numbers

| | |
|---|---|
| Repositories with a record | 28 of 39 |
| Pull requests opened by the agent | 37 (26 green on the team's CI) |
| Improvements merged by the product, autonomously | **12** in 12 repositories (5 quality, 7 security; 13 merges, one fix merged in two runs) |
| Merges verified independently (`verify.py`: ruff, or OSV advisories) | 12 of 12 |
| L5, verified after the agent's own deploy | 2: fst, aegra |
| Model spend | US$3.83 |

## Every merge

| Repository | Pull request | Kind | CI | Independent check | Version |
|---|---|---|---|---|---|
| aiogramshopbot | [#1](https://github.com/satisfymath/c13-aiogramshopbot/pull/1) fix: 2 ruff-baseline F811 findings in ./ | quality | green | verified | 0.18.6 |
| dooit | [#4](https://github.com/satisfymath/c13-dooit/pull/4) security: bump idna 3.10 → 3.15 | security | none | verified | 0.18.6 |
| fst | [#17](https://github.com/satisfymath/c13-fst/pull/17) security: bump dnspython 2.8.0 → 2.9.0 | security | green | verified | 0.18.6 |
| marshmallow | [#3](https://github.com/satisfymath/c13-marshmallow/pull/3) security: bump certifi 2026.7.22 → 2026.10.18 | security | green | verified | 0.18.6 |
| oauthlib | [#2](https://github.com/satisfymath/c13-oauthlib/pull/2) fix: 1 ruff-baseline B006 finding in oauthlib/oauth2/rfc6749/endpoints/ | quality | green | verified | 0.18.6 |
| python-progressbar | [#3](https://github.com/satisfymath/c13-python-progressbar/pull/3) security: bump certifi 2026.5.20 → 2026.10.18 | security | green | verified | 0.18.6 |
| reader | [#1](https://github.com/satisfymath/c13-reader/pull/1) fix: 19 ruff-baseline F821 findings in tests/data/ | quality | green | verified | 0.18.6 |
| resumeio-to-pdf | [#1](https://github.com/satisfymath/c13-resumeio-to-pdf/pull/1) security: bump anyio 4.10.0 → 4.14.2 | security | green | verified | 0.18.6 |
| rich | [#18](https://github.com/satisfymath/c13-rich/pull/18) fix: 1 ruff-baseline F821 finding in examples/ | quality | green | verified | 0.18.6 |
| tracklater | [#1](https://github.com/satisfymath/c13-tracklater/pull/1) fix: 2 ruff-baseline F811 findings in tracklater/tests/ | quality | green | verified | 0.18.6 |
| aegra | [#7](https://github.com/satisfymath/c13-aegra/pull/7) fix(deps): bump certifi 2026.1.4 → 2026.10.18 (security) | security | green | verified | 0.18.9 |
| rich | [#23](https://github.com/satisfymath/c13-rich/pull/23) fix: 1 ruff-baseline F821 finding in examples/ | quality | green | verified | 0.18.9 |
| sqlmodel | [#1](https://github.com/satisfymath/c13-sqlmodel/pull/1) fix(deps): bump anyio 4.12.0 → 4.14.2 (security) | security | green | verified | 0.18.9 |

## L5

- **fst** (0.18.6): L5 (verified-deploy-v1; verified after deploy 1:c2d276ddc4497c36663019687d3960f9e03a83e2)
- **aegra** (0.18.9): L5 (verified-deploy-v1; verified after deploy 1:600c12eaa65e24d074a6b29f31cc76ea594e6c72)

A verified-deploy L5 claims no measured effect. It says four things about the change: it was deployed by the
product, the deploy is attributable, it was judged healthy with no endpoint failing more than before, and
for security the fixed version is the one running. The latency measurement was deferred on every app,
because the host was too busy with many repositories at once (a 1-minute load above a quarter of the CPUs).
That deferral is by design: noise never becomes a result.

## Every pull request, merged or not

| Repository | Pull request | Kind | CI | Merged | Version |
|---|---|---|---|---|---|
| aegra | [#6](https://github.com/satisfymath/c13-aegra/pull/6) security: bump langgraph-checkpoint-postgres 3.1.2 → 3.1.3 | security | red | no | 0.18.6 |
| aegra | [#5](https://github.com/satisfymath/c13-aegra/pull/5) security: bump filelock 4.0.9 → 4.2.1 | security | red | no | 0.18.6 |
| aegra | [#4](https://github.com/satisfymath/c13-aegra/pull/4) security: bump certifi 2026.1.4 → 2026.10.18 | security | red | no | 0.18.6 |
| aiogramshopbot | [#3](https://github.com/satisfymath/c13-aiogramshopbot/pull/3) security: bump python-dotenv 1.0.1 → 1.2.2 | security | green | no | 0.18.6 |
| aiogramshopbot | [#2](https://github.com/satisfymath/c13-aiogramshopbot/pull/2) security: bump pillow 12.1.0 → 13.0.0 | security | green | no | 0.18.6 |
| aiogramshopbot | [#1](https://github.com/satisfymath/c13-aiogramshopbot/pull/1) fix: 2 ruff-baseline F811 findings in ./ | quality | green | yes | 0.18.6 |
| ctfd | [#1](https://github.com/satisfymath/c13-ctfd/pull/1) security: bump idna 3.10 → 3.15 | security | red | no | 0.18.6 |
| dooit | [#4](https://github.com/satisfymath/c13-dooit/pull/4) security: bump idna 3.10 → 3.15 | security | none | yes | 0.18.6 |
| dooit | [#3](https://github.com/satisfymath/c13-dooit/pull/3) security: bump Pygments 2.19.2 → 2.20.0 | security | none | no | 0.18.6 |
| fst | [#17](https://github.com/satisfymath/c13-fst/pull/17) security: bump dnspython 2.8.0 → 2.9.0 | security | green | yes | 0.18.6 |
| marshmallow | [#3](https://github.com/satisfymath/c13-marshmallow/pull/3) security: bump certifi 2026.7.22 → 2026.10.18 | security | green | yes | 0.18.6 |
| oauthlib | [#2](https://github.com/satisfymath/c13-oauthlib/pull/2) fix: 1 ruff-baseline B006 finding in oauthlib/oauth2/rfc6749/endpoints/ | quality | green | yes | 0.18.6 |
| python-mss | [#1](https://github.com/satisfymath/c13-python-mss/pull/1) fix: AttributeError in as_region (src/mss/models.py) | correctness | red | no | 0.18.6 |
| python-progressbar | [#3](https://github.com/satisfymath/c13-python-progressbar/pull/3) security: bump certifi 2026.5.20 → 2026.10.18 | security | green | yes | 0.18.6 |
| reader | [#1](https://github.com/satisfymath/c13-reader/pull/1) fix: 19 ruff-baseline F821 findings in tests/data/ | quality | green | yes | 0.18.6 |
| resumeio-to-pdf | [#5](https://github.com/satisfymath/c13-resumeio-to-pdf/pull/5) security: bump urllib3 2.5.0 → 2.8.0 | security | none | no | 0.18.6 |
| resumeio-to-pdf | [#4](https://github.com/satisfymath/c13-resumeio-to-pdf/pull/4) security: bump starlette 0.47.3 → 1.3.1 | security | none | no | 0.18.6 |
| resumeio-to-pdf | [#3](https://github.com/satisfymath/c13-resumeio-to-pdf/pull/3) security: bump idna 3.10 → 3.15 | security | green | no | 0.18.6 |
| resumeio-to-pdf | [#2](https://github.com/satisfymath/c13-resumeio-to-pdf/pull/2) security: bump certifi 2025.8.3 → 2026.10.18 | security | green | no | 0.18.6 |
| resumeio-to-pdf | [#1](https://github.com/satisfymath/c13-resumeio-to-pdf/pull/1) security: bump anyio 4.10.0 → 4.14.2 | security | green | yes | 0.18.6 |
| rich | [#22](https://github.com/satisfymath/c13-rich/pull/22) fix: ZeroDivisionError in _split_text (rich/cells.py) | correctness | red | no | 0.18.6 |
| rich | [#21](https://github.com/satisfymath/c13-rich/pull/21) fix: IndexError in _split_text (rich/cells.py) | correctness | red | no | 0.18.6 |
| rich | [#20](https://github.com/satisfymath/c13-rich/pull/20) fix: 2 ruff-baseline F821 findings in tests/ | quality | green | no | 0.18.6 |
| rich | [#19](https://github.com/satisfymath/c13-rich/pull/19) fix: 2 ruff-baseline F821 findings in rich/ | quality | green | no | 0.18.6 |
| rich | [#18](https://github.com/satisfymath/c13-rich/pull/18) fix: 1 ruff-baseline F821 finding in examples/ | quality | green | yes | 0.18.6 |
| tracklater | [#1](https://github.com/satisfymath/c13-tracklater/pull/1) fix: 2 ruff-baseline F811 findings in tracklater/tests/ | quality | green | yes | 0.18.6 |
| aegra | [#9](https://github.com/satisfymath/c13-aegra/pull/9) fix(deps): bump langgraph-sdk 0.4.2 → 0.4.6 (security) | security | green | no | 0.18.9 |
| aegra | [#8](https://github.com/satisfymath/c13-aegra/pull/8) fix(deps): bump filelock 4.0.9 → 4.2.1 (security) | security | green | no | 0.18.9 |
| aegra | [#7](https://github.com/satisfymath/c13-aegra/pull/7) fix(deps): bump certifi 2026.1.4 → 2026.10.18 (security) | security | green | yes | 0.18.9 |
| rich | [#25](https://github.com/satisfymath/c13-rich/pull/25) fix: 2 ruff-baseline F821 findings in rich/ | quality | green | no | 0.18.9 |
| rich | [#24](https://github.com/satisfymath/c13-rich/pull/24) fix: 2 ruff-baseline F821 findings in tests/ | quality | green | no | 0.18.9 |
| rich | [#23](https://github.com/satisfymath/c13-rich/pull/23) fix: 1 ruff-baseline F821 finding in examples/ | quality | green | yes | 0.18.9 |
| sqlmodel | [#5](https://github.com/satisfymath/c13-sqlmodel/pull/5) fix(deps): bump starlette 0.50.0 → 1.3.1 (security) | security | green | no | 0.18.9 |
| sqlmodel | [#4](https://github.com/satisfymath/c13-sqlmodel/pull/4) fix(deps): bump idna 3.11 → 3.15 (security) | security | green | no | 0.18.9 |
| sqlmodel | [#3](https://github.com/satisfymath/c13-sqlmodel/pull/3) fix(deps): bump certifi 2025.11.12 → 2026.10.18 (security) | security | green | no | 0.18.9 |
| sqlmodel | [#2](https://github.com/satisfymath/c13-sqlmodel/pull/2) fix(deps): bump black 26.5.1 → 26.10.1 (security) | security | green | no | 0.18.9 |
| sqlmodel | [#1](https://github.com/satisfymath/c13-sqlmodel/pull/1) fix(deps): bump anyio 4.12.0 → 4.14.2 (security) | security | green | yes | 0.18.9 |

Some green pull requests stayed unmerged, and the reason was not a defect. When one pull request merged,
the others that touched the same lock file went stale, and the product closed them to measure them again.
0.18.10 lets the observed cycle wait for that new proposal. Others stayed open because the pass ended first.
A red pull request is left to a person by rule, even when the base was red already (ctfd's own lint).
dooit's merge shows CI `none`: its workflows run only on pushes to `develop`, never on a pull request, so
the lab's evidence is all there is (0.18.6), and the independent check confirms the advisories gone.

## Repositories without a pull request

These are listed in `REPORT-aggregate.md`, one row each with its reason. The reasons include: nothing to
propose, the team's CI does not run the tool, no proven fix, a stack that does not build here, no compose
file, or out of scope (TypeScript, Go, a monorepo subdirectory).

Still running when this page was generated: brightbean-studio, codex-lb, gin, gymhero, harlequin, misago, recruitops-agent, spoolman, timetracker, traefik-manager, weblate.

## How this pass got here

The pass was started on 0.18.1 and stopped five times. Each time its own records showed a general product
defect, and each was fixed with a test and released before going on (0.18.2 to 0.18.10, in `FINDINGS.md`).
The stopped starts are kept in `final-0.18.*-stopped/`. They are never added to the totals above:
- final-0.18.5-stopped (0.18.5): 9 pull requests, 3 merged

## Where

- `final-evidence.json`: this page as data, for the site.
- `REPORT-aggregate.md`: every dimension per class with Wilson intervals, one joined row per repository, and
  the comparison with campaign 12.
- `<repo>/B1.json`, `<repo>/run.log`, `<repo>/export/`: each run's record, its log, and the agent's own export
  (events, decisions, experiments, transcripts of every model call, secret-scanned).
- `verify/`: the independent checks.
