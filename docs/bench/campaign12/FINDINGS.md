# Campaign 12: findings as they appear (product defects, harness defects, observations), dated, never edited later

Each line: date · where seen · what · class (defect / wording / harness / limit) · status (open / fixed in <sha> /
accepted limit). Fixes happen only in phase 6; until then the line stays open and the record keeps the behaviour.

- 2026-11-01 · Rich product walk · the Director reported "3 pull requests already open (cap 3)" with one pull request
  on the fork: local proposals counted as open pull requests · defect (decisions) · fixed before the freeze in
  `2f7eee5` (candidate).
- 2026-11-01 · Level A pilot · `scan` does not run the project's checks (analyzers only); they run in the agent's first
  cycle. A person reading "scan: run the repository's own checks in the sandbox" (the command's help) expects them
  there · wording/UX · open.
- 2026-11-01 · Level A pilot, humanize · the dependency image lacks `msgfmt` (gettext): the CI's
  `scripts/generate-translation-binaries.sh` fails with exit 127, recorded as `infra_failed` (correct class). The image
  does not read system packages a CI job installs with apt · limit (environment reproduction) · open.
- 2026-11-01 · Level B pilot, rich · the lab logs "asking the local model for a candidate" while the mandate denies
  local inference and the call goes to Meta's API (`measuring the frontier candidate` follows) · wording · open.
- 2026-11-01 · Level A pilot · dependency images of development repositories were cached from earlier stages, so
  "environment reproduced" took 10-20 s; a fresh machine builds them (minutes). Recorded per run (`image_age`) ·
  harness/observation · recorded.
- 2026-11-01 · Level A pilot · the ledger's `spend_calls` shown by the dashboard for a workspace named like an earlier
  one (`humanize`) counted that earlier spend; the campaign names workspaces `c12-<name>` to keep rows apart ·
  limit (workspace = repository name) · known, documented in RELEASE.
- 2026-11-01 · seeded scenarios, run 1 · "¿Qué recomendarías revisar primero?" was classified as informing (the
  analysis patterns know `recomienda|recomiendas|recomendar`, not the conditional), so no model call was attempted
  and the cap-0 refusal was not exercised · defect (chat intent coverage, ES conditional/subjunctive forms) · open.
- 2026-11-01 · seeded scenarios, run 1 · option `api` on a repository GitHub has not confirmed public: an analysis is
  refused by routing ("private_code leaves only renamed by the privacy bridge") before the ledger is reached; correct
  by the data rules, but the hint offered was the local-inference one (`models local-first` / add a key), not
  `models frontier --private-code allow`, because the hint table matches "denies local inference" first · wording
  (hint order) · open.
- 2026-11-01 · seeded scenarios, run 1 · after `resume` from the dashboard, an agent started with `--interval 3600`
  stays asleep until its next tick: releasing the kill switch does not wake the loop (run 2, interval 15 s: the agent
  worked within two ticks) · UX (resume could wake the loop; with the default interval it is a short wait) · open.
- 2026-11-01 · seeded scenarios, run 1 · two simultaneous `start`: one owner, the other "already running" (correct);
  `pgrep -f 'unbidden.cli watch'` still listed two processes 3 s later · resolved in run 2: the count was host-wide
  (other campaign runs' agents); one owner per workspace held · harness artefact · closed.
- 2026-11-01 · Level B pilot, rich B1 · autopilot opened 3 pull requests on the campaign fork (`c12-base`), the second
  cycle opened none again (same 3 branches, same 3 PRs; jobs 30 → 39) · observation (no duplicate effect) · recorded.
- 2026-11-01 · Level B pilot, rich B1 · `unbidden egress` lists 2 `chat.analyze` rows for one terminal analysis: the
  first attempt was repaired (two egress attempts for one answer); the record is right, the count may surprise ·
  observation · recorded.
- 2026-11-01 · Level B pilot, rich B1 · the dashboard's layout for `live:rich` already held a table from the product
  walk of the same day: the presentation store follows `UNBIDDEN_HOME` (the machine's ledger home), not the
  installed tool's HOME, so two installations sharing a ledger share layouts by source id · limit (state location) ·
  open.
- 2026-11-01 · Level B pilot, rich B1 · the fork's CI does not run on pull requests against `c12-base` (Rich's
  workflows filter on `master`): "CI green on the fork" cannot be observed for libraries in this setup; the product
  would wait for CI before an autonomous merge · campaign setup limit · recorded.
- 2026-11-01 · Level B pilot, marshmallow B1 · 4 opportunities (ruff/mypy) declined by the Director as outside the
  team's CI scope, robustness probe 0 crashes, no proposal; one chat analysis said so from the record and named what
  the digest lacks (severity, effort, risk) · supported abstention (valid outcome; US$0.018) · recorded.
- 2026-11-01 · Level B pilot, marshmallow B1 · the second cycle's dashboard came up on 8861 although `start --ui
  --port 8860` was asked: the port was still held (TIME_WAIT or the previous server's socket) and `free_port` moved on
  without a word in `status` beyond the new URL · UX (say "8860 was busy; using 8861" in `start`'s output) · open.
- 2026-11-01 · Level A pilot, codex-lb · 34 of 6,422 tests failed in the sandbox with `FileNotFoundError: 'git'`:
  the dependency image has no git, and the record says `failed` (a project failure) where the cause is the
  environment · defect (classification: a missing system tool in the image should read as `infra_failed`, like
  humanize's `msgfmt`) · open.
- 2026-11-01 · Level A pilot, conduit · `blocked`: `asyncpg==0.26.0` has no arm64 wheel and the slim image has no
  `gcc`; the stage-7 lab solved it by building the app image for linux/amd64 (human preparation). The product says
  so in `scan`'s problems and in the record · limit (environment reproduction: no compiler, no platform fallback) ·
  open.
- 2026-11-01 · Level A pilot, development set · 12/12 installed, onboarded, agent lifecycle and dashboard; checks
  reproduced with tests collected 10/12 (passed 8, project failures 2), environment failures 2 (humanize, conduit);
  US$0 (cap 0 refused every model call; the refusal is in each agent log) · observation · recorded.
- 2026-11-01 · Level B pilot, spoolman B1 (lab from source, drill passed, `mode autonomous` granted by the product) ·
  37 min, 108 model calls, US$0.746: 83 `world.endpoint_tables` calls (the map of 68 resources) and 20
  `lab.perf_request`; 4 opportunities (2 open: a 100k-row table read 122 times in 5 min, a `GET /api/v1/spool`
  group listing; 2 declined with reasons), no proposal, no pull request, no deploy beyond the drill's; the lab stayed
  healthy; the second cycle repeated nothing · observation (the cost of the first map dominates a cycle on an API of
  that size) · recorded.
- 2026-11-01 · Level B pilot, spoolman B1 · "not measured (cannot measure: no the handlers of the endpoints that read
  it)": a grammar slip in a reason a person reads, and the measurement needs handler code the map did not tie to the
  endpoint · wording + limit (perf measurement needs handler attribution) · open.
- 2026-11-01 · Level B pilot, spoolman B1 · `doctor` said "no database service declared" and the map listed the lab's
  `app`/`db` as "running, but not declared in any compose file read": the campaign compose file is named
  `docker-compose.c12.yml`, which the product does not read; the harness will name it `docker-compose.yml` when the
  repository has no compose file of its own (counted as preparation) so the declared view is fair · harness · fixed.
- 2026-11-01 · Level B pilot, spoolman B1 · the first open opportunity ("spool, 100000 rows, read 122 times in 5
  min") may count the agent's own probe traffic as application load; to verify in phase 5 before it is read as a
  finding · to verify · open.
- 2026-11-01 · verification, rich B1 · the three pull requests verified apart from the agent: each named finding
  present at the base and gone at the head (ruff run by the verifier), only the named files changed, no test file
  removed, no skip added; PR 4 (F811 in test files) re-checked in a fresh sandbox: the suite passes with the same 981
  tests collected as the base · verified (3/3) · recorded.
- 2026-11-01 · Level B pilot, fst B1 (autonomous after the product's drill) · 22 min, 40 model calls, US$0.17: six
  opportunities, the known `item.owner_id` foreign key without an index measured L4 (`DELETE /api/v1/users/me`
  14.14 → 4.49 ms, permutation p = 0.0), proposed and published as PR #4 on the campaign fork; not merged: "the
  repository declares CI workflows but none has run on" the pull request, so no autonomous merge and no deploy of
  the change; the drill's deploy is the only one; the second cycle repeated nothing; the lab stayed healthy ·
  observation + campaign setup limit (the fork's CI must run on the campaign base for the merge/deploy path to be
  observable) · open.
- 2026-11-01 · Level B pilot, fst B1 · 10 of 46 `world.endpoint_tables` payloads were blocked by the egress gate
  ("payload contains 1 secret(s)"): the repository's own code holds values the scanner reads as secrets (its example
  settings), so those endpoint-to-table readings never left and the map was built from the other 36 · observation
  (correct refusal; the map's coverage is reduced by it) · recorded.
- 2026-11-01 · forks and CI · on the campaign forks GitHub does not start `pull_request` workflows (fst fork: 15
  workflows registered, 0 runs for PR #4 and for a throwaway probe PR #5 opened by the owner with `gh`; rich,
  marshmallow, c12-spoolman: 0 workflows registered), while a `workflow_dispatch` run on the fst fork did execute.
  The product therefore never sees CI on its pull requests there and, in autonomous mode, waits ("declares CI
  workflows but none has run") instead of merging: the merge → deploy path cannot be observed on forks in this
  state. Two ways out, both a person's call: enable workflows in each fork's Actions tab (the fork-state prompt the
  API does not expose) or plain copies `c12-<name>` (a public repository creation was blocked by this session's
  permission classifier; not attempted again) · campaign setup block · open, decision asked.
- 2026-11-01 · before the freeze (David's instruction) · codex-lb's classification corrected in the candidate: a round
  whose every failure names an executable the sandbox image lacks is `infra_failed`, the tool named, the test names
  and the count kept; one real failure beside a missing tool stays the project's failure; the round is not retried
  (`unbidden/lab/testsuite.py`, regression tests in `tests/unit/test_testsuite_rounds.py`) · defect (classification) ·
  fixed in `69b0702` (the frozen candidate; the pilot ran on `2f7eee5`); the affected case re-run as Level A
  `pilot-fix/codex-lb` on the new wheel.
- 2026-11-01 · humanize (`msgfmt`) and conduit (`gcc` for `asyncpg`) stay as recorded: environment failures with their
  causes (the dependency image does not install the system packages a CI job adds with apt; no compiler and no
  platform fallback for a wheel-less dependency). No repository-specific fix in the harness · limit · open (phase 6
  candidates: apt packages the CI job names; a compiler in the image when a dependency has no wheel).
- 2026-11-01 · spoolman's 108 calls (83 `world.endpoint_tables` for a 68-resource map) stay a cost finding for the
  report's improvement list; the scope is not widened now (David's instruction) · cost · open.
- 2026-11-01 · copies instead of forks (authorized by David 2026-11-01): `satisfymath/c12-<name>`, plain public
  repositories, the pin pushed as the upstream's default branch, provenance in the description and homepage, one
  documented campaign commit per copy that removes the workflow files which would deploy, release, publish or act as
  the project's bots (and cuts Spoolman's two publishing jobs out of `ci.yml`, its test jobs untouched). On
  `c12-fst`, within a minute of the push, Dependabot opened five pull requests that each started the full CI
  (test-backend, playwright, pre-commit, zizmor, test-docker-compose): `pull_request` workflows DO run on copies.
  Dependabot's dynamic workflow is disabled in each copy's settings and its pull requests closed (not the agent's;
  they are never counted) · campaign setup · recorded. GitHub registers a workflow only once an event triggers it, so
  `deploy.yml` (push to master) could not have been disabled in the settings before the first merge would have run
  it: hence the commit, not the settings. The copy's base is therefore pin + one commit; Level B restores the local
  checkout at that head (a proposal's base is the local HEAD; the product marks a proposal stale when the remote base
  differs).
- 2026-11-01 · the existing campaign fork `satisfymath/c12-spoolman` renamed `c12-spoolman-fork` (GitHub keeps a
  redirect) so the plain copy can carry the authorized name · inventory · done.
- 2026-11-01 · pre-freeze, fst on the copy (`pilot-copy`) · the agent logged "host busy (load 1.6-2.1): measurement
  deferred" for several minutes while the harness ran other work on the same host (codex-lb's checks in the sandbox,
  the unit suite): the product's own load gate holds (correct), and the campaign's wall-time numbers for that run
  include waits the host caused, not the product. The pilot had concurrent runs too; the frozen evaluation runs one
  thing at a time (`run_eval.sh`) · harness/observation (latency confound, named) · recorded.
- 2026-11-01 · codex-lb re-run on `69b0702` (`pilot-fix`) still read `failed`: of its 34 failures 30 name the missing
  `git`, 4 do not (a `CalledProcessError` from a script, three `exit 126` of a repository shell script), so the
  all-or-nothing rule did not apply. The rule is replaced before the freeze: tests whose failure names an executable
  the image lacks leave `failed` and are kept apart as `could_not_run` (test → tool) in the round, the summary, the
  checks record (`{tests, lacks}`), the cycle's log line and the Level A record; a round with nothing else failed is
  `infra_failed`. For codex-lb the honest record becomes "failed 4; 30 could not run: the image lacks git" ·
  defect (classification), second iteration · fixed in the frozen candidate (next commit); re-verified as
  `pilot-fix/codex-lb` after the fst copy test (not concurrently: see the load note above).
- 2026-11-01 · pre-freeze test on the development copy `c12-fst` (`pilot-copy/fst/B1.json`, candidate `69b0702`,
  autonomous after the product's drill, 33 min, 125 calls, US$0.377, no block, no intervention) · the whole path the
  brief asks for was observed: (a) the agent published PR #4 (`item.owner_id` index, L4: `DELETE /api/v1/users/me`
  14.47 → 5.17 ms, permutation p = 0.0) at 23:09:21; (b) GitHub started the copy's own checks on it at 23:09:25:
  13 check runs (test-backend, test-docker-compose, playwright ×4 + merge + alls-green, pre-commit ×2, zizmor,
  changes, conflict detector), every one on the exact head `6a892d9a` the agent measured; (c) all 13 finished
  `success` at 23:12:03; (d) the product merged at 23:15:14, after the CI and only then (cycle 1 ended with the PR
  open and CI green but unpolled; cycle 2 polled, merged, `operations.merged` 1); (e) the deploy that followed ran in
  the lab only (`operations.deployed` 2 = the drill's and the change's; lab checkout at the merge commit `a76a7c9d`;
  health 200; `deployment.observed` 2, `impact.judged` 1, `outcome.recorded` 1); on the copy, master's push ran the
  test workflows only (no deploy/release workflow exists there any more). Red and absent CI: not reproducible on
  purpose without touching the agent's pull request; covered by the product's unit tests
  (`tests/unit/test_publish.py::test_no_merge_until_the_pull_requests_own_ci_passed`: none, pending, red, cancelled)
  and, for "absent", by the live pilot fst B1 on the fork ("declares CI workflows but none has run" → no merge).
  The second cycle repeated no effect (same proposal, now merged; the same 6 opportunities). Dashboard served and
  walked by the browser; chat analysis routed to Meta (`chat.analyze`, public_code) and answered from the record ·
  verdict: the copies work for CI, merge and deploy; the setup is frozen as is · recorded.
- 2026-11-01 · `c12-fst` · one `Smokeshow` run (workflow_run after a Dependabot PR's test-backend) executed on the pin
  before the campaign commit removed the file; it needs a secret the copy does not hold and uploaded nothing ·
  observation · recorded.
- 2026-11-01 · `c12-fst` · the squash merge the product performed carries the token owner's name as author (GitHub
  attributes API merges to the token's user); the commit message is the agent's proposal title and body with the PR
  number · observation · recorded.
- 2026-11-01 · codex-lb re-verified on the frozen wheel (`pilot-fix/codex-lb/A.json`, candidate `8686674`): checks
  `failed` with 6,422 collected, **failed 4, could_not_run 30 (lacks: git)**; the record's `why` ends with "30 test(s)
  could not run: the sandbox image lacks `git`". The 4 remaining failures (a script's `CalledProcessError`, three
  `exit 126` of a repository shell script) are left as the project's until a cause is shown; they may also be the
  environment's (an executable bit or a tool the script needs) and are listed for phase 6 · verified · closed for
  the freeze.
- 2026-11-01 · harness · the run tag did not carry the phase (`c12-B1-fst` for both the pilot's fst B1 and the copy
  test's), so `run_spend` in `pilot-copy/fst/B1.json` (US$0.3773) sums both runs; the envelope says the copy test
  itself cost **US$0.209** (`s12-pilot` 1.0062 → 1.215). Tags now carry the phase (`c12-<phase>-B<n>-<repo>`); the
  record is left as written and this line corrects its reading · harness defect (attribution) · fixed before the
  freeze.
- 2026-11-02 · eval · **Level A finished 39/39** (23:48Z → 03:33Z, US$0): setup 39/39, doctor 38/39, scan 38/39,
  UI walk 39/39, lifecycle (start, second start refused, stop, no jobs left, no KILL) 39/39. Checks by class: dev
  passed 8 / failed 2 / blocked 1 / infra 1; independent passed 2 / failed 5 / blocked 5 / infra 6 / none 1;
  frontier passed 1 / blocked 3 / out_of_scope 4 (declared gaps: Go, TypeScript, Python not at the root).
  Longest Level A: recruitops-agent 19.3 min (4713 tests, 309 opportunities). Analysis in phase 5.
- 2026-11-02 · eval · **pipx: `doctor --json` and `scan --json` crash** with `TypeError: Object of type datetime is
  not JSON serializable` (`observe/stack.py:368 _detect_python_parts`: `json.dumps(project)` on the parsed
  pyproject; pipx's `[tool.nab]` holds TOML datetimes `uploaded-prior-to = 2026-10-26T18:24:46Z`). The agent's
  first cycle then produced no `baseline_checks` in 1 h (`waited_s` 3602.8). Product defect, general (any TOML
  datetime in pyproject) · phase 6 with a regression test · pipx stays in the record as written; its Level B runs
  will show the same defect.
- 2026-11-02 · eval · **spoolman B1 did not run: harness crash** in `labs.up` (`labs.py:257` chmods
  `~/unbidden-lab/c12/spoolman/docker-compose.yml`, which does not exist: the lab directory for spoolman was never
  materialised before the freeze; the pilot ran spoolman at Level A only). No record written, `run_eval.sh` went on
  to the next repo (exit 1 logged). Harness defect, not product · decision for phase 5: fix the lab bring-up,
  document it, and run spoolman B1/B2 after the frozen sequence ends, apart from the main tranche.
- 2026-11-02 · eval · **Level B run 1 finished** (03:33Z → 16:18Z, 11 records; spoolman missing, harness crash
  above). Spend US$0.4146 (fst 0.1654 / 50 calls, rich 0.1061 / 11, the rest ≤ 0.032). Modes as the product
  resolved them: fst `autonomous` (the only repo with deploy steps and a drilled lab), every other repo `autopilot`
  (autonomous blocked without deploy steps; the harness named autopilot as the fallback) — so merges can only be
  observed on fst; elsewhere the dimension is "PR published, CI observed, left to a person". Agent PRs on copies:
  fst #5 merged by the product after 13 green checks on its head (deploy in lab `c12-fst`, health 200); rich #11
  (19/19 green), #12, #13 (17 red) open; misago #1 open (1 green). No PR on marshmallow, brightbean-studio,
  traefik-manager, graphtage, oauthlib, rdflib, harlequin; pipx produced nothing (datetime defect in every job).
  Bounds: five repos hit both cycle bounds (90 + 45 min: misago, oauthlib, rdflib, harlequin, pipx) because the
  loop keeps scheduling `world.refresh`/map jobs every 5 min, so the harness's idle rule (empty queue through two
  ticks) never fires · measurement cost, not a product defect; the per-repo wall time is dominated by it.
