# Unbidden 0.18.0, experimental candidate: the terminal app on the product branch, not 1.0

## 0.18.8 (2026-11-04): the web workspace wears the brand sheet

- **The dashboard is monochrome in its source.** Deep black and bone white replace petrol blue and turquoise. Amber,
  red and green keep their meaning, desaturated. Primary buttons are solid bone; code highlighting is grey.
- **The real mark.** A fine open ring with a separate dot, in the logo and the favicon, and the `UNBiDDEN` wordmark.
  The demo video recorded these same values injected at capture time; the product now carries them itself.

## 0.18.7 (2026-11-04): a crash fix and its regression test the team's CI can run

- **The robustness lab puts its candidate through the team's formatter.** rich, final pass on 0.18.6: two crash
  fixes found by the probe (`ZeroDivisionError` and `IndexError` in `_split_text`) were red on `black --check` in
  every CI cell, only for the regression test file they add. The formatting step the fix lab has (0.18.6) is now one
  function both labs use.
- **Every round starts from the measured revision, whatever runs it.** 0.18.6 reset the tree between rounds only when
  the CI job's own test step ran; sqlmodel's `mkdir coverage` comes from its CI steps as Unbidden translates them, so
  rounds 2 and 3 still failed on "File exists" and its security bumps were declined again. Real check: sqlmodel's
  268 tests run in all three rounds.
- **Without Hypothesis in the project, the regression test is pinned to the falsifying example.** python-mss, the
  same pass: the crash fix's regression test imported Hypothesis, which the project does not install, and failed to
  import in every CI cell. When no manifest, lock or tox file names Hypothesis, the property test travels as a plain
  test whose arguments default to the example Hypothesis found (decorators and imports gone); when that cannot be
  done, the fix is not proposed and the reason is kept.

## 0.18.6 (2026-11-04): the labs' type checks and formatter run where the project is installed

- **The fix lab and the performance lab run mypy and pyright in Unbidden's own environment.** reader, final pass on
  0.18.5: reproducing its lint findings, the fix lab ran mypy in the CI job's image (no `/deps/.venv`), so every
  fix ended "cannot judge: incomplete reports from mypy". A tool that reads `/deps/.venv` now runs beside, in
  Unbidden's own environment of the same revision (0.18.3); the others still run in the CI job's.
- **A `uv.lock` with a git source relocks.** harlequin, the same pass: eight security bumps (aiohttp's eight
  advisories among them) stopped at "uv lock failed", the reason lost; uv had said git was missing for a git source
  (pytest-textual-snapshot from GitHub). The relock image now has git, and a failure keeps uv's own `error:` and
  `cause:` lines. Real check: aiohttp relocked to 3.14.4.
- **A team CI that never runs on pull requests is no CI to wait for.** dooit, the same pass: its workflows run
  only on pushes to `develop` (the `pull_request` trigger commented out), so the agent waited for checks that would
  never come and both security pull requests stayed open. When no workflow at the measured commit runs on a pull
  request into the base (`pull_request`, `pull_request_target`, or a `push` that matches the branch), the merge rests
  on the lab's evidence, as for a repository with no workflow; an unreadable workflow is assumed to run.
- **Each round of the team's own test step starts from the measured revision.** sqlmodel, the same pass: its CI
  step runs `mkdir coverage`; rounds 2 and 3 failed on "File exists" in the tree round 1 left, and all five
  security bumps (their advisories gone) were declined as infrastructure failures.
- **The candidate goes through the team's formatter and type check from the installed project.** rich, the same
  pass: two pull requests red on `black --check` in every CI cell, with the note "black: not in the project's
  environment": the formatter ran in the CI job's image, where it is not on the PATH.

## 0.18.5 (2026-11-04): standing advisories are not new with a bump; findings relative to the repository

