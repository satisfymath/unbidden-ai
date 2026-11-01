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


## Exclusions applied (criterion 7)

3,192 lower-cased `owner/repo` names, merged from: `bench/repos/{campaign-v1,level-a,scale,corpus-2026-10-28}.yaml`
URLs; `bench/corpus/2026-10-28-pool.json` (3,000 names); `docs/CAMPAIGN-v1.md` section 3 (dev corpus + the named
CAMPAIGN-v1 flask/django inspections + the prototype set); `docs/bench/stage10-evaluation.md` and
`stage9-evaluation.md` mentions; the 24 fork parents on `satisfymath` (`gh repo list satisfymath --fork`); and
Unbidden's own dependencies (pydantic, pyyaml, jsonschema, httpx, rich, scipy, google-re2, psycopg, pytest,
pytest-asyncio, ruff, pyright). A secondary check flags bare repo-name collisions for a manual look. Note: the dev
corpus TimeTracker is `DRYTRIX/TimeTracker` (GPL-3.0, Flask+Postgres) -- it surfaced at flask rank r69 and was
excluded as previously exposed.

## Inspection log (in order, per quota)

Format: `wNN rRRR owner/repo -> verdict ; files read`. "meta" = repository metadata (license/size/stars/branch/
dates). "root" = default-branch HEAD tree. "wf:<name>" = that workflow file. "compose" = a root compose file.
Exposed candidates are skipped by the pre-filter and not re-listed individually (counts given per quota).

### Quota 1 - topic:fastapi (90 exposed results skipped first; window of non-exposed candidates follows)

