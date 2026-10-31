# Stage 10: a new frozen evaluation on applications never used before

Written before any candidate was looked at (2026-10-30). Development applications (Conduit, LNbits, Spoolman,
Prefect, and fst and mealie for revalidation) are not candidates. Nothing below changes once the first candidate is
inspected; the set, the product, the harness, the models, the modes, the acceptance conditions, the oracles, the
repetitions, the budget, the time limits and the invalidation rules are frozen together before any run.

## Selection rule (fixed now)

**Source, deterministic:** GitHub's public search API, unauthenticated, query
`language:Python topic:fastapi stars:>150 pushed:>2026-05-01 archived:false`, sorted by stars, descending,
read page by page. Candidates are examined in that order; the **first three** that pass every criterion form the set.
A candidate is never skipped for any reason not listed here, and never replaced after a run.

**Criteria** (the scope v1.0 declares):
1. An OSI-approved license identified by GitHub.
2. A Python project at the repository's root (`pyproject.toml`, `requirements.txt` or `setup.py` there) whose
   server is FastAPI.
3. PostgreSQL supported as its database (in its settings, compose files or documentation).
4. Its own tests in the repository, run by a GitHub Actions workflow.
5. Runnable locally with its database only: no other external service required to start and serve its API.
6. Its API documented by OpenAPI at a standard path, with no authentication, an API key in a header, or a login
   the project's own tests perform; OAuth with an external provider excludes it.
7. At most 300 MB on GitHub.
8. Not a template, a library, a tutorial or an example collection; not built from the RealWorld/Conduit
   specification; not used by Unbidden before.

Every inspection (which files were read, for which criterion) is recorded in this document before the next
candidate is examined.

## What the harness may prepare (human preparation, counted) and what Unbidden must do