- **The base's advisories are read, every package's.** marshmallow, final pass on 0.18.4: certifi's bump removed its
  advisories and the suite passed 3/3, yet it was declined because virtualenv's 25 advisories, standing before the
  bump, were counted as new with it. The comparison set was never filled; the dependency lab now reads the base's
  installed packages (Unbidden's own environment) and their advisories before judging the candidate.
- **Findings are relative to the repository in a CI job's workspace.** rich: ruff ran at the CI job's workspace path
  and reported absolute paths there (`…/ci-env/<key>/ws/rich/console.py`); the model's answer naming one was refused
  as unsafe, so no lint or type fix could land in any repository measured through its CI job. The workspace prefix
  is now removed from every finding.
- **Why the candidate's packages could not be read is said.** pyjwt: pytest's fix (9.0.3) needs Python 3.10, and
  pyjwt supports 3.9; the verdict now carries the install's own reason instead of only "nothing is claimed".

## 0.18.4 (2026-11-04): security bumps the final pass could not finish

- **A requirement in `pyproject.toml` is bumped.** pyjwt: pytest's advisory was found and its fix known, but
  "bumping a dependency in pyproject.toml is not supported yet". Every requirement string naming the package
  (dependencies, optional dependencies, dependency groups) is raised to the fixed version, extras and markers kept,
  an upper bound kept when the fixed version still satisfies it (`pytest>=8.4.2,<9.0.0` becomes `pytest>=9.0.3`). A
  package the file does not name, without a lock, is declared, not guessed.
- **The candidate's packages are read from Unbidden's own environment.** marshmallow: certifi's advisories were gone
  and its 1192 tests passed 3/3, yet "no proven fix": the candidate's installed packages were read from the CI job's
  image, which has no `/deps/.venv`, and an unread list declined silently. Now read from Unbidden's own environment
  (0.18.3); unread is said in the verdict.
- **A `uv.lock` is re-resolved from the whole tree.** sqlmodel: five advisories with known fixes (anyio, black and
  others) stopped at "uv lock --upgrade-package failed": only the manifests were copied, and its build backend (pdm)
  needs the licence file and the package to compute its metadata. Real check: anyio relocked to 4.14.2.
- **The robustness lab's reproduction runs where pytest is.** The same cause would have stopped every crash the probe
  finds from being reproduced beside a CI job's environment.

## 0.18.3 (2026-11-04): beside the CI job's environment, Unbidden's own

- **Types, advisories and robustness probes work where the team's CI job prepares the environment.** The final
  pass's first libraries ended with nothing to propose: the CI job's Python keeps the project where the job wants it
  (marshmallow: tox's own environment), so the robustness probe found no pytest, mypy no `/deps/.venv`, and the
  advisories could not list the installed packages — silently, on every repository measured through its CI job since
  0.16.0. Unbidden now installs its own environment of the same revision beside it: the team's checks still run in
  the CI job's environment, while mypy, pyright, the advisories and the probe use Unbidden's. When that install
  fails, it is said. Real check, marshmallow: mypy complete (3 findings), advisories complete (29), 6 opportunities
  opened where there were none; the probe runs (4 property tests).

## 0.18.2 (2026-11-04): a merge needs no running stack

- **An incomplete reconnaissance refuses only a start that may deploy.** The final pass's first minutes: sqlmodel, a
  library whose compose file serves its tests, was refused at `unbidden start` ("incomplete: stack down, postgres
  unread") although its mandate allowed merges and denied deploys. A merge on the team's green CI needs no running
  stack; a deploy does. With deploys denied the incomplete recon is now a warning; with deploys allowed it still
  refuses.

## 0.18.1 (2026-11-04): a tool beside the application is never its health; the development runs as evidence

- **Health on the application's own port.** misago's bring-up took mailpit's web page (`/` on its 8025) for the
  forum's health. The candidates for health are now the services built from the repository first, then the rest; a
  database, a mail catcher, a database console or a tracing UI is never one. Real check: misago's health is now
  `/login` on misago's own port.
- **The development runs, kept as evidence** (`docs/bench/campaign13/DEV-EVIDENCE.md`, `dev-evidence.json`): 23
  corpus repositories exercised while 0.16.0 to 0.18.0 were built; 15 team suites pass under Unbidden's measurement
  (18,734 tests); 3 apps brought up by Unbidden itself, 2 rollback drills passed; 1 L5 by verified deploy (fst);
  US$0.34 of model spend. Failures and declared repositories listed with the rest.

## 0.18.0 (2026-11-04): Unbidden brings an app up by itself, L5 beyond latency, every model answer kept

What a large autonomous run over many repositories needs, proven on a rehearsal before it.

- **`unbidden host up | down | status`** (`operate/bringup.py`): the application brought up from the repository's
  own compose file, rendered by Docker Compose with the repository's example env values and generated secrets
  (example placeholders never used), host ports remapped to free local ones, fixed container names dropped, an
  isolated project; migrations in the application's own service when the database is empty (alembic, Django,
  Flask-Migrate); synthetic rows from the database's own catalog; the health URL found (a documented OpenAPI health
  route first, then the usual paths, Django's admin login, local TLS proxies); the deploy steps written as this same
  command, the probe interval at 1 s, the reconnaissance settled, and the rollback drill run against the latest
  commit with the same migrations. Gated by `operations.self_host` (`auto`: autonomous, or a person's `--yes`).
- **L5 beyond latency**: a security, quality or correctness change reaches L5 by a *verified deploy*
  (`verified-deploy-v1`): the deploy containing the merge is healthy, no endpoint fails more, both deploys are
  attributable, and for a security fix the fixed version is what the running container holds. It claims no measured
  effect and is kept apart from measured L5 everywhere.
- **Evidence**: every model call, local or remote, leaves a redacted transcript (request as sent, answer, tokens,
  cost); `unbidden export` writes a workspace's events, decisions, experiments, verdicts, proposals, deployments,
  transcripts and its own spend rows as JSONL with a manifest of hashes, refused if the secret scanner finds anything.
- **Stale pull requests**: when a merge moves the base, an open pull request measured on the old base is closed and
  its opportunity opened again at the new head, so it is measured and proposed afresh.
- **CI-job environment**: the tests run in the environment their last test step saw (codex-lb sets up bun between
  two test steps); the map probes Flask routes and a self-hosted health route on the service's port.
- **Harness** (`bench/campaign13`): copies `c13-<name>` keep the team's test workflows and drop what publishes and
  Dependabot's config; Level B is parallel-safe (ports per worker, locked summaries); `run_final` schedules N
  workers; apps without a hand lab use `unbidden host up`; libraries merge on green CI with nothing deployed; every
  run's export is kept; the report joins A and B per repository and compares with campaign 12 with Wilson intervals.

Rehearsal (US$0.33 from s13-dev, autonomous, frontier models only):

| Repository | What Unbidden did on its own |
|---|---|
| fst | found dnspython 2.8.0's advisory, bumped it to 2.9.0, the copy's CI green, merged, deployed: **L5 by verified deploy** (security); its index proposal (GET /api/v1/items/ 18.3 → 5.9 ms) went stale when the base moved, which 0.18.0 now measures again |
| rich | four lint findings declined: the team's CI runs ruff the same way and passes (Unbidden's environment, not the code's): no pull request, correctly |
| codex-lb | brought up by itself (FastAPI, 86 s), rollback drill passed, autonomous; its CI test job then lacked bun, a 0.17.1 regression fixed here: 6422 tests pass again (pyjwt 476, unchanged) |

Real bring-ups: codex-lb (FastAPI), misago (Django, drill passed), TimeTracker (Flask behind nginx/TLS: up,
healthy, 500 users and 20000 activities seeded; drill declared, its head adds a migration).

## 0.17.1 (2026-11-04): three regressions of the CI-job environment fixed

Level A on 0.16.0 found three repositories that passed with 0.15.0 and stopped running. All three were in how the
measurement used what the team's job prepared, not in the repositories:

- **A step without a name, or with an expression in its name**, is found as act shows it, with the expressions
  resolved (marshmallow: `run: uv run tox -e ${{ matrix.tox }}` shown as `uv run tox -e py310`; pyjwt: `name: Run tox
  targets for ${{ matrix.python-version }}`). Before, no test step was found and Unbidden's own plan ran instead.
- **The tests run in the environment their first step saw**, not the job's last: pyjwt switches to Python 3.9 after
  its tests to combine coverage, and the final PATH found a Python without the tests' packages.
- timetracker was already fixed by 0.17.0 (its services on localhost).

| Repository | 0.15.0 | 0.16.0 | 0.17.1 |
|---|---|---|---|
| marshmallow | passed, 1192 | did not run | passed, 1192 |
| pyjwt | passed, 476 | did not run | passed, 476 |
| timetracker | 560 run, failures | did not run | its CI's tests: 169 of 169 pass |
| humanize (control) | did not run | passed, 878 | passed, 878 |

## 0.17.0 (2026-11-03): the team's failing tests repaired, when its own CI fails them too

David's rule: when Unbidden did its part well and the tests still fail because of the repository, and the
repository's own CI fails them too, Unbidden may repair them (`lab/repair.py`).

- **When it opens**: the project's checks fail named tests here, and the team's CI fails the same way: its test job,
  run here as GitHub runs it, failed at a test step; or its CI on GitHub is red and not contradicted here. A green CI,
  or the job's tests passing here, means the environment is Unbidden's: nothing opens. A failure whose report names
  a missing piece of the environment (a browser, an executable, a service, a module, the network) is never repaired.
- **What it proves**: only tests failing in 3 of 3 base rounds are targeted (a flaky test is another opportunity).
  The model sees the failures, the failing tests and the code their tracebacks pass through, or where what they call
  is defined; whole files, or excerpts when the mandate's per-call cap is smaller. A change to a test or a conftest,
  a skip, an xfail, a suppression or a new exception handler is refused and the model told why. Accepted when every
  targeted test passes in 3 of 3 rounds and the team's suite shows no regression; metric `failing_tests`
  (correctness); the proposal says why the failure was the repository's.
- **The team's CI job, more of them prepared** (archery, MySQL and Redis): steps that drive the host's Docker are
  left out and said; a service's fixed container name is dropped; a fixed host port is kept when free (act runs the
  job on the host's network, as GitHub does) and left to Docker, and said, when taken; at measurement the job's
  services answer on localhost; the runner image has the MySQL, Postgres and Redis clients. Archery: 1521 tests pass
  (before: blocked).
- A blocked environment's error is kept by both ends, the installer's first error first (P3-12).

Measured: on real repositories the rule opened nothing (timetracker 169/169 pass, archery 1521 pass, rdflib names no
test, recruitops-agent's red CI is its runner's); a seeded defect in a humanize copy was repaired with the exact
inverse change, L4, US$0.007.

## 0.16.0 (2026-11-03): the environment the team's own CI job prepares

Campaign 13 changed course here (`docs/ROAD-TO-1.0.md` §3, dimension 2). Unbidden used to reconstruct a project's
CI job: read the workflow, drop its actions, build its own image with a guessed toolset, strip lines, run offline.
Every repository broke a different assumption and each fix only showed the next one. Now the team's own test job
runs once, as GitHub runs it, and what it prepared is what everything is measured in (`sandbox/ci_env.py`).

- **Prepare**: the test job (found by the team's own naming across the workflows that run on push or pull
  request; else the CI plan's choice) runs through `act` in a GitHub-runner-like image, with the network: its actions
  (setup-python, setup-uv, setup-task, caches), its `env:`, its service containers. Nothing else runs: other jobs,
  publishing steps (coverage uploads, releases, deploys, pushes; installing such a tool is not publishing), the
  host's Docker socket, secrets. One Linux matrix combination is written into the job; conditions on other jobs are
  lifted; fixed host ports of services are dropped (they collided with this machine's own databases).
- **Keep**: the job's container is committed with its workspace (virtualenvs, `.tox`, `node_modules`), the step
  scripts act wrote (GitHub expressions already resolved) and a layer with Unbidden's pinned analyzers; cached per
  commit, job and filtered workflow.
- **Measure**: the job's own test steps, verbatim, offline, at the job's workspace path, with a runner's size
  (4 CPUs, 8 GB). A run that stopped for something the network would have given is rerun with the network and said
  so. Without `act`, without a test job, with a self-hosted or non-Linux job, or when the job failed before its
  tests, Unbidden's own image is used and the reason recorded on it.
- **When**: mandate `egress.ci_environment`, `auto` (the default: allowed in autonomous mode), `allow` or `deny`.
  `doctor` lists `act` as optional.

Measured on campaign 12's corpus (US$0, no model call), the project's checks through this path:

| Repository | Campaign 12 | 0.16.0 |
|---|---|---|
| humanize | environment failure (`msgfmt`) | passed, 878 tests |
| graphtage | environment failure (`make`) | passed, 289 |
| oauthlib | blocked (requirements include) | passed, 902 |
| codex-lb | 30 tests could not run (`git`) | passed, 6422 |
| harlequin | blocked (git dependency) | 2203 of 2214 pass (the failures read a workflow the campaign copy removed) |
| traefik-manager | environment failure | 2192 run (its own suite is nondeterministic: 0 to 50 failures run to run) |
| pipx | crash (TOML date) | 2224 run, 50 failures (tests that install packages) |
| timetracker | pytest-xdist crash | its CI's quick tests: 166 of 169 pass |
| rich, fst | passed | passed, 981 and 58 |
| rdflib | environment failure (`task`) | prepared; its `task gha:validate` fails in its own job too, under study |
| mediacms, conduit, mimirq | — | not prepared by their CI: tests inside their own compose (next), CI broken upstream (ubuntu-18.04, Poetry 1.1.12), a self-hosted runner |

Also: an alias that keeps a redefined test is not a fix (rich's F811 pull requests); the message for missing
measurement preconditions reads correctly; the snapshot's repository runs no git maintenance.

## 0.15.0 (2026-11-03): the environment funnel; the campaign 13 harness

Campaign 13, work stream 7 (`docs/ROAD-TO-1.0.md` §3, dimension 2: the project's checks reproduced), and the harness
of the final pass.

- **A test plan without the documentation build**: a line that only builds docs (`sphinx-build`, `mkdocs build`,
  `make html`/`docs`) is left out of the CI's test plan and said in its notes. graphtage, blocked in campaign 12 at
  `make: command not found` and then at `sphinx-build`, now reproduces its checks: 289 tests, passed.
- **A repository in the snapshot**: before a suite runs, the snapshot gets one commit of its tracked files (the
  image's links excluded), and git trusts it inside the sandbox, for tests that ask git about their checkout
  (codex-lb: `git ls-files`, `git grep`).
- **The runner's home, user and locale**: `/home/runner` is writable in the sandbox; the image has a passwd entry for
  uid 1000, `LANG`/`LC_ALL` C.UTF-8, and en_US.UTF-8 generated when Debian's `locales` is allowed. harlequin, blocked
  in campaign 12 and then failing on `en_US.UTF-8`, now passes its checks with Debian allowed.
- **Coverage flags**: a round that pytest stops at "unrecognized arguments: --cov" (the team's coverage plugin is
  not installed here) runs again without them, said in the record (python-mss).
- **Causes named**: a user switch (`su`/`sudo`) and a name that did not resolve are the environment's, said as such
  (dinkydash, pipx).
- **The base suite once per commit**: the fix lab reuses the base rounds for the same commit, plan and image
  (misago: 58 minutes per side were spent again by each experiment).
- **The campaign 13 harness** (`bench/campaign13/`): the final pass's mandate with every permission, the agent's
  questions answered only by the protocol's table and each answer recorded, cycles that end on the product's idle
  signal.

## 0.14.1 (2026-11-03): a deploy's failed requests are judged like its latency

Campaign 13, work stream 4 (class "reliability", `docs/ROAD-TO-1.0.md` §2). After a deploy, each probed endpoint's
share of failed requests (5xx or no answer) is compared with the previous deploy: lower or higher only when the 95%
Wilson intervals do not overlap over at least 100 requests per side (`observe/impact.judge_errors`). Until now
errors only decided an outage. A proposal whose claim is correctness or reliability is judged by the failures it was
meant to remove, so a fix reaches L5 (and L6 when it holds) the way a speed-up does; a speed-up is still judged by
latency. The class comes from the verdict's typed measurement (0.13.0).

## 0.14.0 (2026-11-03): known vulnerabilities, and a dependency bump proven like any other change

Campaign 13, work stream 5 (`docs/ROAD-TO-1.0.md` §2, class "security and dependencies").

- **Known vulnerabilities in what the project installs**: after the project's own tools, a scan lists the
  distributions installed in the dependency image (offline, inside the sandbox) and looks each one up in PyPI's JSON
  API, whose advisories come from the Python advisory database and OSV. It runs only when the mandate lists
  `pypi.org` among its package registries. Each vulnerable package is one opportunity (category `security`), titled
  "requests 2.31.0: 6 known vulnerabilities, fixed in 2.33.0", with the lowest version that fixes every advisory that
  has a fix; advisories with no published fix are kept and said apart. A package PyPI does not publish (the
  project's own) is not a failed lookup.
- **The dependency lab** (`lab/deps.py`): the bump is written the way the team keeps its dependencies: a pin in a
  requirements file rewritten (or a transitive package constrained), or `uv.lock` re-resolved with
  `uv lock --upgrade-package` in a build container, the only place that reaches a registry. The candidate's
  dependency image is built from a scratch commit (removed afterwards), the advisories are read again, and the
  team's suite runs on both sides. Proven when the targeted advisories are gone, none is new, and no test regressed;
  the claim is `advisories: N → 0`. Pull requests are titled "security: bump dnspython 2.8.0 → 2.9.0". Poetry locks
  and packages with no published fix are declared, not guessed.
- **Verified for real** on a copy of fst: 80 installed packages looked up; dnspython 2.8.0 carried
  GHSA-45c3-73f7-pv4m; `uv.lock` re-resolved to 2.9.0; the candidate's image built; the suite green on both sides;
  the advisory gone; L4. On misago, 19 of 77 installed packages have known advisories.

## 0.13.0 (2026-11-03): every stop is retried, asked or declared; the claim is typed; the team's type check

Campaign 13 (`docs/ROAD-TO-1.0.md`), work streams 1, 2 and the first part of 6.

**Blocks and questions.** A stop is now one of three things, by its kind: a service that did not answer is retried
up to six times with backoff; something a person can grant becomes a question with options and the work waits for
the answer; something nobody can grant here is declared at once and not retried at the same commit (an error
Unbidden does not recognise keeps the usual retries). New questions: the monthly cap raised from a stopped job, the
machine's spend authorization (`unbidden spend`, never changed by the agent), the kill switch (resume), a refused
connection credential, the rollback drill (asked right after deploy steps are adopted; answering queues it for the
agent), and approving a capability the forge built (asked when it waits; approving admits it and runs what waited).
`unbidden status --json` lists open questions and blocks and says `idle` when only housekeeping is due. A scripted
setup that already granted the database counts it as granted in the reconnaissance.

**The claim, typed.** Every verdict carries its measurements (`contracts/metric.py`: metric, unit, direction,
threshold, source; base, head, effect, interval, p): request latency, the project's own tool's findings, the
reproducing test. Pull requests open with that claim, and their last line says what the mandate will do: merged once
the team's CI is green on the exact commit, or left to a person (campaign 12 merged pull requests that said "a person
decides"). The perf criteria line reads perf-v4; a perf-v4 verdict is no longer listed as pending revalidation.
Priorities count by the words they use ("performance of reads as data grows" now boosts performance); reliability
and dependencies are valued categories.

**The team's type check.** A candidate goes through the mypy or pyright command the CI runs (rich: `make typecheck`)
on the base once per commit and on the candidate, and is rejected with that feedback when it adds errors.

## 0.12.9 (2026-11-03): campaign 12's fixes on main; the spend question raises the cap that is checked; the road to 1.0

Campaign 12 (installed product on 39 repositories, real Meta models, branch `feat/64-campaign`) fixed general
defects on a frozen branch; they are ported here with their tests:
- a `pyproject.toml` with TOML dates no longer crashes `doctor`, `scan` and every job (`observe/stack.py`);
- `-r`/`-c` includes in requirements files are copied into the dependency build, and the filtered copy of a CI
  requirements file sits beside it so its includes resolve (`sandbox/provision.py`);
- with Debian's archive allowed the image carries `git` and `make`; an `apt-get install` after `&&` is read; a test
  command that stops at `X: command not found` names the program and where it would come from;
- the quiet-host rule scales with the CPUs; a busy host, a spend cap, the kill switch or a policy refusal is a block,
  never "the candidate broke the workload"; the monthly cap reached is a person's block, released when it rises;
- a candidate goes through the team's formatter (black or `ruff format`) before it is measured;
- the endpoint-to-table map is read in batches and cached by handler (81 calls to 8 on spoolman);
- tests that fail only because the image lacks an executable are kept apart from the project's failures; local
  proposals and open pull requests are counted apart.

Fixed on main: answering "raise" to the spend question amended the machine ledger while the router checks the
mandate's monthly cap, so the calls stayed refused; it now raises `business_constraints.maximum_monthly_spend_usd`
(higher than before, recorded as `MANDATE_CHANGED`) and releases the held work (`director/asks.py`).

The road to 1.0: `docs/ROAD-TO-1.0.md` (criteria redefined from campaign 12, five classes of improvement),
`docs/bench/campaign13/` (protocol, measures), D-065.

## 0.12.8 (2026-11-03): a sandbox Postgres starts when the project's password lives in an untracked .env

Seen on the demo copy with a model (0.12.7, option `api`): every measurement of an unindexed foreign key waited 90 s
and failed with "data service db was not ready", and the agent chose a new request with the model each time
(US$0.36 in 20 minutes for nothing). The compose file declares `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?...}`; the
value lives in the project's untracked `.env`, so in the sandbox it resolves empty, and the postgres image refuses
to start without a password. A sandbox database is throwaway, offline and on an internal network: when its password
resolves empty it now starts with `POSTGRES_HOST_AUTH_METHOD=trust`, and the application connects with the empty
password it was given (`sandbox/sidecars.py`, `tests/unit/test_sidecars_env.py`). Verified on the demo copy: the
database comes up; the next blocker (the application started as its image starts it) is in the walk notes.

## 0.12.7 (2026-11-03): the chat answers as a colleague, with read-only tools

Seen on the end-user walk: "hola" in the app got "No he entendido la petición. Puedo: graficar la latencia…". Under
option `api` the chat never called a model for a free question: `_inform` went to the rule planner before any model
call, `chat.inform` is `local_only` (the mandate denies local inference under `api`), and the canvas tools label their
output `runtime`, which never leaves. "¿para qué sirve todo esto?" was refused as a kill (the preposition `para`
matched the stop verb).

- **A greeting is answered without a model**: "Hola. Soy Unbidden, el agente que trabaja en …; pregúntame qué
  encontré, qué estoy haciendo…" (`chat.greeting`).
- **A free question no rule knows goes to a model with read-only tools** (`chat/agent.py`, purpose `chat.agent`,
  routed like heavy work: Meta's API under `api` and under `mixed` when the content may leave, the local model under
  `local`). Tools: `records_query` (status, opportunities with their stage, open questions, notes, proposals, spend,
  connections), `world_query` (the map: summary, services, tables, endpoints, blind spots), `read_file`, `grep`,
  `git_log` (the repository at HEAD, under `repo.read`), `docs` (what Unbidden is, the cycle, the commands, the
  modes, the evidence levels, the keys, the spend: `chat/docs.py`, in the package). Each result carries its source
  label (`record`, `repo`, `prompt`; never `runtime`), so the router's gate decides what may leave; a refusal is the
  answer, with the hint that would allow it. Four tool rounds, then it must answer. A question a rule knows (a
  table, a chart, the status line) still goes by rules; an analysis still goes by the digest.
- **`para` is a preposition**: only `para el/al agente` stops the agent.
- The chat's remaining hard-coded Spanish ("(sin respuesta)", "He aplicado las herramientas anteriores", the spend
  chart's title, the rules' failure line, the no-model analysis) moved to `web/text.py` and `text_es.py`.

Verified: `make check`; `tests/web/test_chat_agent.py` (a greeting without a model call; a free question under
`api` to the remote model with the six tools, two tool rounds and the labels `record` and `prompt` on what went
back; without a key the refusal with the router's reason and a hint; a rule-known question still by rules; the tools
over the demo record and a repository; the intent fix); and `unbidden chat` on the demo copy from this checkout.

## 0.12.6 (2026-11-03): reconnaissance before the agent runs

Seen on the end-user walks: the agent started with the stack down and found nothing of the database until a person
brought the stack up by hand; GitHub stayed `needs_authorization` in the connections table though the setup had
verified the account; the deploy procedure the repository documents was logged as "proposed only" and never
declared; the drill was never offered. The person's words: "unbidden debería ser capaz de tener un muy buen
reconocimiento inicial y dejar todo perfectamente conectado antes de continuar".

- **A `recon` section in the default walk** (`setup/recon.py`), between model access and permissions. In order:
  the stack (when it is down, "start it now with `docker compose up -d --wait`?", in the person's terminal); the map
  of the running system (no model call), with its blind spots said; each Postgres service, read inside its container
  (nothing leaves it) and, when it publishes a port, a read-only role over the network if the person gives one, the
  grant written only after it connects; GitHub, the access the found block verified written as the `github`
  connection grant (the table says `connected`); external APIs the compose files name, a key or skipped; the deploy
  procedure found in the repository, adopted into `operations.deploy_steps` with a yes; the rollback drill, offered
  when the steps, a live health endpoint and two commits exist. What was found and decided is kept in the store
  (`recon`, with `complete`); `unbidden setup recon` runs it again.
- **`start` warns when the reconnaissance never ran or is incomplete, and refuses an autonomous start on an
  incomplete one**; `doctor` has a `recon` line.
- **The in-container Postgres read shows as a connection** (`postgres:container:<service>`, connected): the
  registry looked for the reader's stamp on the service resource, which the map never stamps; it is on the tables
  and their `defines` relations.

Verified: `make check`; `tests/unit/test_recon.py` (a running stack mapped, the database read, GitHub granted, the
procedure adopted, the drill run; a down stack started with a yes; a network grant checked before it is written and a
failed one not; a scripted run that records what it could not do and `start` saying so); and on the demo copy, from
this checkout, a scripted recon with the stack running: the map, `db` read inside its container, GitHub written as a
connection and `unbidden connections` saying `connected` for both.

## 0.12.5 (2026-11-03): the agent asks with options, says what it is doing, and marks what matters

Seen on the end-user walks (0.12.2 and 0.12.3, Linux): the app never offered a choice. A proposal waiting for
approval, a key the service refused, a hold after a bad deploy, a deploy procedure found in the repository, a
registry the sandbox needed: each lived in a collection (`blocks`, `holds`, `proposals`, `actions`) and in
`agent.log`, surfaced only by `/activity` or the dashboard, answered only by typing the right command. Nothing said
what the agent was doing, how long it usually takes or what comes next. "Pull request opened" was a line like any
other.

- **Questions with options** (`contracts/ask.py`, `director/asks.py`). Where the agent stops for a person it opens
  one `Ask` per subject: *approval* (the pull request: approve, reject with a reason, later), *credential* (a
  refused key: paste another, proven before it counts), *registry* (allow the host in `egress.package_registries`),
  *hold* (keep, or release with a reason), *deploy_steps* (adopt the procedure found into the mandate), *spend* (a
  new cap), *access* and *capability* (the command, until their effects move here). Answering applies the same module
  the CLI command uses, writes `ASK_ANSWERED` with the person as actor, and the ask is withdrawn on its own when the
  matter was settled another way (`reconcile`, every tick).
- **In the app** the question opens by itself when nothing else is open: arrows or a click, Enter answers, Esc leaves
  it for later; an option that takes a value (a key, a reason, an amount) asks for it next. `/ask [id]` brings one
  back; the bar counts `N question(s) · /ask`; the feed says `Question: … · /ask <id>` with the command for a
  terminal. In the dashboard the "Necesita una persona" card shows each question with a button per option
  (`POST /actions {operation: "answer"}`). `unbidden ask` lists and answers from a terminal; `unbidden inbox` and
  `unbidden activity` show them first.
- **Progress** (`director/pipeline.py`). Every job writes `JOB_STARTED` (what it does, the stage it works toward,
  the usual seconds from the last ten runs, or "first time") and `JOB_FINISHED` (ok, failed, parked, stopped; the
  seconds; what it queued next). The bar says `now: measuring a candidate in the sandbox → measured` and, between
  jobs, `next: proposal.prepare`. The feed narrates the jobs that matter (lab, probe, checks, prepare, publish,
  deploy) and keeps the routine ones for `/verbose`. `unbidden inbox` has a `stage` column: `3/7 measured`,
  `5/7 proposed`. The sentences the cycle wrote only to its log ("experiments wait", "no proven fix", "waiting for
  a person", "CI green on pull request #n", "merged") are `NOTE` events now, in the feed and the dashboard.
- **Tones**. A feed line is plain, a question (accent), good (`✓` bold: branch pushed, pull request opened, CI green,
  merged, deployed, improved), warn (`!` accent: parked, waiting, not measured) or bad (`✗` bold: refused, blocked,
  failed, rollback, CI red). The publisher writes `BRANCH_PUSHED` before the pull request; `PROPOSAL_PUBLISHED` says
  the number; model calls refused for the key fold into one bad line.

Verified: `make check`; the app's pilot tests (a question opens on its own and Enter approves; Esc defers and the bar
counts it); the cycle test (one ask per proposal, a NOTE); and the walk on the demo copy described in the pull request.

## 0.12.4 (2026-11-03): Flask applications have endpoints

On the demo copy of ihatemoney (Flask with blueprints and Flask-RESTful, no OpenAPI document) the map had tables
and no endpoints, so `unindexed_foreign_keys` and `full_table_scans` dropped every finding (an opportunity names the
endpoints that pay for it; with none, there is nothing to measure) and the only opportunity was a ruff finding.
Endpoints were read from FastAPI routers and from a live OpenAPI document only.

- `world/flask_routes.py`: a Flask application's routes, read from the code: `Blueprint(..., url_prefix=)` and the
  prefix given to `register_blueprint`, `@bp.route(path, methods=[...])` and `@bp.get/post/...`, Flask-RESTful's
  `Api(bp, prefix=)` and `add_resource(Cls, "/path", ...)` as one endpoint per HTTP method the resource class
  defines. `<int:x>` reads as `{x}`, so a live document, when there is one, reconciles the same way. Each endpoint
  carries its handler's file and line (`static.py` adds them as inferred, `prefix_known`, `framework: flask`; a
  file that declares Flask routes is not read as a FastAPI router too).
- `world/column_use.py`: a Flask-SQLAlchemy model without `__tablename__` maps to its class name in snake case
  (`Bill` -> `bill`, `ShoppingList` -> `shopping_list`), in the static table resources too; a handler that filters
  by the column in its own body counts, and a call reaches the repository's only definition of that function
  whatever the file names say (`web.py` calling `models.py`'s `get_bills_unordered`).
- The "describe no OpenAPI" and "full endpoint paths" blind spots are not raised for endpoints read from Flask.

Seen on the demo copy, from a checkout: 83 resources instead of 20; 64 endpoints; two opportunities on the first
map: `person.project_id is a foreign key without an index, filtered on by 7 endpoint(s)` and `bill.payer_id ...
filtered on by 1 endpoint(s)` (`GET /{project_id}/`, via `list_bills` and `get_bills_unordered`). Measuring them
in the lab against a Flask server is the next walk.

## 0.12.3 (2026-11-03): a key is proven before anything runs on it; the installer speaks in steps

Seen on the first end-user walk on Linux (`curl -fsSL https://unbidden.cl/install.sh | sh`, 0.12.2, Fedora, a public
copy of ihatemoney): the person pasted a shell command where the setup asked for the Meta API key. The setup saved it,
the free model listing answered 401 and the text said inference might still work; nothing proved the key. The agent
then ran for an hour and a half with every remote call refused (`invalid_api_key`): the labs swallowed the error as
"no usable answer" and counted an attempt against the opportunity, the probe said "no model answered" in the log, the
app's bar said only "spend cap not verified", and the ledger charged US$0.04 for calls Meta had refused. Each is fixed
here, with its test:

- **A key is proven when it is pasted.** A value that cannot be a key (a command, spaces, under 16 characters) is
  refused in place and asked again. Then one short inference call (8 tokens, under a cent, in the ledger) says
  "Key accepted: muse-spark answered" or "Meta refused this key", and a refused key gets a menu: paste another, use
  a local model, or continue without one (the agent refuses to start). A key saved earlier is proven the same way,
  once per key: `~/.unbidden/keys.json` keeps its fingerprint and the verdict, never the key (`setup/keycheck.py`).
  `--probe` is gone: proving is not optional.
- **A 401 is "key rejected", never billed, never retried.** `ProviderUnauthorized` (401/403) is a `ProviderRejected`:
  the ledger row settles at US$0, `MODEL_CALLED` carries `problem: key rejected`, the labs and the research code
  re-raise it instead of treating it as a failed answer, so the loop records a `pending_person` block ("a Meta API
  key the service accepts: `unbidden key set`") and spends no attempt of the opportunity.
- **Nothing starts on a refused key.** `start` and `/start` prove a saved key once (a refused one refuses the start
  with `unbidden key set`; one that cannot be proven now only warns). `doctor`'s `meta api` line says what the key
  does, not what the listing says. The app's bar shows `MODEL KEY REFUSED · /key` from the first refused call.
- **`unbidden key`, `unbidden key set`, `unbidden key remove`, and `/key` in the app:** the key's state, a new one
  pasted hidden and proven on the spot, or gone. `setup credentials` and `setup models` use the same step.
- **A local model, made to work.** When the option needs a local model that is not there, the setup installs Ollama
  (the official installer in the person's terminal on Linux, Homebrew on macOS, after asking), starts its server,
  pulls the model that fits and proves it with one short generation; `doctor --fix` does the same. A small model is
  said to be small: it serves what never leaves the machine.
- **The installer speaks in steps.** On a terminal: `✓ uv 0.9.x`, `✓ Downloading unbidden 0.12.3`, `✓ sha256
  verified`, `✓ Installing unbidden 0.12.3`, then the installed path and the two commands that matter. What uv and
  curl print goes to a log shown only when a step fails; `--verbose`, `UNBIDDEN_INSTALL_VERBOSE=1`, and any run
  without a terminal (CI) print every line as before.

Verified here: the unit and app suites (`make check`); the installer from local artifacts into an empty HOME, on a
terminal and through a pipe; `unbidden key set` with a wrong key against the real API (refused at once, US$0 in the
ledger, `start` refused); the demo repository's walk is the person's, after the release.

## 0.12.2 (2026-11-02): the route shown is the route run; the egress gate reads code as the prompt guard does

Three things seen on the first walk on Linux (Fedora x86-64, option `api`, mode `supervised`, a public copy of the
FastAPI full-stack template), each a fix with its test:

- A lab's progress line said "asking the local model for the schema change" while the call went to Meta's API; the
  text was fixed in the code. The labs now ask the Brain where the call goes (`Brain.where`, dry) and say so:
  `asking the model at api.meta.ai (muse-spark) for the schema change`, `the local model (llama3.2:3b)`, or `no
  model` with the mandate's reason.
- `unbidden route` showed `fallback local` under a mandate with `local_fallback: deny` or `local_inference: deny`:
  both rules were applied only when a call was made (`Brain.complete`). `apply_mandate` (`brain/route_policy.py`)
  applies them in `Brain.decide`, which `route`, the chat and the labs read, so what is shown is what runs: a call that
  may run nowhere shows `denied` with the reason; a refused fallback shows `-` and names the rule. When the first model
  fails, a refused fallback is still recorded (`MODEL_FALLBACK`, `taken: false`), never taken.
- The egress gate refused five `world.endpoint_tables` requests over public code ("payload contains 1 secret(s)")
  that the prompt guard had passed. The gate scans the request serialized as JSON, where a newline is the two
  characters `\n`, so `password=user_in.password\n` read as a value ending in a backslash and no longer looked like
  code. A backslash now ends a value; a parameter's type annotation inside a parameter list (`token: TokenDep)`) and
  the template's `changethis` placeholder are not secrets. On the template's five files that were refused: 8 false
  hits before, once serialized; 0 after; the suite's real-secret cases are still refused, raw and serialized.

## 0.12.1 (2026-11-02): GitHub through gh, no OAuth App

The browser sign-in no longer needs an OAuth App of Unbidden's own: the setup's "gh" choice installs the `gh` CLI
when it is missing (the machine's package manager, in the person's terminal, after asking) and runs
`gh auth login --web`; the app steps aside for it and comes back. Unbidden reads that session as it already did
(`gh auth token`, held in memory, never copied). The device-flow module is gone. The found block now also asks
GitHub who the access found is and whether that account can push to the repository of the remote; an account
that cannot gets the same menu as no access. Tab in the app completes a command instead of moving the focus.

## 0.12.0 (2026-11-02): Spanish

What Unbidden says to the person follows a language: the app, the setup assistant, the home screen, `/help`, the
chat's own sentences and the installer's closing lines, in English or Spanish. Resolved from `UNBIDDEN_LANG`, then
the choice saved on the machine (`/language es|en`, `unbidden setup language`), then the terminal's locale, then
English; a key a translation lacks falls back to English. Not translated: the other CLI commands, the engine's
records (reasons, titles, pull request text stay as recorded) and the web dashboard, which stays Spanish. A third
language is one `text_<code>.py` per table. `docs/INSTALL.md`, "Languages".

## 0.11.0 (2026-11-02): setup asks three things

The assistant finds the repository and its GitHub remote, where GitHub access comes from (a saved token, the
environment, or the `gh` CLI's sign-in, held in memory and never copied), the scope, the connections the compose
files declare at HEAD (listed, never granted on their own), the machine, Ollama and its models, and whether a key
is saved; the model option follows from those facts. It asks the Meta API key only when none is found, how much
Unbidden may do on its own, and whether to apply. Priorities, budget, dashboard, private code and manual
connections keep their defaults, shown with the section that changes each (`unbidden setup budget`, `/setup
connections`, pre-filled from compose). A sign-in through the browser came with 0.12.1, through `gh`. Scripted setup needs no `--models` or `--mode`. `docs/INSTALL.md`,
"`unbidden setup`".

## 0.10.2 (2026-11-02): a chat question answered twice, and a start that refuses what cannot run

- A chat turn in the app or the dashboard failed on the second question with `RuntimeError: Event loop is closed`:
  each provider kept one HTTP client for life while every turn ran its own event loop. Now a client belongs to the
  loop that uses it and is closed before that loop ends (`unbidden/brain/providers/clients.py`, `Brain.aclose`).
- `unbidden start` and `/start` first check, without any network call, that the option's model exists here
  (Ollama reachable with the recommended model pulled, or the API key held). If not, nothing starts: exit 4 with
  the one command that fixes it; `--force` starts anyway. Docker absent or a missing GitHub token only warn.

## 0.10.1 (2026-11-02): the mark and the menus

The banner's ring is drawn in braille cells, round and thin, open at the upper right with the dot outside the gap,
as the logo is; the wordmark letterspaced. On the setup screen a choice (local / mixed / api, the mode, a connection
kind) or a confirmation is a menu: arrows or a click, Enter; the default highlighted. Nothing else changes.

## 0.10.0 (2026-11-02): the terminal app

`unbidden` on a terminal (at least 60 columns, `TERM` not `dumb`, no `--json`, `--plain` or `UNBIDDEN_PLAIN`) opens
a full-screen app on Textual 8: the setup assistant inside it the first time, then the live feed of the agent's
records grouped by what it is doing (discovering, investigating, experimenting, proving, deciding, asking,
guarding), a prompt for questions and `/` commands, a status bar (agent, jobs, mode, model option, spend available,
dashboard, age of the last event). The engine is unchanged: the app reads the records and calls the actions that
already existed (start, stop, kill switch, approve, reject, chat). `docs/INSTALL.md`, "A first run". Verified by hand
on macOS arm64 with the built wheel installed by `install.sh` into an empty HOME and driven in a pseudoterminal; CI
unchanged (without a terminal, `unbidden` is the text home screen). Everything below describes 0.9.0 and still holds.

**Status: 0.12.8, experimental candidate.** Not 1.0: the criteria of v1.0 are in `docs/CAMPAIGN-v1.md` and were not
met when the campaign paused at its gate (D-063); they are not changed here. The one that blocks 1.0: no useful cycle
has been shown on an application not used in development. This candidate adds the product around the same engine:
an installable wheel, a guided setup, one executor per workspace with a background agent, and the dashboard and chat
on the engine's own records (D-064). Nothing is published, tagged, released, merged or deployed.

## The exact point

- Code: product branch `feat/63-product-onboarding` (code at `2d72ce4`, the commit CI validated; the head adds documentation only), cut from `main` at `d560b6f` (the merge of
  PR #2: 0.9.0 and the web workspace). `pyproject.toml` says `0.9.0`; `unbidden --version` prints `unbidden 0.9.0`.
  `uv.lock` pins every Python dependency (Python 3.12). This file is updated after the commit it names: read it from
  the branch head.
- Verified platform (and only this one, by hand): macOS on Apple Silicon (arm64), 2026-11-01; Docker with its buildx
  and compose plugins. Linux x86-64 runs in GitHub Actions only (below). Linux by hand, Intel macOS and Windows were
  not tested.
- Models: Meta's API (`muse-spark-1.3` on the `code` route) in the validation (option `api`). The local route
  (Ollama, `muse-glimmer:30b-mxfp8-dflash`) is supported and was exercised in earlier stages; options `local` and
  `mixed` were configured by tests, not walked with a model.

## What it supports (v1.0 scope), and what it does not

| Area | Supported (exercised) | Not supported, or not exercised |
|---|---|---|
| Install | one wheel with the web workspace inside, installed by `install.sh` as a uv tool with its own Python 3.12, sha256 verified; from the GitHub release through `curl -fsSL https://unbidden.cl/install.sh \| sh`, or from local artifacts; `update`, `uninstall` keeping data | PyPI |
| Projects | a git repository whose Python project is at the root: `pyproject.toml` (uv or Poetry locks), `requirements.txt` or `setup.py`; the interpreter chosen from the project's own declarations (CI matrix, Dockerfile, `.python-version`, `requires-python`, locks), the rule recorded | a Python project in a subdirectory (no per-subproject environment); interpreters outside 3.8-3.13 |
| Checks | the project's tests (pytest) from its GitHub Actions test job: local reusable workflows and composite actions followed, an action's test-command input read as the command, the job's service containers as sidecars, the job's `uv sync` groups; without such a job, pytest over the repository. Run once at the base of every commit (`observe.checks`) and three rounds on each side of every experiment | CI suites sharded by matrix into groups (not one command); jobs that need network, privileges or the repository's secrets while they run; other CI systems |
| Running system | Docker Compose projects on this machine: containers, published ports, the live OpenAPI, PostgreSQL catalogs read inside their containers (also when started from a compose file Unbidden does not read) | Kubernetes, remote hosts, cloud accounts |
| Databases | PostgreSQL over the network, a read-only role, bounded reads | MySQL, SQLite connections, IAM auth |
| HTTP APIs | OpenAPI 3.0 and 3.1 (recursive schemas included), served under the document's `servers` path; an API key in a header, or no credential; only the operations the document says that credential can call; page, offset/limit and cursor pagination, completeness judged by how counts behave; documented-vs-observed deviations recorded per operation and field; rate limits waited out on reads; writes with an `Idempotency-Key`, undone by a DELETE, each authorized just before it is sent | OAuth, bearer tokens, keys in a query string; APIs that read through `POST` (every POST is treated as a write); SOAP, GraphQL; writes without an observable undo |
| Findings | unindexed foreign keys (traced to the endpoints and SQL or ORM code that use them), whole-table scans, API-reported numbers against stored data, crashes found by property tests, the project's own linters and type checkers | other kinds of defect |
| Operation | one executor per workspace (a kernel lock on `.unbidden/engine.lock`); `start`/`stop`/`status` of a background agent; stale locks recovered and interrupted jobs resumed; the kill switch untouched by `stop` | starting at boot (nothing is installed as a service); two agents on one workspace; NFS workspaces |
| Dashboard and chat | `unbidden ui` and `start --ui` over the repository's own state, read-only; demo and historical sources; actions (approve, reject, approve writes, kill, resume) on live sources; chat that informs by rules and analyzes with one routed call | deploy and rollback from the dashboard (they name the CLI command); the chat acting on anything |

## What it may do, and when a result is accepted

The mandate (`.unbidden/mandate.yaml`, written by `unbidden setup` or by hand) decides what runs on its own:
`observe`, `run_experiments`, `provision_dependencies`, `use_new_capabilities`, `delegate_synthetic`,
`open_pull_requests`, `merge_pull_requests`, `deploy`, `rollback`, `act_on_connections` (each `allow`,
`require_approval` or `deny`); the registries builds may reach (`egress.package_registries`); where model calls may
go (`models.profile`, `local_fallback`, `local_inference`: the three options `local`, `mixed`, `api` are fixed
combinations of these); a monthly spend cap; the connections and their permissions. The setup assistant shows the
effective permissions computed by the `PolicyEngine` before writing.

**Autonomy modes** (unchanged): `supervised` asks before a pull request and never merges or deploys; `autopilot`
opens pull requests for proven work and people merge; `autonomous` also merges L4 work, deploys with the team's steps
and rolls back, and cannot be switched on without `operations.deploy_steps` and a passed `unbidden drill`.

**Credentials** are never in the repository or the mandate: they live in `~/.unbidden/.env` (written by setup, mode
600) and `.unbidden/.env`, referenced by name (`credential_ref`); a broker hands them to the one call that needs them;
prompts, logs and stored records are scanned and masked (credential-looking values, personal data); a credential a
service refuses is reported as an access problem for a person, but a read it simply does not reach is left out.

**Evidence levels** (each claim's confidence is capped by its level):

| Level | Meaning, precisely |
|---|---|
| L1 | Reasonable suspicion: a check or a model points at something; nothing reproduced |
| L2 | Reproduced: the finding is observed (a scan, a query plan, a discrepancy between an API and its data) |
| L3 | Improved in the lab: a change measured better in the sandbox, but the project's checks did not validate it on both sides |
| L4 | Functionally validated: the project's own checks pass on both sides (three rounds each), and the measurement passes criteria **perf-v4** (D-060): perf-v3's sessions (four alternating sessions per side on fresh databases, an exact permutation test on session medians at alpha 0.05, at least 20% faster, and for an index, the index seen in use on every measured call), plus the same responses on both sides, an A/A control of base sessions and a confirmation in new sessions in a new order. Verdicts under older criteria are listed as pending revalidation |
| L5 | Operational result: measured on the running system after deploy, its confounders listed |
| L6 | Persisted: L5 held over the mandate's period |

A goal's result is an acceptance with sealed conditions (`applied`, `accepted`, `rejected`, `inconclusive`,
`stale`), the model's own claim recorded apart. A conclusion that needs a whole set is withheld when a read is
partial (unknown completeness, or a query that reached its limit): a discrepancy found stands; "none" does not.

## Models and budget

Every remote call reserves its worst cost in `~/.unbidden/spend.db` before it is sent and settles to the reported
cost after; calls past the cap a person entered are refused. The mandate's monthly cap is checked in that one ledger
for every process of a workspace, so the dashboard's chat and the engine count against the same cap. An
authorization can be split into envelopes, each enforced the same way (`unbidden spend --envelopes dev=12,eval=12,demo=6
--envelopes-total 30 --source ...`; every call then names one with `UNBIDDEN_ENVELOPE`); a cap is raised without
resetting what was spent (`--amend-cap`). The ledger is an estimate (list price x tokens), not a bill. Setup calls no
model; its optional paid probe asks first and shows the worst cost. What costs tokens and what does not, command by
command: `docs/INSTALL.md`.

## Known limitations (each seen in a run)

- **No useful cycle on an independent application yet.** On Conduit (development) the full cycle runs: reproduce,
  find, measure, propose, decline what does not hold. On the evaluation's applications it did not.
- **No public release.** Install from local artifacts; `unbidden update` without `--version` finds nothing.
- **Linux not verified by hand**: GitHub Actions is the only Linux evidence (below).
- An empty HOME has no Docker CLI plugins: without buildx the first build records a `compatibility` block
  (`unknown flag: --progress`). `doctor` checks the daemon and both plugins (`docker buildx`, `docker compose`) and explains a missing one.
- A dashboard served apart keeps its own model runs and egress in `~/.unbidden/web/<source>-state.db`; `unbidden
  egress` lists them beside the engine's with their origin (`dashboard apart`), and the spend ledger is one. Two
  workspaces with the same repository name share a monthly cap. `unbidden ui` has no `--state-dir`.
- The chat's deterministic repertoire is the rules' list (status, tables, charts, explain, compare two runs, change a
  chart, undo); everything else needs a model.
- Performance workloads are written by a model, and the verdict depends on the data they seed: the same index on
  Conduit measured 18% with one workload and 25% with another.
- The world checks find unindexed foreign keys and table scans; the value of an index on a table that is empty in the
  lab cannot be measured there.
- Masking credential-looking or personal values in prompts hides them from the model too.
- A few real projects, run a few times each: no claim about rates.

## Install and check

The one guide is `docs/INSTALL.md`. The short form, from a checkout, until a release exists:

```sh
git clone https://github.com/satisfymath/unbidden-ai.git && cd unbidden-ai
git checkout feat/63-product-onboarding       # the candidate named above (code 2d72ce4 + docs)
make dist                                      # Node 24 builds the web workspace; uv build; SHA256SUMS
(cd dist && python3 -m http.server 8777 --bind 127.0.0.1 &)
UNBIDDEN_INSTALL_BASE=http://127.0.0.1:8777 sh install.sh --yes --version 0.9.0
unbidden --version                             # unbidden 0.9.0
```

Prerequisites a person provides: git; Docker with its buildx and compose plugins (`docker buildx version` and
`docker compose version` must answer; Docker Desktop and OrbStack install them for the user); for options `mixed` and
`api`, a Meta key, which `unbidden setup` asks for and saves in `~/.unbidden/.env` (mode 600), and a spend cap entered
by a person (`unbidden spend --verified-balance`); for options `local` and `mixed`, Ollama with a model that fits the
machine (setup offers the download; `unbidden doctor --fix` pulls it later). Developers: `uv sync` and `make check`
(ruff, pyright, pytest; the Docker tests skip without a daemon).

## The walk

```sh
cd your-repo
unbidden                     # the assistant: project, priorities, models (local | mixed | api), credentials,
                             # autonomy (supervised | autopilot | autonomous), connections, budget, dashboard;
                             # the diff of the mandate before writing; no model called
unbidden doctor              # required and optional, for the option chosen
unbidden start --ui          # the agent in the background; the dashboard served from its process
unbidden status              # pid, log, stale or not; dashboard URL; kill switch
unbidden chat "why did the last check block?"   # inform by rules, analyze with one routed call; never act
unbidden stop                # ends agent and dashboard; the job in progress returns to the queue
unbidden ui                  # a dashboard served apart: same widgets, same conversation
unbidden ui --stop           # ends only that dashboard
unbidden start               # resumes interrupted jobs; a second start answers "already running: pid N"
```

Without a terminal: `unbidden setup --non-interactive --models api --mode supervised --budget 1.5 --dashboard later
--model-key-stdin --yes --json` (the key on stdin, never in argv or output).

**Walked on 2026-11-01, macOS arm64**, with the installed tool from an empty HOME (`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`,
credentials file written by setup), on a dedicated clone of the fork `satisfymath/rich` at `9d8f9a372cc5`, option
`api`, mode `supervised`, monthly cap US$1.5. Reused from the host, declared: the real spend ledger
(`UNBIDDEN_HOME=/Users/david/.unbidden`, envelope `s11-product`), the machine's Meta key passed on stdin, and
`DOCKER_CONFIG=/Users/david/.docker` after the first attempt without it recorded two `compatibility` blocks for the
missing buildx plugin (kept in the record).

| Step | Result |
|---|---|
| install | `unbidden --version` = 0.9.0; the dashboard's assets inside the wheel |
| setup | mandate `frontier`, `local_inference: deny`, `local_fallback: deny`; `.env` mode 600; the key's name in the JSON, never its value |
| doctor | exit 0: Ollama and local model optional, Meta API and Docker required and present |
| cycle (`start --ui --port 8830 --interval 60`) | the project's checks at the base passed (981 collected, 0 failed); a robustness probe with 3 calls to `muse-spark-1.3` found 1 property violation, kept for a person (L1); 14 events, 0 opportunities (no improvement was needed for this walk) |
| dashboard served by the agent | summary live and current, the agent's pid, the key present (name only), the 14 events by type |
| chat | status by rules without a model; one analysis call (US$0.0051) citing the record's counts and the two Docker blocks; 2 widgets created by rules, provenance `live:rich-s11`, an empty table marked `missing` |
| stop and reopen | `stop` withdrew agent and dashboard; `unbidden ui` on another port showed the same 2 widgets and 8 messages; `ui --stop` ended it |
| stop and resume | a second `start` answered `already` with the same pid, one `watch` process; `kill -9` of the agent: `status` running false, stale true, 1 job running; `start` resumed 1 interrupted job; clean `stop`, no KILL file, 0 processes left; 14 events before and after |
| spend | US$0.0438 (4 calls) in `s11-product`; the machine's cumulative cap unchanged |

Record: `docs/PRODUCT-ONBOARDING-PLAN.md`, "Validación real acotada". Not walked by hand: Linux, options `local` and
`mixed` with a model, `autopilot` and `autonomous`, a project with connections.

## CI on Linux x86-64

Run [41333127432](https://github.com/satisfymath/unbidden-ai/actions/runs/41333127432) on `2d72ce4` (`ubuntu-latest`,
x86-64, 2026-11-01), every job green. Reported apart, as each covers a different thing:

| Job | What ran | Result |
|---|---|---|
| `check` | `uv sync --frozen`, ruff, ruff format, pyright, `pytest -q` (the deterministic suite, mocks for every model) | 939 passed, 2 skipped, 6 deselected (slow) |
| `frontend` | `npm ci`, lint, typecheck, vitest, `npm run build`, Playwright (Chromium) against the Python server serving the built assets on the demo and a historical record | vitest 10 passed; Playwright 7 passed |
| `installed` | the wheel built with the web workspace inside; `install.sh --yes --version 0.9.0` from a local server into an empty HOME; `unbidden --version`; `setup --non-interactive --models api --mode supervised` in a fresh repository; `doctor --json` (Ollama and the local model optional, Meta API required); the home screen; `setup --mode autonomous` refused with exit 4 and nothing written; `start` → `status` (running) → a second `start` refused → one `watch` process → `stop` → `status` (not running, not stale), no KILL file; `unbidden ui` serving the built `index.html` from the installed package (no Node on that path), reused on a second call, `chat` by rules (inform; an action refused), `ui --stop`; Docker reported (present on the runner, with buildx and compose); `install.sh --uninstall --yes` keeping the data | all steps passed |
| `secrets` | gitleaks over the history | clean |

What this does and does not show: artifact install and command resolution on Linux x86-64, yes; onboarding and the
deterministic walk, yes; the daemon's start/stop/status and the dashboard from the installed package, yes; Docker,
only its presence (no sandbox build, no cycle); no model was called (US$0). "Linux validated end to end" would
require a real cycle with Docker and a model on a Linux host, which was not run. The real cycle, the chat analysis
and the dashboard with real events were run on macOS arm64 only (`docs/bench/product-walk-2026-11-01/`).
`release.yml` (manual, publishes nothing) could not be dispatched from the branch: GitHub only runs a
`workflow_dispatch` workflow that exists on the default branch, so it waits for the merge.

## Preparing a project apart

```
unbidden prepare /path/or/url --rev v1.2.3 --into ~/unbidden-lab/name
```

Copies the repository apart at a commit, reads its stack (and says why each version was chosen), builds the
dependency image with network to the mandate's package registries only, reads the CI's test plan (what was left out
and why), runs the project's own checks offline in the sandbox and prints the outcome with its evidence: tests
collected and failed, or why none ran. A block is printed as the finding. `unbidden doctor` inside a repository adds
the scope diagnosis: whether its stack, tests and database are inside what this version supports, and why not when
not. What a person still prepares for the lab (a compose file of the application, synthetic data, a read-only role)
is not part of this command and is counted as human preparation in every record.

## The mandate, by hand

`unbidden setup` writes it; `unbidden setup <section>` changes one part; `unbidden mode` and `unbidden models` change
the two most common. It can also be edited: `unbidden init` writes the supervised default. A mandate, without secrets
(secrets go in `~/.unbidden/.env` or `.unbidden/.env`, mode 600, referenced by name):

```yaml
mandate:
  workspace: shop
  priorities: [correctness, performance of reads as data grows]
  business_constraints: {maximum_monthly_spend_usd: 2.0}
  autonomy: {observe: allow, run_experiments: allow, provision_dependencies: allow, delegate_synthetic: allow,
             use_new_capabilities: allow, open_pull_requests: deny, merge_pull_requests: deny, deploy: deny,
             rollback: deny, act_on_connections: deny}
  egress: {package_registries: [pypi.org, files.pythonhosted.org],
           remote_models: {destinations: [api.meta.ai], max_payload_bytes: 60000}}
  models: {profile: frontier, local_fallback: deny, local_inference: deny}    # what the option `api` writes
  connections:
    - {id: shop-db, kind: postgres, location: 127.0.0.1:5432/shop, environment: staging, username: shop_reader,
       credential_ref: SHOP_READER_PW, permissions: [read]}
    - {id: shop-api, kind: http_api, location: http://127.0.0.1:8000, docs: http://127.0.0.1:8000/openapi.json,
       environment: staging, credential_ref: SHOP_API_KEY, permissions: [read]}
```

`content_may_leave: true` on a connection and `private_code_to_frontier: allow` are a person's statement that the
data and code may leave (synthetic data, public code); on real projects leave them out.

## Evidence: where it is, how to keep and review it

- `unbidden activity` (found, decided and why, the project's checks at the base, blocks and requests, proofs and
  revocations, spend), `unbidden why <opportunity>`, `unbidden connections`, `unbidden egress`, `unbidden spend`;
  the dashboard and `unbidden chat` read the same records.
- `.unbidden/state.db`: opportunities with their history, experiments with every measured session raw, verdicts
  and revocations, goal runs, acceptances, model runs, egress attempts; `.unbidden/artifacts/`: patches, workloads,
  probe files, logs; `.unbidden/logs/agent.log`: the background agent's output.
- To keep a run's evidence, move the whole `.unbidden/` out of the repository after it (the harnesses do); the
  spend ledger is per machine and is never reset. A kept `.unbidden/` can be served read-only as a historical source
  (`python -m unbidden.web --record`).

## Stop, clean up, recover, roll back

- `unbidden stop` ends the background agent cleanly: the job in progress returns to the queue without spending an
  attempt; the kill switch is not touched. `unbidden start` resumes; after a crash or `kill -9`, `status` says the last
  run ended without `stop` and the next `start` requeues what was running.
- `unbidden kill` stops everything now (no new job or model call, in every process; running sandbox containers
  killed; pushes, pull requests, merges, deploys and rollbacks check it immediately before acting); `unbidden resume`
  lifts it; `kill --stop` also ends the agent.
- Experiments work on snapshots, never on the repository; a proposal is a local branch (or a pull request where the
  mandate allows), reverted like any commit. A deploy is rolled back with the mandate's own steps; a failed one leaves
  a hold only a person releases (`unbidden hold`).
- A lab verdict that does not hold is revoked, not erased (`unbidden/lab/revoke.py`): kept with its reason.
- Clean up: sandbox containers carry `unbidden.sandbox` (`docker ps -a --filter label=unbidden.sandbox`); dependency
  images are `unbidden-deps-*`; the workspace is `.unbidden/`. The benchmark labs own their resources by identity
  (`unbidden.lab.id=<lab>`): `... down` removes only that lab's containers and networks and keeps its data; `--volumes`
  removes the data too.
- Roll back the tool itself: `unbidden update --version <previous>` or `sh install.sh --version <previous>`; data
  untouched. `unbidden uninstall --yes` removes the tool and keeps `~/.unbidden` and every `.unbidden/`.

## The demo

The recorded demo is stage 9's, on the engine this candidate carries: `docs/bench/stage9-demo.md`, written from the
run's records by `bench/ecosystem/demo9_report.py` (no model writes it), with an independent check
(`bench/ecosystem/conduit_indep.py`: the endpoints' own SQL on the lab data, rolled back). Run DEMO-B-1 at 2f3986e on
Conduit, a **development** application: a demonstration, not evaluation evidence.

- Harness (not Unbidden): the repository at 029eb77, synthetic data (2,000 users, 20,000 articles, 300,000
  comments, 20,000 favorites), a read-only role, a fresh token, a proactive mandate with no goal, the `demo`
  envelope; one declared answer (a registry Unbidden names: `deb.debian.org`).
- Unbidden: the project's checks at the base (90 passed); six opportunities; two L4 under perf-v3
  (`commentaries.article_id` 24.1 -> 18.3 ms, `favorites.article_id` 9.6 -> 1.7 ms, the index used on every
  measured call), one measured "no change" (`articles.author_id`), one not measurable (its workload failed), two
  consistency questions inconclusive (completeness unknown); two local branches with migrations; nothing pushed.
  US$0.53, 46 calls, 47 minutes.
- Independent check: the comments listing 8.27 -> 0.06 ms; the article delete 0.61 -> 0.20 ms with comments indexed
  on both sides. Both L4s confirmed.

The product walk (install, setup, `start --ui`, dashboard, chat, stop and start) has no recorded demo yet; its
validation is the table under "The walk". `demo/autonomous.sh` is the older CLI demo (marshmallow, from a checkout
with `uv run`, autonomous locally, pull requests only to the fork).

## Integration proposal

Facts from the graph (origin, 2026-11-01): `main` is `d560b6f` (the merge of PR #2, 0.9.0 + the web workspace). The
product branch `feat/63-product-onboarding` was cut from it and is 27 commits ahead, among them three `--no-ff`
merges of its own side branches (`feat/63a-distribution`, `feat/63c-daemon`, `feat/63e-docs`, all merged and
deleted). A test merge of the branch into `main` in a scratch worktree is clean: 71 files, +7,885/-421, no
conflicts. The branch is published on origin for CI only; no pull request, merge, tag or release was made.

Proposal, for a person to carry out, in this order: (1) read the CI results of the branch head (above) and the walk's
evidence (`docs/PRODUCT-ONBOARDING-PLAN.md`); (2) one pull request `feat/63-product-onboarding` -> `main`, merged with
`--no-ff` (the result's tree equals the branch's); (3) only then `.github/workflows/release.yml` can be dispatched (a
`workflow_dispatch` workflow must exist on the default branch to be run): run it once in its only mode, build and
smoke-test without publishing, and read the Linux smoke report it uploads; (4) the first release, when David decides
it: tag `v0.9.0`, a GitHub release carrying `unbidden_ai-0.9.0-py3-none-any.whl`, `SHA256SUMS` and `install.sh`
(the commented block at the end of `release.yml` shows the shape), after which the one-line install in
`docs/INSTALL.md` becomes true and the "available once..." notes are removed; (5) PyPI (`unbidden-ai`, free) as a
second channel later. Rollback of (2): `git revert -m 1` of the merge commit, or a reset before anything is built on
it; the spend ledger, the labs' data and every workspace's `.unbidden/` live outside the repository. The version
stays "0.9.0, experimental candidate" until another decision is taken explicitly.
