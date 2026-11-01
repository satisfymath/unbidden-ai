# Campaign 12: corpus selection log

Written 2026-11-01 (UTC) before any candidate was inspected. Read-only: GitHub's search and contents API with the
`satisfymath` token (nothing created, forked, starred or written); no clone, no Docker, no model. Every inspection
is recorded below, in order, before the next candidate was examined. Nothing in the rule changed after the first
inspection.

## Rule (fixed before the first inspection)

**Base rule:** stage 10's eight criteria (`docs/bench/stage10-evaluation.md`), generalized from "FastAPI on
PostgreSQL" to the declared support of `unbidden/observe/scope.py:diagnose` (a Python project at the root with
`pyproject.toml` / `requirements.txt` / `setup.py` / `setup.cfg`; a GitHub Actions job that runs pytest; a compose or
CI database service where the family is an application; interpreters 3.8-3.13).

**Source, deterministic:** GitHub's search API, authenticated, sorted by stars descending, one query per quota,
all pages read (the first 300 results at most). Queries and quotas, in this order:

| # | query | quota |
|---|---|---|
| 1 | `language:Python stars:>150 pushed:>2026-05-01 archived:false topic:fastapi` | 5 applications with a database service (compose or CI service container); PostgreSQL preferred; at most 2 with SQLite/MySQL only |
| 2 | same, `topic:django` | 3 applications, only if a pytest path exists in CI (Django's own runner is not pytest; those go to the frontier set) |
| 3 | same, `topic:flask` | 3 applications |
| 4 | `language:Python stars:>300 pushed:>2026-05-01 archived:false topic:library`, then `topic:python-library` if needed | 6 libraries without services, varied build tools (at least one each of uv, Poetry, hatch, tox, setuptools/pip, make where found) |
| 5 | `language:Python stars:>150 pushed:>2026-05-01 archived:false topic:cli` | 3 CLI tools |

**Criteria, all required, per candidate** (the file read for each is named in the log):
1. An OSI license identified by GitHub (`license.spdx_id` neither `NOASSERTION` nor empty).
2. Size < 500 MB (`size` < 512,000 KB in the repository metadata).
3. A Python project at the repository root: `pyproject.toml`, `setup.py`, `setup.cfg` or `requirements.txt` in
   the root tree of the default branch's HEAD.
4. A GitHub Actions workflow whose job runs pytest (workflow files read through the contents API; matrix, services
   and groups noted). A Django application whose CI runs only `manage.py test` fails this criterion.
5. Not a framework, an ORM, a course, a tutorial, a template/boilerplate, an awesome list, a Docker image or an
   example collection (the README/description and the root tree decide).
6. No mandatory external paid service or credentials to run its tests (README, settings and workflow env read).
7. Not previously exposed: not in the development corpus (`docs/CAMPAIGN-v1.md` section 3), not in
   `bench/repos/{campaign-v1,level-a,scale,corpus-2026-10-28}.yaml`, not in `bench/corpus/2026-10-28-pool.json`
   (3,000 names), not named in `docs/bench/stage10-evaluation.md` or `stage9-evaluation.md`, not the parent of a fork
   on the `satisfymath` account (24), not among the CAMPAIGN-v1 flask inspections, not a dependency of Unbidden.
   The merged list (3,192 names, lower-cased `owner/repo`) is applied mechanically before examination.
8. Pushed after 2026-05-01 (already in the query; re-checked in the metadata).
Quota-specific: quotas 1-3 need an application with a database (a compose file or a CI service container names
PostgreSQL, MySQL/MariaDB or SQLite is the application's store); quota 4 needs no service; quota 5 a command-line
tool. Two members of one project family (two FastAPI starter templates, two admin panels of the same ORM) count as
one: the second is recorded as a near-duplicate and does not fill the quota.

**Window and ordering:** candidates are examined in search order. Criterion 7 is a property of this evaluation's
history, not of the repository, so it is applied as a pre-filter: the 60-candidate window of each query counts
repositories that are *not* previously exposed (`w01..w60`); the absolute search rank is recorded too (`r91`).
Under the strict alternative reading (the window counts all 60 first results, exposed ones included), the
`topic:fastapi` quota would be empty by construction, because stage 10 inspected and thereby exposed that query's
first 90 results; that outcome is recorded in the shortfalls, so the evaluation can choose either reading. The first
candidates that pass every criterion fill the quota; a quota that cannot be filled inside its window is recorded as
a shortfall and no criterion is relaxed. No candidate is skipped for a reason not listed here, and none is replaced
after a run.

**Pin:** the default branch's HEAD SHA at inspection time (`repos/O/R/commits/<default_branch>`).

**Inspection record format:** `wNN rRRR owner/repo: verdict (criterion failed, or PASS) ; files read`.
Metadata-only rejections name the metadata field. Per candidate the script `inspect.sh` (kept in the session
scratchpad, reproduced in section "Method") read: repository metadata, HEAD SHA, root tree, every workflow under
`.github/workflows` (lines mentioning pytest, python-version, services, matrix, tox/nox/make/uv/poetry/hatch/pdm,
npm/pnpm, go test, manage.py test), and any root compose file (service names and images).

**Frontier set (8):** one per class, chosen by the first fit in a stated query, same record format, with "why it is
frontier" and what the product should say. Classes: (1) Python project in a monorepo subdirectory (no root
pyproject); (2) Django application whose CI uses `manage.py test`; (3) a Python application whose only database is
MySQL/MariaDB; (4) a Python project with no tests in CI or no CI; (5) Python + TypeScript, CI runs both; (6) a
TypeScript/Node project; (7) a Go project; (8) a very large or very old Python project inside support (> 400 MB or a
10,000+ test suite).

## Search snapshots (taken 2026-11-01, before inspection)

| query | total_count | items read |
|---|---|---|
| topic:fastapi | 306 | 306 (exposed by the pre-filter: the first 90 and others) |
| topic:django | 394 | 394 |
| topic:flask | 141 | 141 |
| topic:library (stars:>300) | 51 | 51 |
| topic:python-library (stars:>300) | 58 | 58 |
| topic:cli | 395 | 395 |