Harness: clone the release (or the default branch's head when there is no release) and pin its commit; a compose
file written by the person with the project's published image or its Dockerfile, PostgreSQL, ports on 127.0.0.1
only, no privileged container, no Docker socket, owned resources; synthetic data through the project's own API or,
where the API cannot create a kind of record, SQL written from the project's models; a read-only database role.
Unbidden: everything else (reproducing the environment, the project's checks, finding, preparing and validating
workloads, measuring, concluding, abstaining). The harness never tells Unbidden anything about the application.

## Protocol (fixed now)

As stage 9 (`bench/ecosystem/app_eval.py`), per application: **B-1** (proactive, no goal), then **A-1** (the same
general goal for every application: "Readers must see correct and timely data: every number the API reports about
stored records must agree with what is stored, and the main listings must stay fast as the data grows", read-only),
each four cycles; one declared answer a person may give after cycle 2 (adding a package registry Unbidden names).
Meta's API only (Spark), `s10-eval` envelope, US$2.00 monthly cap per workspace, each cycle at most 90 minutes.

## Outcome classes and denominators

Reported per application and in total, with explicit denominators: environment reproduced; project checks run
(scope stated); opportunities investigated; workloads valid; experiments completed; improvements verified; justified
abstentions; technical blocks; false promotions. Each outcome is one of: useful improvement verified, absence
verified, technical block, inconclusive, false promotion.

**Independent measurement** (by the harness's author, after the runs, never by Unbidden): the project's own tests as
its CI runs them; every L4 re-measured from its spec outside Unbidden (the endpoint's own SQL with `EXPLAIN ANALYZE`
on the lab data, rolled back) and its patch run against the project's tests; every consistency finding recomputed
from the API and SQL; every abstention checked against the foreign keys, indexes and listing timings on the data.

**Evaluator controls** (development, before the freeze): the A/A and irrelevant-index controls and the seven v4
cases run on the frozen product, so a run that ends blocked is never read as proof that false positives cannot occur.

**Invalidation:** a run whose harness failed, or whose product tree changed during it, is invalid and reported as
such; it is not repeated inside the evaluation. A failure that needs a correction closes this version: the fix and
any repeat are regressions.

## Freeze (2026-10-31, before the first candidate is inspected)

- **Product:** commit 0102ccb, the tree the evaluator controls passed on (7 of 7 on a quiet host,
  `stage10-controls/0102ccb-run4`; the third run's inconclusive A/A on a noisy host is kept beside it). Frozen as
  hashes: `unbidden/` tree 577c03c03025a89678495e8f5640f52d53f3aff7, `pyproject.toml` 6f1c60dd626db4358fa9a310ca9396268ae87ec9,
  `uv.lock` 9c80aa6458810a803d0695888bc95ffa269d50f9. Every evaluation run is made from a worktree whose files have
  exactly these hashes; a run on any other product is invalid.
- **Harness:** commit 0fe4ecd: `bench/ecosystem/app_eval.py` f6b87cf79e5db8e911c1f9be980ae40f0e3a89e7,
  `bench/ecosystem/cycle.py` 299991beb6bdce328b478b9a4581915d60a66b4f, `bench/ecosystem/conduit_eval.py`
  0fef07d5c0ffa5a15c7ffaa9bb55673c1e1e4608. Each selected application adds its own preparation as new files only
  (`bench/ecosystem/<app>_lab.py`, its compose file and data), recorded and counted as human preparation; no frozen
  file changes.
- **Protocol:** this document's sections above, as committed in 2f3da12 (blob 81620c54fa2ede92ef0540ac576c3d347f500fa0),
  unchanged. Models: Meta's API only (Spark, `muse-spark-1.3`, the runner's config). Budget: envelope `s10-eval`,
  US$8.50, untouched at the freeze (cumulative cap US$37.2945, spent US$24.2976).
- **Host:** the runs are measured on the same machine as the controls; the controls showed that a busy host makes the
  A/A control inconclusive, so each run records the host's load and the lab services running.

## Choice

(to be filled, in order, before any run)

**Source, read 2026-10-31:** the search as fixed, page 1 (per_page 100), total_count 305. Inspections in order;
files read through GitHub's API and raw files only (nothing cloned or run); "metadata" is the search result itself.

1. `fastapi/fastapi` — metadata (description "FastAPI framework", topic framework): a framework, criterion 8 fails.
2. `headroomlabs-ai/headroom` — tree, pyproject.toml, compose files, headroom/memory/config.py, README: storage is
   SQLite ("future: PostgreSQL"), criterion 3 fails; it is a library and proxy (README), criterion 8 fails.
3. `Zeyi-Lin/HivisionIDPhotos` — tree, requirements.txt, docker-compose: no PostgreSQL anywhere (no database),
   criterion 3 fails; no workflow runs its tests, criterion 4 fails.
4. `Evil0ctal/Douyin_TikTok_Download_API` — tree, pyproject.toml, docker/compose.yml, src/dtk/core/config.py,
   README: PostgreSQL (TimescaleDB) and Redis, the api service depends on both ("Nothing beyond Postgres and Redis is
   required"), criterion 5 fails.
5. `fastapi/sqlmodel` — metadata ("SQL databases in Python", an ORM): a library, criterion 8 fails.
6. `coleifer/peewee` — metadata ("a small, expressive orm"): a library, criterion 8 fails.
7. `QuentinFuxa/WhisperLiveKit` — tree, pyproject.toml, compose: no PostgreSQL (no database), criterion 3 fails.
8. `polarsource/polar` — metadata: 555 MB on GitHub, criterion 7 fails.
9. `pycaret/pycaret` — metadata: license NOASSERTION (not identified by GitHub), criterion 1 fails.
10. `vastsa/FileCodeBox` — tree, pyproject.toml, requirements.txt, core/database.py: SQLite only
    (`tortoise.backends.sqlite`, no PostgreSQL driver), criterion 3 fails.
11. `nonebot/nonebot2` — metadata ("asynchronous multi-platform chatbot framework"): a framework, criterion 8 fails.
12. `xerrors/Yuxi` — tree, compose files: no manifest at the repository's root (the backend is in `backend/`),
    criterion 2 fails; it also needs Milvus, Neo4j, etcd and Redis, criterion 5 fails.
13. `dramaclaw/dramaclaw` — metadata: license NOASSERTION, criterion 1 fails (and 696 MB, criterion 7).
14. `shy3130/tick-stock-panel` — tree: no manifest at the root (backend/), criterion 2 fails; DuckDB, no PostgreSQL
    in its files, criterion 3 fails.
15. `fastapi-users/fastapi-users` — metadata ("ready-to-use users management for FastAPI"): a library, criterion 8.
16. `SenteLabsAI/OpenExecutive` — tree: no manifest at the root (packages/), criterion 2 fails.
17. `remsky/Kokoro-FastAPI` — tree, pyproject.toml, compose files: a text-to-speech server with no database,
    criterion 3 fails.
18. `AhmadHassan-BTed/AutoSwarm-Shadow-Adapter` — tree, pyproject.toml: no PostgreSQL in its files, criterion 3 fails.
19. `IBM/mcp-context-forge` — metadata: 444 MB, criterion 7 fails.
20. `strawberry-graphql/strawberry` — metadata ("a GraphQL library"): a library, criterion 8 fails.
21. `pydantic/logfire` — metadata (an observability SDK, "logfire" client): a library, criterion 8 fails.
22. `dynaconf/dynaconf` — metadata ("configuration management"): a library, criterion 8 fails.
23. `arvin341az-glitch/RVG` — metadata: license NOASSERTION, criterion 1 fails.
24. `datamodel-code-generator/datamodel-code-generator` — metadata (a code generator): a library/tool, criterion 8.
25. `Lightning-AI/LitServe` — metadata ("a minimal Python framework" for inference servers): criterion 8 fails.
26. `TracecatHQ/tracecat` — tree, pyproject.toml, docker-compose.yml and docker-compose.lite.yml: even the lite
    stack needs Temporal (and the full one MinIO and Redis), criterion 5 fails.
27. `Soju06/codex-lb` — tree, pyproject.toml, docker-compose.yml, app/main.py, app/core/config/settings.py,
    app/core/auth/dashboard_mode.py, .github/workflows/ci.yml, Makefile, README. **Passes; selected (1 of 3).**
    1: MIT. 2: pyproject.toml at the root, FastAPI (`app = FastAPI(...)` in app/main.py). 3: PostgreSQL supported
    (`CODEX_LB_DATABASE_URL`; README "PostgreSQL is optional"; compose runs postgres). 4: 524 test files under tests/,
    run by ci.yml's "Tests (pytest, ...)" jobs (`make test-unit`, `make test-integration-core-*`). 5: compose holds
    only PostgreSQL; the upstream it proxies (OpenAI) is needed for proxying, not to start and serve its own API (judged
    from the settings' degraded-startup handling; to be confirmed when prepared). 6: OpenAPI at FastAPI's default
    path (not disabled); dashboard auth is a password the project's tests use, with a `disabled` mode, and API keys in
    a header for proxy routes; the OpenAI OAuth only links ChatGPT accounts, not access to its API (judged). 7: 80 MB.
    8: an application.
28. `lxf746/any-auto-register` — tree, requirements.txt, workflows: no PostgreSQL in its files, criterion 3 fails;
    no workflow runs its tests, criterion 4 fails.
29. `ml-tooling/opyrator` — metadata (turns functions into microservices): a library/tool, criterion 8 fails.
30. `tiangolo/uvicorn-gunicorn-fastapi-docker` — metadata (a Docker image): not an application, criterion 8 fails.
31. `smithyhq/sqladmin` — metadata ("SQLAlchemy Admin for FastAPI"): a library, criterion 8 fails.
32. `s3rius/FastAPI-template` — metadata (a cookiecutter template): criterion 8 fails.
33. `3441293738/creatorhub` — metadata: no license identified, criterion 1 fails.
34. `the-momentum/open-wearables` — tree, compose: no manifest at the root (backend/), criterion 2 fails; it also
    needs Redis and Svix, criterion 5 fails.
35. `wassim249/fastapi-langgraph-agent-production-ready-template` — metadata (a template): criterion 8 fails.
36. `supabase/supabase-py` — metadata (a client library): criterion 8 fails.
37. `fastapi-practices/fastapi-best-architecture` — metadata (topic fastapi-template, an architecture template):
    criterion 8 fails.
38. `jwadow/kiro-gateway` — tree, requirements.txt: no PostgreSQL (no database), criterion 3 fails.
39. `TNT-Likely/PanWatch` — tree, pyproject.toml, requirements*.txt, src/platform/persistence/database.py: SQLite
    only (no PostgreSQL driver), criterion 3 fails.
40. `ithtelab/workbuddy-manager` — metadata: license NOASSERTION, criterion 1 fails.
41. `widgetti/solara` — metadata ("a pure Python, React-style framework"): criterion 8 fails.
42. `Kludex/mangum` — metadata (AWS Lambda support for ASGI): a library, criterion 8 fails.
43. `Anil-matcha/open-agent-email` — metadata: 414 MB, criterion 7 fails.
44. `benavlabs/FastAPI-boilerplate` — metadata (a boilerplate): criterion 8 fails.
45. `BetaStreetOmnis/xhs_ai_publisher` — tree, requirements.txt: no PostgreSQL (no database), criterion 3 fails.
46. `laurentS/slowapi` — metadata (a rate limiter): a library, criterion 8 fails.
47. `openapi-generators/openapi-python-client` — metadata (a client generator): a library/tool, criterion 8 fails.
48. `vstorm-co/full-stack-ai-agent-template` — metadata (an app generator, a template): criterion 8 fails.
49. `piccolo-orm/piccolo` — metadata (an ORM): a library, criterion 8 fails.
50. `pmh1314520/WebRPA` — metadata: license NOASSERTION, criterion 1 fails.
51. `ormar-orm/ormar` — metadata (an ORM): a library, criterion 8 fails.
52. `guillevc/yubal` — tree, pyproject.toml (a workspace root; FastAPI not in it), compose: no PostgreSQL, criterion 3
    fails.
53. `uriyyo/fastapi-pagination` — metadata (a pagination library): criterion 8 fails.
54. `drmingler/docling-api` — tree, pyproject.toml, compose: no PostgreSQL; Redis and Celery, criteria 3 and 5 fail.
55. `pixeltable/pixeltable` — metadata: 392 MB, criterion 7 fails.
56. `benavlabs/fastcrud` — metadata (a CRUD package): a library, criterion 8 fails.
57. `fim-ai/fim-one` — metadata: license NOASSERTION, criterion 1 fails.
58. `insistence/RuoYi-FastAPI` — tree, compose files: no manifest at the root (ruoyi-fastapi-backend/), criterion 2
    fails; Redis in its stacks, criterion 5 fails; a general admin framework (README), criterion 8 fails.
59. `akfamily/aktools` — tree, pyproject.toml: an HTTP front of a data library, no PostgreSQL, criterion 3 fails.
60. `teamhide/fastapi-boilerplate` — metadata: no license identified (criterion 1), a boilerplate (criterion 8).
61. `devnen/Chatterbox-TTS-Server` — tree, requirements.txt, compose: a TTS server with no database, criterion 3 fails.
62. `trallnag/prometheus-fastapi-instrumentator` — metadata (instrumentation): a library, criterion 8 fails.
63. `transmute-app/transmute` — metadata: 433 MB, criterion 7 fails.
64. `koxudaxi/fastapi-code-generator` — metadata (a code generator): criterion 8 fails.
65. `Amm1rr/WebAI-to-API` — tree, manifests, compose: no PostgreSQL (no database), criterion 3 fails.
66. `slackapi/bolt-python` — metadata (Slack's framework): criterion 8 fails.
67. `aegra/aegra` — tree, pyproject.toml, docker-compose.yml, libs/aegra-api/src/aegra_api/{settings,main}.py,
    .github/workflows/ci.yml, README. **Passes; selected (2 of 3).** 1: Apache-2.0. 2: pyproject.toml at the root, a
    uv workspace (`members = ["libs/*"]`) whose server, libs/aegra-api, is FastAPI (judged a Python project at the
    root, unlike the candidates with no root manifest at all). 3: PostgreSQL (pgvector image; asyncpg settings).
    4: libs/aegra-api/tests, run by ci.yml ("Run tests with pytest"). 5: compose adds Redis, but its broker is off by
    default (`REDIS_BROKER_ENABLED: bool = False`); model keys are for running agents, not to start and serve the API
    (judged; to be confirmed when prepared). 6: OpenAPI at FastAPI's default path (`docs_url="/docs"`), auth
    `AUTH_TYPE = "noop"` by default. 7: 4 MB. 8: an application (a LangGraph Platform alternative); its "templates" are
    of the agents it creates, not the repository.
68. `SalesforceAIResearch/enterprise-deep-research` — tree, manifests: no PostgreSQL (no database), criterion 3 fails.
69. `larlarua/AutoCVE` — tree, compose files: no manifest at the root (backend/), criterion 2 fails; no workflow
    runs its tests, criterion 4 fails.
70. `yezz123/authx` — metadata (an authentication package): a library, criterion 8 fails.
71. `atpuxiner/fastapi-scaff` — metadata (a scaffold): criterion 8 fails.
72. `developmentseed/titiler` — tree, pyproject.toml, compose: a tile server with no database, criterion 3 fails
    (and a set of packages to build servers with, criterion 8).
73. `art049/odmantic` — metadata (a MongoDB ODM): a library, criterion 8 fails.
74. `Ricky-7-Yan/intelligent-audit-system` — metadata: no license identified, criterion 1 fails.
75. `asdfghj1237890/WebVideo2NAS` — metadata: license NOASSERTION, criterion 1 fails.
76. `tsukumijima/KonomiTV` — tree: no manifest at the root (server/), criterion 2 fails; no PostgreSQL (Tortoise on
    SQLite), criterion 3 fails.
77. `Finrandojin/alexandria-audiobook` — tree: no manifest at the root, criterion 2 fails; no database, criterion 3.
78. `TypeError/secure` — metadata (security headers): a library, criterion 8 fails.
79. `jowilf/starlette-admin` — metadata (an admin interface): a library, criterion 8 fails.
80. `beizhu-1209/AIHelms` — tree, compose: no manifest at the root, criterion 2 fails; no workflow runs its tests,
    criterion 4 fails.
81. `dunossauro/fastapi-do-zero` — metadata: no license identified (criterion 1), a course (criterion 8).
82. `sabuhish/fastapi-mail` — metadata (a mail package): a library, criterion 8 fails.
83. `bitcart/bitcart` — tree, pyproject.toml, api/settings.py, .github/workflows/ci.yml, README: Redis is part of
    the application (api/redis.py, REDIS_* settings; the CI's tests start a Redis service beside PostgreSQL), and
    its coin daemons are separate services, criterion 5 fails.
84. `CloakHQ/CloakBrowser-Manager` — metadata: license NOASSERTION, criterion 1 fails.
85. `weiwill88/Local_Pdf_Chat_RAG` — tree, requirements.txt: no PostgreSQL (FAISS, no database), criterion 3 fails.
86. `Pipelex/pipelex` — metadata: license NOASSERTION, criterion 1 fails.
87. `alikon-art/DeterminFlow` — tree, pyproject.toml, requirements.txt, README: no PostgreSQL driver or setting,
    criterion 3 fails.
88. `JMS1717/8mb.local` — metadata: license NOASSERTION, criterion 1 fails.
89. `feldroy/air` — metadata (a web framework on FastAPI): criterion 8 fails.
90. `LibreChat-AI/rag-api` — tree, requirements.txt, docker-compose.yaml, app/config.py, app/middleware.py,
    .github/workflows/ci.yml, README. **Passes; selected (3 of 3).** 1: MIT. 2: requirements.txt at the root,
    FastAPI. 3: PostgreSQL with pgvector, the default `VECTOR_DB_TYPE` (MongoDB Atlas is an alternative). 4: tests/,
    run by ci.yml (pytest). 5: compose holds only the pgvector database; the embeddings provider (OpenAI by default,
    or a local Hugging Face model) is called when documents are embedded or queried, not to start and serve its API
    (judged; to be confirmed when prepared). 6: `/openapi.json` and `/docs` exempt from its middleware; with no
    `JWT_SECRET` the middleware lets every request through (no authentication). 7: 30 MB. 8: an application (the RAG
    service of LibreChat), not a template, library or tutorial; not used by Unbidden before.

**The set (first three that pass every criterion, in the search's order):** 1 `Soju06/codex-lb`, 2 `aegra/aegra`,
3 `LibreChat-AI/rag-api`. Candidates 91-305 were not examined. The set is not changed after any run.