- w01 r091 LvcidPsyche/auto-browser -> REJECT c1-ok but c-quota: no database service (compose has browser-node/controller, no DB); browser/MCP app ; meta, root, wf:ci.yml, compose
- w02 r092 cle-b/httpdbg -> REJECT c5 (developer tool / library, not an application with a DB) ; meta, root, wf:build.yml
- w03 r093 getludic/ludic -> REJECT c5 (HTML template-engine library) ; meta, root, wf:test.yaml
- w04 r094 JoeanAmier/KS-Downloader -> REJECT c4 (workflows are build/release/stale only, no pytest job) ; meta, root, wf:*
- w05 r095 Aeternalis-Ingenium/FastAPI-Backend-Template -> REJECT c5 (project template/boilerplate) ; meta, root, wf:ci-backend.yaml, compose (postgres present)
- w06 r096 DemonDamon/AgenticX -> REJECT c4 (CI is desktop build + enterprise-db-compat via pnpm; no python pytest job) ; meta, root, wf:*
- w07 r097 Anil-matcha/open-agent-connector -> REJECT c4 (no .github/workflows) + c3 (server/ + client/, no root manifest) ; meta, root, compose
- w08 r098 Guard-Core/fastapi-guard -> REJECT c5 (FastAPI security library) ; meta, root, wf:ci.yml
- w09 r099 felipeall/resumeio-to-pdf -> REJECT c4 (CI is ruff only, no pytest) -> FRONTIER class 4 ; meta, root, wf:ruff.yml
- w10 r100 litestar-org/advanced-alchemy -> REJECT c5 (SQLAlchemy companion library) ; meta, root, wf:ci.yml/test.yml
- w11 r101 shuxiachai/academic-commercialization-agent -> REJECT quota (compose service is only `app`, no DB) + c6 risk (crewai/anthropic, Node required for contract tests) ; meta, root, wf:test.yml, compose, pyproject
- w12 r102 fastapi-mvc/fastapi-mvc -> REJECT c5 (project generator / template tool) ; meta, root, wf:main.yml
- w13 r103 ChenShuo2004/cs-board -> REJECT c4 (no workflows) ; meta, root
- w14 r104 myccarl/ai-shortVideo-pipeline -> REJECT c4 (no workflows) + c3 (requirements.txt at root but no CI) ; meta, root, compose (postgres/redis/minio)
- w15 r105 mr-fatalyst/oxyde -> REJECT c5 (ORM) ; meta, root, wf:test.yml
- w16 r106 asaotomo/FofaMap -> REJECT quota (no database; asset-mapping tool) ; meta, root, wf:ci.yml
- w17 r107 volfpeter/fasthx -> REJECT c5 (FastAPI SSR utility library) ; meta, root, wf:tests.yml
- w18 r108 iktakahiro/dddpy -> REJECT c5 (DDD example) ; meta, root, wf:test.yaml
- w19 r109 Nativu5/Gemini-FastAPI -> REJECT quota (no DB) + c6 (wraps Gemini) ; meta, root, wf:ruff.yaml
- w20 r110 canarybyte/veridrop -> REJECT quota (no DB service; API-relay checker) ; meta, root, wf:test.yml, pyproject
- w21 r111 aixisstudio/Snitch -> REJECT quota (compose has no DB; network monitor) ; meta, root, wf:ci.yml, compose
- w22 r112 vibber-ai/fastapi-azure-auth -> REJECT c5 (auth library) ; meta, root, wf:testing.yaml
- w23 r113 AgentTeam-TaichuAI/ScienceClaw -> REJECT c1 (license None) + c3 (no root manifest) ; meta, root, compose
- w24 r114 Mafifrizi/ARES -> REJECT c5-family (offensive red-team tooling; not a representative application) despite mechanical pytest+postgres ; meta, root, wf:ci.yml, pyproject
- w25 r115 judahpaul16/gpt-home -> REJECT c3 (root has only requirements-test.txt; no requirements.txt/pyproject/setup at root) ; meta, root, wf:workflow.yml, compose (pgvector), requirements-test.txt, tests/
- w26 r116 fastapi/fastapi-cli -> REJECT c5 (CLI tool for FastAPI; and a fastapi/* dependency-adjacent) ; meta, root, wf:*
- w27 r117 hotosm/tasking-manager -> REJECT c6 (CI uses an external reusable workflow `hotosm/gh-workflows` with `secrets: inherit` and prebuilt ghcr images; not reproducible from the repo alone) ; meta, root, wf:pr_test_backend.yml, compose (postgis)
- w28 r118 SulgX/SulgX-Panel -> REJECT c4 (no workflows) ; meta, root
- w29 r119 emersonfelipesp/netbox-proxbox -> REJECT c5 (NetBox plugin, not standalone) ; meta, root, wf:ci.yml/django-tests.yml
- w30 r120 tomwojcik/starlette-context -> REJECT c5 (Starlette middleware library) ; meta, root, wf:test-suite.yml
- w31 r121 Krukov/cashews -> REJECT c5 (cache library) ; meta, root, wf:tests.yml
- w32 r122 ivan-borovets/fastapi-clean-example -> REJECT c5 (clean-architecture example) ; meta, root, wf:ci.yaml, compose (postgres:18)
- w33 r123 rafsaf/minimal-fastapi-postgres-template -> REJECT c5 (template) ; meta, root, wf:tests.yml, compose (postgres)
- w34 r124 skygazer42/MimirQ -> ACCEPT (api-postgres) ; meta, root, wf:ci.yml, compose, requirements.txt, .env.example (CI uses LLM_MOCK_ENABLED=true + sk-test; no paid key)
- w35 r125 PunithVT/ai-avatar-system -> REJECT c3 (manifest under backend/, not root) -> FRONTIER class 5 ; meta, root, wf:ci.yml (postgres+redis, env provided), backend/
- w36 r126 Anil-matcha/Open-AI-Micro-Drama-Generator -> REJECT c1 (license None) ; meta, root
- w37 r127 Hainrixz/whatsapp-agentkit -> REJECT c4 (no workflows) ; meta, root
- w38 r128 SearchSavior/OpenArc -> REJECT quota (no DB; Intel inference engine) + c5 (inference platform) ; meta, root, wf:run-unit-tests.yml, compose
- w39 r129 caura-ai/caura -> REJECT c3 (core-api/ + clients/ layout, no root manifest) ; meta, root, wf:ci.yml
- w40 r130 JiayuXu0/FastAPI-Template -> REJECT c5 (template) ; meta, root, wf:ci.yml, compose
- w41 r131 Yzw202011/OmniSpace -> REJECT c1 (license None) + c4 (no workflows) ; meta, root
- w42 r132 yaojingang/GEORank -> REJECT c3 (apps/ + backend/, no root manifest) ; meta, root, wf:backend-ci.yml (postgres), frontend-ci.yml
- w43 r133 GACWR/OpenUBA -> REJECT c5 (UEBA framework) ; meta, root, wf:ci-backend.yml
- w44 r134 apocas/restai -> REJECT c5/c-quota (AIaaS platform; CI inits sqlite via database.py, no DB service; GPU group; frontend) ; meta, root, wf:tests.yml, pyproject, compose
- w45 r135 Lancetnik/FastDepends -> REJECT c5 (DI library extracted from FastAPI) ; meta, root, wf:tests.yml
- w46 r136 Azure-Samples/rag-postgres-openai-python -> REJECT c5 (Azure sample) + c6 (OpenAI/Azure) ; meta, root, wf:app-tests.yaml
- w47 r137 didilili/shopkeeper-agent -> REJECT c3 (app/ + frontend/, no root CI manifest) + c6 (LangGraph/LLM, ES/Qdrant/MySQL) ; meta, root
- w48 r138 tomasvotava/fastapi-sso -> REJECT c5 (SSO plugin/library) ; meta, root, wf:test.yml
- w49 r139 RMA-MUN/RAGNotebook -> REJECT c3 (backend/ only, no root manifest) ; meta, root, wf:ci.yml
- w50 r140 zrt-ai-lab/ViNote -> REJECT c4 (CI runs `python -m unittest`, not pytest) ; meta, root, wf:checks.yml
- w51 r141 jod35/fastapi-beyond-CRUD -> REJECT c1 (license None) + c5 (tutorial series source) ; meta, root, wf:(none), compose
- w52 r142 violit-dev/violit -> REJECT c5 (web framework) ; meta, root
- w53 r143 felipeall/transfermarkt-api -> REJECT quota (no database; scraping API) ; meta, root, wf:check.yml
- w54 r144 bigsk1/voice-chat-ai -> REJECT quota (no DB service) + c6 (LLM/TTS providers) ; meta, root, wf:*, compose
- w55 r145 piccolo-orm/piccolo_admin -> REJECT c5 (ORM admin library; tests SQLite-only) ; meta, root, wf:tests.yaml
- w56 r146 benavlabs/crudadmin -> REJECT c5 (FastAPI admin library) ; meta, root, wf:tests.yml
- w57 r147 Beever-AI/beever-atlas -> REJECT quota (DB is MongoDB, not postgres/mysql/sqlite) + c6 (LLM-wiki) ; meta, root, wf:ci.yml (mongo+redis)
- w58 r148 dialoguemd/fastapi-sqla -> REJECT c5 (SQLAlchemy extension library) ; meta, root
- w59 r149 KLR-Pattern/fastapi-voyager -> REJECT c5 (API visualizer library) ; meta, root, wf:publish.yml
- w60 r150 OschAI/VisioFirm -> REJECT c4 (CI is publish only, no pytest) ; meta, root, wf:publish.yml
- RESULT: 1 accepted (MimirQ). SHORTFALL 4 of 5. The topic:fastapi window is dominated by templates/boilerplates,
  libraries/ORMs/plugins, LLM wrappers needing provider keys, and backend+frontend monorepos with no root manifest.

### Quota 2 - topic:django (7 exposed skipped first; pytest-path applications)

- w01 r001 django/django -> REJECT c5 (the framework) ; meta
- w02 r004 jumpserver/jumpserver -> REJECT c4 (CI is image builds/compile-messages; no pytest) + security PAM platform ; meta, root, wf:*
- w03 r005 encode/django-rest-framework -> REJECT c1 (NOASSERTION) + c5 (framework) ; meta
- w04 r006 netbox-community/netbox -> REJECT c4 (CI `manage.py test`, not pytest) -> FRONTIER class 2 ; meta, root, wf:ci.yml (postgres+redis)
- w05 r007 wagtail/wagtail -> REJECT c5 (CMS framework) ; meta
- w06 r008 suitenumerique/docs -> REJECT c3 (src/backend layout, no root manifest) ; meta
- w07 r009 ansible/awx -> REJECT c1 (NOASSERTION) ; meta
- w08 r010 cookiecutter/cookiecutter-django -> REJECT c5 (template) ; meta
- w09 r011 wsvincent/awesome-django -> REJECT c5 (awesome list) ; meta
- w10 r012 django-cms/django-cms -> REJECT c1 (NOASSERTION) + c5 (framework) ; meta
- w11-w12, w21, w22, w27, w29, w30, w33-w35, w37, w41, w43, w44 -> REJECT c5 (django-allauth, django-ninja, cors-headers, authlib, graphene-django, django-unfold, drf-yasg, oauth-toolkit, import-export, django-environ, django-storages, viewflow, drf-spectacular, whitenoise, django-unicorn: libraries/frameworks) ; meta
- w13 r016 LibrePhotos/librephotos -> REJECT c3 (apps/ monorepo, no root manifest) -> FRONTIER class 1 ; meta, root, wf:*
- w14 r017 joerick/pyinstrument -> REJECT c5 (profiler library) ; meta
- w15 r018 inventree/InvenTree -> REJECT (ambiguous runner: `invoke` + pytest-django; large 393 MB; postgres services) - left out of independent ; meta, root, wf:qc_checks.yaml/frontend.yaml (postgres)
- w16 r019 liangliangyy/DjangoBlog -> REJECT c4 (CI `manage.py test`, not pytest) ; meta, root, wf:django.yml
- w17 r020 wger-project/wger -> REJECT c4 (CI `manage.py test`, not pytest) ; meta, root, wf:ci.yml
- w18 r021 django-oscar/django-oscar -> REJECT c5 (e-commerce framework) ; meta
- w19 r022 WeblateOrg/weblate -> REJECT c2 (size ~5.8 GB) -> FRONTIER class 8 ; meta
- w20 r023 coleifer/huey -> REJECT c5 (task-queue library) ; meta
- w23 r026 mediacms-io/mediacms -> ACCEPT (web-django) ; meta, root (pyproject+requirements+setup.cfg), wf:python.yml (pytest via docker compose), compose (postgres:17+redis)
- w24 r027 DefectDojo/django-DefectDojo -> REJECT c2 (size 926 MB) ; meta
- w25 r028 jazzband/django-silk -> REJECT c5 (profiling library) ; meta
- w26 r030 amidaware/tacticalrmm -> REJECT c1 (NOASSERTION) ; meta
- w28 r033 FuzzyGrim/Yamtrack -> REJECT c4 (CI `manage.py test`; pytest.ini present but CI does not call pytest) ; meta, root, wf:app-tests.yml
- w31 r037 modoboa/modoboa -> REJECT c4 (CI `manage.py test`, not pytest) ; meta, root, wf:modoboa.yml (postgres/mysql matrix)
- w32 r038 Gerapy/Gerapy -> REJECT c5 (scrapy management framework) ; meta
- w36 r042 swirlai/swirl-search -> REJECT c6 risk (AI search, provider keys) + size 271 MB ; meta
- w38 r044 babybuddy/babybuddy -> REJECT c4 (Django app; CI not pytest) ; meta, root, wf:ci.yml
- w39 r045 opencve/opencve -> REJECT c1 (NOASSERTION) ; meta
- w40 r046 viewflow/viewflow -> REJECT c5 (workflow library) ; meta
- w42 r048 rafalp/Misago -> ACCEPT (web-django) ; meta, root (requirements.txt+setup.py), wf:tests.yml (pytest + postgres:15)
- w45 r052 brightbeanxyz/brightbean-studio -> ACCEPT (web-django) ; meta, root (pyproject+requirements.txt), wf:ci.yml (pytest + postgres)
- RESULT: 3 accepted (mediacms, Misago, brightbean-studio). Quota FILLED.

### Quota 3 - topic:flask (17 exposed skipped first; applications)

- w01 r001 Asabeneh/30-Days-Of-Python -> REJECT c1 (license None) + c5 (course) ; meta
- w02-w08,w10-w13,w18,w21,w23,w25,w27-w30,w32,w34,w35,w37,w40,w43-w45,w48,w49,w51,w54,w56,w60 ->
  REJECT c5 (libraries/frameworks: ProxyPool, UltraRAG, Flask-SocketIO, authlib, Flask-AppBuilder, dependency-injector,
  FractalCore, flask-sqlalchemy, quart, responder, toapi, Flask-Migrate, flask-jwt-extended, flask-wtf, environs,
  apispec, Flask-HTTPAuth, flask-limiter, apiflask, flask-caching, httpdbg, flask-marshmallow, badsecrets,
  advanced-alchemy, flask-smorest, flask-security, fastopenapi, pytest-flask, wireup) ; meta (+root for several)
- w09 r016 Fractal-Compute-Orchestrations/FractalCore -> REJECT c1 (NOASSERTION) ; meta
- w14 r024 christabor/flask_jsondash -> REJECT c4 (CI codeql only, no pytest) + DB is MongoDB ; meta, root, wf:codeql, compose (mongo)
- w16 r027 flaskbb/flaskbb -> REJECT c1 (NOASSERTION) ; meta
- w17 r029 ChrispyBacon-dev/DockFlare -> REJECT c1 (NOASSERTION) ; meta
- w19 r033 fabston/TradingView-Webhook-Bot -> REJECT c4 (no test CI) ; meta
- w20 r034 chr0nzz/traefik-manager -> ACCEPT (web-flask, no DB) ; meta, root (requirements+pytest.ini), wf:tests.yml (pytest; also a Go job)
- w22 r036 HaoZhang95/Python24 -> REJECT c5 (learning repo) ; meta
- w24 r038 tecladocode/rest-apis-flask-python -> REJECT c1 (license None) + c5 (course projects) ; meta
- w26 r040 spiral-project/ihatemoney -> REJECT c1 (NOASSERTION) ; meta
- w31 r046 dannymcc/bluehood -> REJECT c4 (CI is docker build only) ; meta, root, wf:docker.yml
- w33 r049 PhialsBasement/LibreCrawl -> REJECT c4 (no workflows) ; meta, root
- w36 r053 helloflask/flask-tutorial -> REJECT c1 (license None) + c5 (tutorial) ; meta
- w38 r055 logamee/lin-cms-flask -> REJECT c1 (NOASSERTION) ; meta
- w39 r056 Allen7D/mini-shop-server -> REJECT c4 (no workflows) ; meta, root, compose (postgres)
- w42 r059 cernopendata/opendata.cern.ch -> REJECT c5 (Invenio instance) + size 331 MB ; meta
- w46 r063 nickjj/docker-flask-example -> REJECT c5 (example) ; meta
- w47 r064 liwanlei/FXTest -> REJECT c4 (no workflows) ; meta, wf(none)
- w50 r067 inveniosoftware/invenio -> REJECT c5 (digital-library framework) ; meta
- w52 r069 DRYTRIX/TimeTracker -> REJECT c7 (this is the development-corpus TimeTracker; previously exposed) ; meta
- w53 r070 weijiang1994/Blogin -> REJECT c4 (no CI tests; compose MySQL only) ; meta
- w55 r072 fe80Grau/ytdlp2STRM -> REJECT c4 (CI docker-publish only) ; meta, wf
- w57 r074 Lost-MSth/Arcaea-server -> REJECT c4 (no workflows) ; meta, wf(none)
- w58 r075 sentriz/betanin -> REJECT c4 (CI test.yaml runs ruff/npm, no pytest) ; meta, wf:test.yaml
- w59 r076 hackersandslackers/flask-blueprint-tutorial -> REJECT c5 (tutorial) ; meta
- RESULT: 1 accepted (traefik-manager). SHORTFALL 2 of 3. The topic:flask window is almost entirely Flask
  extension libraries, NOASSERTION-licensed apps, tutorials/courses, and applications with no pytest CI job.

### Quota 4 - topic:library stars:>300 (1 exposed skipped; also used topic:python-library)

- w01 r001 ccxt/ccxt -> REJECT c2 (size 8.9 GB) ; meta
- w02 r002 gruns/icecream -> REJECT (uncertain CI runner; tox toxenvs not confirmed pytest) - left out in favor of clearer libraries ; meta, root, wf:ci.yml
- w03 r003 kubernetes-client/python -> REJECT c5 (generated API client, huge) ; meta
- w04 r005 nabla-c0d3/sslyze -> REJECT quota-family (network scanner, needs live TLS endpoints) ; meta
- w05 r006 borb-pdf/borb -> REJECT c1 (NOASSERTION) + c2 (805 MB) ; meta
- w06 r007 oauthlib/oauthlib -> ACCEPT (library; tox + make) ; meta, root, wf:lint_python.yml (pytest), tox.ini
- w07 r008 binance/binance-connector-python -> REJECT quota-family (exchange API client; network) ; meta (via mysql/other cross-check), wf:ci.yaml
- w08 r009 gruns/furl -> REJECT c1 (NOASSERTION) ; meta
- w09 r010 dateutil/dateutil -> REJECT c1 (NOASSERTION) ; meta
- w10 r011 sepandhaghighi/art -> REJECT c4 (CI test.yml uses a custom runner, not pytest/tox/unittest) ; meta, root, wf:test.yml
- w11 r012 trailofbits/graphtage -> ACCEPT (library; uv + hatch) ; meta, root, wf:pythonpackage.yml (pytest), uv.lock
- w12 r013 kivymd/KivyMD -> REJECT c5 (UI framework) + display deps ; meta
- w13 r014 hhursev/recipe-scrapers -> REJECT quota-family (scraper; network) ; meta
- w14 r015 apache/libcloud -> REJECT c5 (cloud abstraction framework) ; meta
- w15-w17,w22,w29,w30 -> REJECT (riko: no pytest; yandex-music-api: network; parallel-ssh: needs ssh server; CUP; PyPtt: network; bitcoinlib: AGPL ok but network/node) ; meta
- w18 r019 brainix/pottery -> REJECT quota (needs a redis service) ; meta, root
- w19 r020 tmux-python/libtmux -> REJECT (needs a tmux binary; kept as backup, not needed) ; meta, root, wf:tests.yml (uv, pytest)
- w20 r021 viblo/pymunk -> REJECT c4 (CI runs `python -m unittest`, not pytest) ; meta, root, wf
- w23 r024 argoproj-labs/hera -> REJECT quota-family (Argo Workflows client) ; meta
- w24 r025 ceccopierangiolieugenio/pyTermTk -> REJECT (TUI toolkit; display) ; meta
- w25 r026 wolph/python-progressbar -> ACCEPT (library; setuptools/pip + tox) ; meta, root, wf:main.yml (pytest), autofix.yml (tox)
- w26 r027 acl-org/acl-anthology -> REJECT c2 (910 MB) ; meta
- w27-w28,w31 -> REJECT c1 (NOASSERTION: nose2, python-zeroconf, simpleeval) ; meta
- w32,w39 -> REJECT c5 (KiCad parts libraries, not Python test suites) ; meta
- w33 r034 Xewdy444/Playwright-reCAPTCHA -> REJECT quota-family (browser automation; network) ; meta
- w34 r035 kz26/PyExcelerate -> REJECT (left out; Excel writer, candidate backup) ; meta
- w35 r036 miurahr/py7zr -> REJECT (left out; candidate backup, LGPL ok) ; meta
- w36 r037 lemon24/reader -> ACCEPT (library; tox) ; meta, root, wf:build.yaml (coverage run -m pytest), tox.ini
- w37 r038 dylanljones/pyrekordbox -> REJECT (left out; candidate backup) ; meta
- w38 r039 bisohns/search-engine-parser -> REJECT c1 (license None) ; meta
- python-library window: w04 r005 docker/docker-py -> REJECT (needs docker daemon in tests); w07 mongo-python-driver ->
  REJECT (needs mongo); w13 django-celery-beat -> REJECT c1 (NOASSERTION); w20 r021 alan-turing-institute/CleverCSV ->
  REJECT c4 (CI runs `python -m unittest`, not pytest); w21 r022 BoboTiG/python-mss -> ACCEPT (library; hatch);
  w02 kellyjonbrazil/jc -> REJECT c4 (CI `python -m unittest`) ; meta/root/wf for each as noted
- RESULT: 6 accepted (oauthlib, rdflib [python-library/library overlap r011], graphtage, python-progressbar,
  python-mss, reader). Quota FILLED. Build-tool coverage: tox (oauthlib, reader, rdflib), uv (rdflib, graphtage),
  hatch (graphtage, python-mss), setuptools/pip (python-progressbar, reader, oauthlib), make (oauthlib). NOTE: no
  Poetry-built *library* appeared in either window at stars>300 with a pytest CI job; Poetry/PDM are therefore not
  represented in the library quota (recorded, criterion not relaxed). Poetry does appear in the corpus via jrnl
  (examined for the CLI quota).

### Quota 5 - topic:cli (5 exposed skipped first)

- w01 r001 yt-dlp/yt-dlp -> REJECT (Unlicense; huge, network-heavy) ; meta
- w02 r002 Panniantong/Agent-Reach -> REJECT c6 (agent/LLM) ; meta
- w03 r003 sherlock-project/sherlock -> REJECT quota-family (network OSINT) ; meta
- w04 r004 Aider-AI/aider -> REJECT c6 (LLM provider keys) ; meta
- w05 r005 ifixai-ai/iFixAi / w17 MakazhanAlpamys/Soup / w29 Q00/ouroboros / w37 gptme / w44 av/harbor / w45 OSWorld ->
  REJECT c6 (LLM/agent platforms) ; meta
- w06 r006 chubin/cheat.sh -> REJECT (shell service; no pytest CI) ; meta
- w07 r007 soxoj/maigret -> REJECT quota-family (network OSINT) ; meta
- w08 r008 Textualize/textual -> REJECT c5 (TUI framework) ; meta
- w09 r009 FujiwaraChoki/MoneyPrinterV2 -> REJECT c6 ; meta
- w10,w11,w39,w41,w46 -> REJECT c1 (NOASSERTION: tqdm, python-fire, Hyper-Extract, claude_codex_bridge, Fuxi) ; meta
- w12 r014 beetbox/beets -> REJECT (left out; large, plugin network tests) ; meta
- w13 r015 pypa/pipx -> ACCEPT (cli; hatch) ; meta, root, wf:tests.yml (pytest)
- w14 r016 TheR1D/shell_gpt -> REJECT c6 (LLM) ; meta
- w15 r017 streamlink/streamlink -> REJECT quota-family (network streams) ; meta
- w16 r018 blacklanternsecurity/bbot -> REJECT quota-family (network recon) ; meta
- w18 r020 saulpw/visidata -> REJECT c4 (no clear pytest CI job found) ; meta, root, wf
- w19 r021 kellyjonbrazil/jc -> REJECT c4 (CI `python -m unittest`) ; meta, wf
- w20 r022 jdepoix/youtube-transcript-api -> REJECT quota-family (network) ; meta
- w21 r023 WenyuChiou/awesome-agentic-ai-zh -> REJECT c5 (awesome list) ; meta
- w22 r024 AdnanHodzic/auto-cpufreq -> REJECT (system/root-level power tool) ; meta
- w23 r025 jrnl-org/jrnl -> REJECT c4 (pytest not visibly invoked in CI workflows; uses behave/poe, unconfirmed) ; meta, wf:testing_*.yaml
- w24 r026 pypa/hatch -> REJECT (left out; build tool itself, kept distinct from hatch-built picks) ; meta
- w25 r027 jarun/buku -> REJECT (left out; candidate backup) ; meta
- w26 r028 PyCQA/isort -> REJECT c5 (import sorter; more library/formatter than CLI app) ; meta
- w27 r030 tconbeer/harlequin -> ACCEPT (cli; hatch) ; meta, root, wf:test.yml (pytest)
- w28 r031 rsalmei/alive-progress -> REJECT c5 (progress-bar library) ; meta
- w32 r035 mangiucugna/json_repair -> REJECT c5 (library) ; meta
- w33 r036 amanusk/s-tui -> REJECT (left out; hardware sensors) ; meta
- w35 r038 speedyapply/JobSpay -> REJECT quota-family (job-board scraping; network) ; meta
- w36 r039 tmux-python/tmuxp -> REJECT (needs tmux binary; backup) ; meta
- w42 r047 sloria/doitlive -> REJECT (left out; CI test job via tox not confirmed) ; meta, root, wf:build-release.yml
- w43 r048 jarun/ddgr -> REJECT quota-family (network search) ; meta
- w47 r052 dalibo/pg_activity -> REJECT (needs a live postgres to test) ; meta
- w49 r054 kislyuk/yq -> REJECT (needs jq binary) ; meta
- w50 r055 dooit-org/dooit -> ACCEPT (cli; hatch) ; meta, root, wf:pytest.yml (pytest)
- RESULT: 3 accepted (pipx, harlequin, dooit). Quota FILLED.

## Accepted independent set (14 of 20) and shortfalls

| name | family | build | checks (short) | commit (short) |
|---|---|---|---|---|
| mimirq | api-postgres | pip | ci.yml pytest; postgres+redis+minio; mock LLM | 5d08b54 |
| mediacms | web-django | pip | python.yml pytest via docker compose; postgres+redis | 9bf46be |
| misago | web-django | pip | tests.yml pytest; postgres:15 | 4a37d19 |
| brightbean-studio | web-django | pip | ci.yml pytest; postgres:16 | 1d11c52 |
| traefik-manager | web-flask | pip | tests.yml pytest (no DB) | ebf6a84 |
| oauthlib | library | tox | pytest matrix; tox+make | 179287a |
| rdflib | library | uv | validate.yaml pytest; tox+uv | f87db10 |
| graphtage | library | hatch | pythonpackage.yml pytest; uv+hatch | afa9b34 |
| python-progressbar | library | pip | main.yml pytest; tox | 05a60c9 |
| python-mss | library | hatch | tests.yml pytest | 6c00e6e |
| reader | library | tox | build.yaml pytest; tox | 4bac04e |
| harlequin | cli | hatch | test.yml pytest | ad3ecef |
| dooit | cli | hatch | pytest.yml pytest | ba2a7ef |
| pipx | cli | hatch | tests.yml pytest | 2ccbdf4 |

Shortfalls (no criterion relaxed):
- Quota 1 (topic:fastapi applications with a DB service): target 5, found 1 (MimirQ). Short by 4. Cause: the
  non-exposed window is dominated by templates/boilerplates, libraries/ORMs/plugins, LLM wrappers needing provider
  credentials, and backend+frontend monorepos without a root Python manifest.
- Quota 3 (topic:flask applications): target 3, found 1 (traefik-manager). Short by 2. Cause: the window is almost
  entirely Flask extension libraries, NOASSERTION-licensed apps, tutorials/courses, and apps with no pytest CI job.
- Quota 4 build-tool variety: Poetry/PDM not represented among the accepted libraries (none in the window had a
  Poetry build with a pytest CI job). All other requested tools (uv, hatch, tox, setuptools/pip, make) are covered.

Totals: independent 14/20 (quota 2, 4, 5 filled; quota 1 and 3 short). Frontier 8/8 (one per class).

## Frontier set (8 of 8)

| frontier_class | name | family | commit (short) | why frontier |
|---|---|---|---|---|
| 1 | librephotos | monorepo-subdir | 8def36a | no root pyproject; Python under apps/ |
| 2 | netbox | web-django | ddcfe22 | CI `manage.py test`, not pytest |
| 3 | archery | web-django-mysql | a2675e2 | only database is MySQL (postgres is where measurement is defined) |
| 4 | resumeio-to-pdf | api-nodb | 108b5cf | CI runs lint only; tests exist but no CI test job |
| 5 | ai-avatar-system | python+typescript | 0dee976 | CI runs both a Python pytest job and the TS frontend; Python under backend/ |
| 6 | zod | typescript | 2554b70 | TypeScript library, fully out of scope (not previously exposed) |
| 7 | gin | go | 0f09c3a | Go framework, fully out of scope (not previously exposed) |
| 8 | weblate | web-django-large | 80852ad | inside support but ~5.8 GB, likely to time out |

(Full fields and the per-class "product_should" expectation are in corpus-frontier.yaml.)

## Extension search (prepared for David's decision; not part of the frozen set unless accepted)

Written 2026-11-01 before any extension candidate was inspected, at the coordinator's request, to offer optional
fillers for the two shortfalls (4 FastAPI applications with a database, 2 Flask applications). The accepted sets
above are unchanged. Same criteria as the base rule (OSI license by GitHub, root Python manifest, a GitHub Actions
job running pytest, a database service for applications, not a template/library/tutorial/LLM wrapper needing a paid
key, not previously exposed, < 500 MB); exposure pre-filter as above. Rules, in this order, each run to its quota or
the exhaustion of its window (first 60 non-exposed candidates, stars descending):

| rule | query | fills |
|---|---|---|
| E1 | `language:Python stars:50..150 pushed:>2026-05-01 archived:false topic:fastapi` | FastAPI apps with a DB (up to 4) |
| E2 | `language:Python stars:>100 pushed:>2026-05-01 archived:false topic:sqlalchemy`, applications only | FastAPI apps with a DB (remaining) |
| E3 | `language:Python stars:>100 pushed:>2026-05-01 archived:false topic:postgresql`, applications only (FastAPI, Flask, Litestar, Starlette servers count) | FastAPI/ASGI apps (remaining) and Flask apps |
| E4 | `language:Python stars:50..150 pushed:>2026-05-01 archived:false topic:flask`, applications with pytest in CI (DB preferred, not required) | Flask apps (up to 2) |

Each accepted extension candidate goes to `corpus-extension.yaml` with `class: independent-extension` and
`extension_rule: E1..E4`. Record format as above.

### Extension inspection log

Search snapshots (2026-11-01): E1 total 340 (200 read, 60-candidate non-exposed window built); E2 total 72 (60-window);
E3 total 140 (60-window); E4 total 109 (60-window). Screening = metadata, root tree, every workflow (pytest? DB
images?), root compose images, via `screen.sh` (one line per repository, kept in the session scratchpad); candidates
that screened in were then read with `inspect.sh` as above. Metadata-only rejections listed first per rule.

**E1 (`stars:50..150 topic:fastapi`)** - metadata rejects c1: w06 Ai-Healthcare-Chatbot (None), w30 local-rag-llamaindex
(None), w32 TaskFlow (None), w33 stampede (None), w34 lupyne (NOASSERTION), w43 Gozar (NOASSERTION), w47 LogicPaper
(NOASSERTION). Screened 53: 25 had no root manifest or no pytest workflow -> REJECT c3/c4 (recorded in the screen
log). Screened-in, in window order:
- w02 apowerb/apowerb -> REJECT c5 (agentic *framework*; pytest job runs only test_library_import) ; meta, root, wf:build.yaml, docker-build-verify.yml (postgres:16-alpine)
- w03 krishagarwal314/CodeJury -> REJECT quota (compose: app only, no DB) + c6 (multi-agent LLM pipeline) ; meta, root, wf:ci.yml, compose
- w05 EddieTYP/image-prompt-library -> REJECT quota (no DB) ; screen
- w07 coaxk/subarr -> REJECT quota (compose: app only; no DB dependency) ; meta, root, wf:ci.yml, compose, pyproject
- w08 849879772/recruitops-agent -> ACCEPT E1 (api-postgres; compose pgvector/pg16; pytest -c pytest-public.ini; no LLM SDK; no secrets) ; meta, root, wf:ci.yml, compose, pyproject
- w11 masouduut94/volleyball_analytics -> REJECT c4 (pytest only in flake-8.yml name match; ML/video) ; screen
- w13 bomzheg/Shvatka -> ACCEPT E1 (api-postgres; FastAPI+aiogram; pytest with testcontainers postgres:18.2 or SHVATKA_TEST_DB_URL; MIT; py3.14) ; meta, root, wf:test.yml, compose, pyproject, tests/fixtures/db_provider.py
- w16 cvxv666/fomo-robinhood-radar, w18 nanotaboada/python-samples-fastapi-restful (sample), w20 Hannes221/rq-dashboard-fast (redis-only dashboard), w21 ai-forever/gpt2giga (LLM proxy), w22 henrique-coder/perplexity-webui-scraper (scraper), w24 whichmen/dxl-commerce-agent (LLM e-commerce agent), w25 PXSYS13/yadisk_backup, w26 danielhasan1/fastapi-listing (library), w31 appleweiping/WEIPING_COUNCIL (LLM), w35 JiayiLu2003/Trend2Video-Pro, w36 aaronsb/knowledge-graph-system (pytest only in lint.yml), w37 ahnafnafee/local-llm-pdf-ocr, w38 Stellar-Sentinel/sentinel-backend, w54 notadev-iamaura/OneRAG (RAG framework), w55 KOKOSde/localmod, w59 vpcarlos/profyle (dev tool) -> REJECT (no DB service and/or c5/c6) ; screen
- w29 lkmeta/txtify -> REJECT quota (compose: app only; whisper/deepl ASR) ; meta, root, wf:tests.yml, compose
- w40 RRHTY/tg-channel-sync -> REJECT quota (no DB) + c6 (Telegram credentials) ; meta, root, wf:release.yml, compose
- w46 wendaochangsheng/Rapid-Inbox -> REJECT quota (local storage, no DB service; C++ ingest engine) ; meta, root, wf, compose
- w56 AlexAsplund/Vanchor -> REJECT quota (offline GPS autopilot, no DB) ; meta, root, wf:ci.yml, compose
- E1 RESULT: 2 accepted (recruitops-agent, Shvatka); window exhausted; 2 FastAPI slots remain -> E2.

**E2 (`stars:>100 topic:sqlalchemy`, applications only)** - metadata rejects: w04 awesome-sqlalchemy (None, list), w08
globaleaks (SIZE), w20 doudizhu (None), w51 TaskFlow (None), w59 sqlalchemy-tutorial (None), w60 wtforms-sqlalchemy
(NOASSERTION). Screened 54. Libraries/ORMs/plugins/tools -> REJECT c5: aiomysql, eralchemy, sqlalchemy-continuum,
pytest-alembic, Maxteabag/sqlit (TUI), and every other screened line without a DB image (see screen log). Templates
-> REJECT c5: rafsaf/minimal-fastapi-postgres-template, seapagan/fastapi-template, modern-python/fastapi-sqlalchemy-template,
KenMwaura1/Fast-Api-example. Applications, in window order:
- w37 ilyarolf/AiogramShopBot -> ACCEPT E2 (api-postgres; FastAPI webhook + aiogram; compose postgres:18 + redis; pytest in CI without services; MIT; py3.12) ; meta, root, wf:tests.yml, compose, requirements.txt, README
- w41 JakubPluta/gymhero -> ACCEPT E2 (api-postgres; FastAPI+SQLAlchemy+Alembic; pytest via testcontainers; migrations job with postgres:16-alpine service; MIT; uv; py3.13) ; meta, root, wf:ci.yaml, compose, pyproject
- w58 jantman/biweeklybudget -> NOT E2's fill (a Flask app, MariaDB); recorded; it is E4's w26 and is filled there ; meta, root, wf:run-tox-suite.yml, tox.ini
- E2 RESULT: 2 accepted -> FastAPI extension quota met (4 of 4). E3 not needed for FastAPI.

**E3 (`stars:>100 topic:postgresql`, applications only)** - metadata rejects c1: w01 WrenAI, w06 baserow, w09 pgadmin4,
w27 remnawave bot, w35 pg_probackup, w38 temboard, w59 cryptostore (NOASSERTION), w44 envkit-releases, w60 pglast (None).
Screened 51: screened-in lines are libraries/drivers/queues/ORMs/tools (patroni, ibis, tortoise-orm, sqlit, barman,
dbos-transact-py, pgqueuer, procrastinate, pgsync, eralchemy, advanced-alchemy, pytest-postgresql, piccolo_admin,
edgy) -> REJECT c5; rafsaf template and Azure-Samples -> REJECT c5; hotosm/tasking-manager -> REJECT c6 (as in the base
log); fedspendingtransparency/usaspending-api -> REJECT c1 (CC0-1.0 is not OSI-approved) (Django app, 107 MB, postgres).
- E3 RESULT: 0 accepted (no FastAPI slot remaining anyway; no Flask application in the window).

**E4 (`stars:50..150 topic:flask`, applications with pytest in CI; DB preferred)** - metadata rejects: w09 GeoNature
(SIZE), w41 etf-national-tracker (None), w42 docker-updater (None), w43 datacube-ows, w46 shopyo, w49 flask_mab,
w57 critiquebrainz, w58 OptionsCanvas (NOASSERTION), w53 DoorOpener (None), w56 python-for-devops (None). Screened 50;
lines without root manifest or pytest workflow -> REJECT c3/c4 (screen log). Screened-in, in window order (fill
preference stated before reading: DB-backed applications first, then DB-less, both in window order):
- w03 cumbucadev/cinemaempoa -> PASS (Flask + SQLAlchemy/SQLite; uv; pytest; GPL-3.0; py3.14) -> alternate (no DB service) ; meta, root, wf:ci.yml, pyproject, tests/
- w04 salimane/flask-mvc -> REJECT c5 (boilerplate) ; screen
- w05 joseantmazonsb/linguard -> PASS (Flask WireGuard GUI; poetry; pytest; py3.7-3.9; apt wireguard) -> alternate ; meta, root, wf:latest-test.yaml
- w07 scidsg/hushline -> ACCEPT E4 #1 (Flask + Flask-SQLAlchemy on postgres:16.4 via compose; make test -> poetry run pytest; AGPL-3.0; 129 MB; py3.13) ; meta, root, wf:tests.yml, Makefile, compose, pyproject
- w12 MasoniteFramework/exceptionite, w16 vpcarlos/profyle, w18 Ambro17/slackify, w23 zfleeman/ffmpeg4discord, w24 marcoagner/Flask-QRcode, w29 guibranco/progressbar, w37 FROWNINGdev/orm-lens, w47 farahats9/sqlalchemy-celery-beat, w55 hasgeek/coaster -> REJECT c5 (libraries/extensions/tools) ; screen
- w15 eerovil/TrackLater -> PASS (Flask + Flask-SQLAlchemy file DB; pytest; MIT; py3.12) -> alternate (no DB service) ; meta, root, wf:pythonapp.yml, compose
- w25 wink-wink-wink555/MarkiNote -> REJECT c6 (AI-agent document system) + c3 (apps/ layout) ; screen
- w26 jantman/biweeklybudget -> ACCEPT E4 #2 (Flask/SQLAlchemy finance app; mariadb:10.4.7 service; tox -e py314 running pytest; AGPL-3.0; py3.14 only) ; meta, root, wf:run-tox-suite.yml, tox.ini
- w28 craws/OpenAtlas -> PASS (Flask + PostGIS via compose; pytest via docker exec; GPL-2.0; py>=3.13) -> DB-backed alternate ; meta, root, wf:starter.yaml, compose, pyproject
- w31 BlueSquare23/web-lgsm -> REJECT (game-server manager needing LGSM/system tools; no DB) ; screen
- w33 caspii/dinkydash -> PASS (Flask; postgres:17 service; pytest twice, with and without DB; MIT; py3.11; no API key in CI) -> DB-backed alternate ; meta, root, wf:test.yml, requirements
- w35 hoangsonww/AI-Agents-Orchestrator, w48 MCERQUA/OpenVoiceUI -> REJECT c6 (LLM/TTS) ; screen
- w38 ialimustufa/API -> REJECT c5 ("Making a Simple API Server", tutorial-grade) ; screen
- w45 Angrido/Lidarr-YouTube-Downloader -> REJECT (network downloader; no DB) ; screen
- E4 RESULT: 7 pass; fill = hushline + biweeklybudget (the first two DB-backed in window order); alternates in order:
  cinemaempoa, linguard, TrackLater, OpenAtlas, dinkydash. Note for the decision: dinkydash is the only passing Flask
  app with Postgres AND an interpreter inside 3.8-3.13; biweeklybudget is MariaDB + Python 3.14.

### Extension summary (optional; nothing here is frozen)

| slot | name | rule | family | build | checks (short) | commit |
|---|---|---|---|---|---|---|
| FastAPI 1 | recruitops-agent | E1 | api-postgres | pip | ci.yml pytest; compose pgvector pg16 | 1584307 |
| FastAPI 2 | shvatka | E1 | api-postgres | uv | test.yml pytest; testcontainers postgres:18.2 | 352323a |
| FastAPI 3 | aiogramshopbot | E2 | api-postgres | pip | tests.yml pytest; compose postgres:18+redis | f886de2 |
| FastAPI 4 | gymhero | E2 | api-postgres | uv | ci.yaml pytest (testcontainers) + postgres:16 migrations job | 890b0db |
| Flask 1 | hushline | E4 | web-flask | poetry | tests.yml make test (pytest) via compose postgres:16.4 | 1228e5d |
| Flask 2 | biweeklybudget | E4 | web-flask-mysql | tox | run-tox-suite.yml tox -e py314 (pytest); mariadb service | ac8870d |
| alt | cinemaempoa, linguard, tracklater, openatlas, dinkydash | E4 | web-flask | uv/poetry/pip/uv/pip | see yaml | - |

Extension shortfalls: none (4/4 FastAPI via E1+E2; 2/2 Flask via E4). Caveats to weigh: Shvatka, biweeklybudget and
cinemaempoa run on Python 3.14 (above the declared 3.8-3.13); the two E2 FastAPI apps' CI suites do not touch their
Postgres (DB is provided by compose/testcontainers, not exercised by the pytest job); biweeklybudget is MariaDB.
