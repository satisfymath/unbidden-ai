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
