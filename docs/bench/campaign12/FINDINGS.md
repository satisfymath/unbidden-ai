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
