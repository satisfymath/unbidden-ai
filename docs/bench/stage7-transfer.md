# Stage 7: transfer to a real application, written before the agent runs on it

## The application

**Conduit, FastAPI implementation** (`nsidnev/fastapi-realworld-example-app`, MIT), pinned at
**029eb7781c60d5f563ee8990a0cbfb79b244538c** (2022-08-21). A public reference implementation of the RealWorld spec
(a Medium-like blogging API: users, profiles, articles, tags, favorites, comments). We did not write it, it was not
built to evaluate Unbidden, and it is neither Mealie nor any of our labs.

Why it was chosen:
- its stack is inside what Unbidden supports today: Python 3 (FastAPI, asyncpg, Alembic), PostgreSQL, an OpenAPI 3
  document served by the app, docker compose;
- it runs locally and isolated (its own compose file: the app and PostgreSQL), with observable behaviour (a REST API)
  and its own checks (a pytest suite against a real PostgreSQL, the Postman/newman API spec run by its CI, style
  checks);
- its data model has relations whose reads may grow with data (comments and favorites per article), so useful,
  measurable opportunities can exist without our seeding any defect.

Limits, known before running:
- last commit in 2022; its Dockerfile pins Python 3.9.10 and Poetry 1.1: building it today may need care, and any such
  care is counted as human preparation;
- the list endpoint pages by `limit`/`offset` and reports `articlesCount`, not `total`/`count`: Unbidden's reader may
  not know the read is complete (a real transfer question, left to the run);
- authentication is a JWT in `Authorization: Token <jwt>`, obtained by logging in: a person provides a token for a
  synthetic user; Unbidden does not log in;
- writes (create article, comment, favorite) have no `Idempotency-Key` and no observable undo of the kind Unbidden
  validates: writes through the API are outside what it can safely do, and the mandate does not grant them;
- its suite needs a PostgreSQL; the lab's experiments provide one as a sidecar from the CI's own service definition.

## Human preparation (counted, not attributed to Unbidden)

Listed as it is done, with its time, in `docs/bench/stage7-transfer-prep.md`: cloning at the pinned commit; the
`.env`; a compose override binding ports to 127.0.0.1 and labelling the containers; building and starting; synthetic
data (users, articles, tags, comments, favorites: generated, no real user); a read-only database role; a token for a
synthetic user; the workspace's mandate, grants, goal and priorities; deploy steps. No connector, detector or fix for
this application is written; if Unbidden lacks a capability, it acquires it by its own mechanisms or records the block.

## Two questions, frozen before the runs

**A. Transfer, with a general goal.** The goal states what the application is for, not a defect, file or fix:
"Readers must see correct and timely counts: for every article, the number of favorites and comments the API reports
must match what is stored, and reading an article's comments must stay fast as the site grows." Unbidden must
discover, read, acquire an integration if it lacks one, compare, and act only within the mandate (it has no write
grant: acting means proposing a change with its evidence). Utility: a correct count where one was wrong, or a
measured speed-up of a read the goal names; "consistent and fast; nothing to do" is a valid result.

**B. Proactive discovery, no ticket.** From a clean workspace: accesses (the repository, the running staging, the
database read-only), priorities ("correctness, then performance of reads as data grows") and constraints (no pull
request, no merge, no write to data; experiments in the sandbox; changes only proposed), and no goal. Does Unbidden
find an opportunity by itself, explain why it matters, reproduce it before changing anything, decide (investigate,
experiment, abstain, ask for an access), and prove an improvement if one is viable? Utility: a measured improvement
with the application's checks green on both sides (L4 or better), or a justified abstention; more findings, commits
or tests are not more value.

**Versions and repetitions.** Product and harness: one commit, frozen before the first run (`docs/bench/stage7-freeze.md`).
Spark (`muse-spark-1.3`) as for every earlier stage; the local model as recorded fallback; vision and SAM off (the
goal does not ask about pages). A: x2 from a fresh workspace. B: x1, two cycles. Budget from the US$3.99 left: up to
US$2.00 for these runs, refused by the ledger beyond. Nothing about Conduit is tuned before these runs; whatever is
fixed after them is a new version, and claims of generalization would then need another application.
