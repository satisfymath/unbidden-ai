# Campaign 12: Unbidden as an installed product, on a wide corpus, with real Meta models and full autonomy in labs

Written before any run (2026-11-01). What changes after the freeze (section 9) is recorded as a dated amendment at the
end, never edited in place.

## 0. What is measured and what is not

Measured: on how many projects the installed product works from installation; what human preparation it needs;
whether it reproduces the environment and the project's checks; what it discovers and what it misses; whether it
experiments and validates correctly; whether it proposes, publishes pull requests, merges and deploys when that is
what the mandate allows; whether the UI reflects what happened; whether it stops, recovers and continues without
duplicating effects; where it blocks, why, and which general changes would improve the product.

Not measured, not claimed: that this version is better than another; any number about "all repositories"; success on
stacks outside the declared support. The sample is small; results are descriptive, each with numerator/denominator
and a Wilson 95% interval where a rate is reported. Repetitions of one repository are not independent samples.

## 1. Candidate

- Branch `feat/64-campaign`, cut from the product branch head `901a5f9` (A to E delivered, CI green on
  `ubuntu-latest`, run 41333549971). `main` (`d560b6f`) does not contain the product work: the candidate is NOT
  integrated, and the campaign evaluates the branch head, installed from its wheel.
- One correction before the freeze, because it affects the Director's decisions: local proposals waiting for a person
  were counted as open pull requests (`open_prs += 1` per proposal in a sweep), so a supervised run with three
  proposals reported "3 pull requests already open (cap 3)" with one pull request on the fork (seen 2026-11-01 on
  Rich). Now `Context.open_pull_requests` is what is open on GitHub (`PR_OPENED`), `Context.pending_proposals` the
  local proposals (`READY` plus those decided this sweep); the GitHub cap counts pending proposals only when the
  mandate lets Unbidden open pull requests on its own, and the reason names each (`test_director.py`).
- Frozen candidate: commit `2f7eee504dd24d763a72079686161c8247416226` (filled at the freeze); wheel `unbidden_ai-0.9.0-py3-none-any.whl`
  sha256 `e8c7cc8a2ef849f25930b402393ddc18b04d5972206d1ee247ebe9796568856c`; built with `make dist` from that commit; served to every run by the campaign's local server
  (`python3 -m http.server` over `dist/`) because there is no public release: the public URL is not validated here.
- Version stays "0.9.0, experimental candidate". No tag, release, PR to `main` or merge into `main` in this campaign.

## 2. Authorization and isolation (David, 2026-11-01)

Allowed: reading the Meta and GitHub credentials through the credential broker (never their values); forks and test
resources on the `satisfymath` account; branches, pull requests and merges on those campaign forks; building and
running the selected repositories in isolated labs; deploying only to those labs; controlled failure and rollback
drills on campaign resources; sanitized code and records pushed to the campaign branch.

Not allowed: pull requests, pushes, merges or comments on third-party upstreams; destructive changes to existing forks
holding other work; deploys to production or real external services; touching Hosli, the existing Mealie, other
personal applications or other sessions' labs; billing changes; deleting anything outside this campaign's inventory.

Rules: every created resource goes to `INVENTORY.md` with an unambiguous name (prefix `c12-`); an existing fork is
reused only read-only or with new branches that carry the prefix, never reset; tokens by reference through the
broker, never in prompts, visible commands, logs, screenshots, artifacts or URLs (the dashboard's session token is
scrubbed from every kept log); the machine's `.env` is never copied whole into a repository or a container.

## 3. Autonomy, by the product's own rules

Mode `autonomous` for Level B runs on applications with a lab; the product's conditions are met by preparation that
is counted as human work: `operations.deploy_steps` (the lab's steps, in the mandate), `operations.check_steps`, a
health URL, and a passed rollback drill (`unbidden drill`) before `unbidden mode autonomous` is accepted. No
`gate=False`, no forged approvals, no evaluator patches, no direct calls around Guardian. A missing condition is a
recorded block, not something the harness works around during the run.

Libraries have no server deploy. Completing a library's cycle means: a proposal reaching the mandate's level,
published as a pull request on the campaign fork by Unbidden on its own (`autopilot`: `open_pull_requests: allow`),
its CI green on the fork, and a merge that is either (a) Unbidden's when the mandate allows merging without deploy
(it does not: `autonomous` requires deploy steps, so this is recorded as a product limit), or (b) a person's, counted
as a human step. No deploy is invented for them.

During autonomous runs nobody helps the agent. An intervention ends the autonomous attempt; a continuation is
labelled "assisted" or "regression" and reported apart.

## 4. Budget (ledger, 2026-11-01)

Cap raised from US$37.2945 to **US$97.2945** (US$60 authorized by David for this campaign), spend kept
(US$27.8551 at the amendment), envelopes added without touching the earlier ones: `s12-pilot` 8.00, `s12-eval`
30.00, `s12-dev` 17.00, `s12-confirm` 5.00 (envelopes total 80.30). No transfers, no increase without
authorization; nothing has to be spent. Dashboard credits (US$118.36) are the provider's reference, not this budget.

Per-run limits (enforced by the product or the harness, each recorded): mandate `maximum_monthly_spend_usd` 2.00
per workspace (Level B), 0.00 for Level A (every model call refused by the cap: Level A costs nothing by design);
one cycle at a time per host; cycle bound 90 minutes (`bench/ecosystem/cycle.py`); checks bound 60 minutes; at most
two cycles per run plus one resume cycle; at most 2 concurrent Level A preparations (no performance measurement runs
beside a build; the product's own load detection defers measurements and the deferral is recorded).

Models: Meta API only, `frontier` + `local_inference: deny` + `local_fallback: deny`; `muse-spark-1.3` on every
route. Wonder: only in one predeclared, bounded comparison (section 8) if it is available and the question is
concrete; never switched per repository to rescue a result.

## 5. Corpus (40 unique repositories)

Three classes, never mixed in a rate: A. 12 development/regression (known projects, to calibrate the harness and fix
general problems); B. 20 independent (never used to tune Unbidden; frozen with their commits before any product
run); C. 8 frontier (outside or near the declared support; they measure diagnosis, abstention and the clarity of the
limits, not success).

Selection: A from `bench/repos/campaign-v1.yaml` (12 of its 20, chosen for diversity of family and build tool,
listed in `corpus.yaml` with the reason); B and C by the written rule in `bench/campaign12/corpus-candidates.md`
(GitHub search queries in a fixed order, criteria checked file by file, every inspection recorded before the next).
Exclusions: every repository in earlier corpora, in stage 9/10 evaluations, or already forked on `satisfymath`.
After the freeze no repository is replaced; a failing one stays in the denominator. Each repository's record:
URL, license, commit, family, size, stack, services, how checks run, why it was included, prior exposure (the
developer's and Unbidden's), expected preparation.

Declared support (from `unbidden/observe/scope.py` and `docs/RELEASE.md`): a Python project at the repository root;
pytest from a GitHub Actions job (or pytest files, partially); Docker Compose services; PostgreSQL for performance
and consistency work; interpreters 3.8-3.13. The class of each repository (inside / near / outside) is written down
before its first run.

## 6. Levels

**Level A, all 40** (US$0): the installed artifact; `unbidden setup --non-interactive --models api --mode supervised
--budget 0 --dashboard later --yes` (the assistant's scripted form; the key is held by the campaign HOME's `.env`,
written once by `setup credentials` with the value on stdin); `unbidden doctor --json` (support diagnosis);
`unbidden scan` (isolated preparation: the dependency image, the CI's test plan, the project's checks in the sandbox;
the analyzers; no model); `unbidden start --interval 3600` → `status` → `stop` (the daemon's lifecycle; its first
cycle's model calls are refused by the zero cap and that refusal is recorded as such, not as a block); `unbidden ui`
→ `/api/session`, `/summary`, `/opportunities` read through the API → `ui --stop`; a verifiable result or block per
step. Bounds: 60 min for the checks, 10 min for everything else.

**Level B, 12 chosen before any result** (8 independent, 4 development; families varied inside the support):
two runs per repository from the same restored state (repository at the pin, lab re-seeded, new `.unbidden`, the
fork's campaign branch reset to the pin): run 1 and run 2 are the same protocol and measure within-repository
variability; they are not two applications. Each run: proactive discovery without a ticket; experiments; validation;
publication and merge on the fork when a proposal reaches the level (autopilot for libraries; autonomous for lab
applications after the drill); deploy and verification in the lab when applicable; a second cycle that must not
repeat effects; `stop` and `start` between cycles; the UI and chat over the real records (section 8). Mandate cap
US$2 per workspace; two cycles plus one resume cycle; 90 min per cycle.

## 7. Human preparation, measured

Three components, kept apart in every record: what the installer does; what the harness or a person prepares
(clone, compose, services, synthetic data, credentials, mandate, deploy and rollback steps, compatibility fixes);
what Unbidden does on its own. Minutes and steps are counted per repository. Repository-specific fixes are not hidden
in preparation scripts: each is a line in the record with its cause. A workload or reproducible case the harness
writes is attributed to the harness. An incompatibility found during a run stays as the result of that attempt.

## 8. Seeded scenarios and UI checks

A separate battery, never mixed with natural opportunities: rejected/revoked credential; exhausted budget; Docker or
a service down; partial read; lost response after a write; simultaneous second start; process crash during a job;
interruption after an external effect; restart without duplicated PRs/merges/writes; UI port busy; close/reopen the
dashboard; kill switch and recovery; a defective deploy and its rollback; a healthy control that must stay intact; an
irrelevant change that must not be promoted. Each with its expected observable and its verdict. Exit 0 is not
success; no false promotion when no experiment ran proves nothing about precision.

UI, with a browser (Playwright) on each Level B run: connection and activity state; the engine's real events;
findings, experiments, proposals, blocks; applied vs claimed vs verified; live/historical/demo provenance; complete
empty tables vs missing data; a deterministic query without a model call; an analysis through Meta's API; a widget
from existing data; persistence across reload and restart; approvals per mode and permissions; no secret in content
or answers. Visual, navigation and comprehension errors are recorded beside technical failures.

Wonder comparison (predeclared, bounded, optional): if Level B shows a reasoning failure that repeats on the same
input (a wrong fix candidate or a wrong analysis), the same input is sent once to `muse-wonder-1.0` under `s12-eval`,
at most 5 calls in the campaign, recorded apart. No other use.

## 9. Freeze, phases and criteria

Phases: 1 protocol, corpus, budget, limits, criteria (this document); 2 pilot on development repositories to check
the harness (`s12-pilot`); 3 freeze of candidate, harness, corpus and criteria in one commit; 4 the evaluation with
no change to code or harness while it runs (`s12-eval`); 5 analysis of causes, independent verification, priorities;
6 corrections with tests that reproduce each defect (`s12-dev`); 7 the affected cases repeated as regressions, the
initial result kept (`s12-confirm` for a final bounded confirmation). After the evaluation is used to correct, it is
no longer out of sample; a future independent confirmation needs new cases.

Independent verification of every promoted improvement (section 10 of the brief): the problem exists; the change
corresponds to it; the relevant checks ran on both sides; no test was removed or acceptance weakened; the measurement
meets the current criterion; the published and deployed effect corresponds to the evaluated commit. By replay of
requests, external checks, query plans or postconditions; otherwise "no independent confirmation". A declared absence
states the scope observed. Verifiers are frozen with the criteria; a defective verifier keeps the original reading and
adds a separate re-evaluation.

Metrics (units and denominators fixed now; per repository, per family, aggregate; classes apart):
installations completed / repositories; onboardings completed / repositories; environments reproduced (dependency
image built) / repositories inside support; checks executed / repositories inside support, with the effective
coverage (collected tests, scope of the CI plan, partial or not); checks green / project failures / environment
failures (three columns); repositories with ≥1 valid experiment / Level B repositories; repositories with a natural
improvement verified independently / Level B repositories; supported abstentions; technical blocks (by cause);
false promotions (any: a stop condition); pull requests, merges and deploys observed on the fork or lab / proposals;
rollbacks verified; duplicated effects (any); human interventions (count, minutes); UI walk success / Level B runs;
latency, cost (ledger, list price), resources (wall time, host load at start).

Stop conditions: the cap or an envelope reached; an unauthorized action or a false promotion observed (stop, record,
fix as a decision before anything else); a harness defect that invalidates records (fix, re-run from the pilot, keep
the invalid records labelled).

## 10. Records and deliverables

Per run: `docs/bench/campaign12/<phase>/<repo>/<run>.json` (installer, setup, doctor, scan, lifecycle, UI, cycles,
decisions, proposals, effects observed on the fork/lab, spend before/after, interventions, bounds hit) plus the
archived `.unbidden` outside the repository (`~/unbidden-lab/c12/archive/`), sanitized logs and screenshots in the
record. `INVENTORY.md` (forks, branches, labs, HOMEs, containers, volumes), `corpus.yaml`, this protocol, the
aggregate report (`REPORT.md`) with the failure/cause matrix, before/after comparisons for corrections, cumulative
cost, the prioritized improvement list, the conclusion on which product promises hold and which need narrowing, and
a release recommendation (no 1.0 label, no automatic release).

## Amendments (dated; nothing above is edited)

- 2026-11-01, before any Level B run: the four development repositories of Level B are `fst`, `spoolman`, `rich`,
  `marshmallow` (not `conduit`): the rollback drill needs a health endpoint the application exposes, and Conduit has
  none (`GET /api/tags` is not a health check); Spoolman (`/api/v1/health`) and fst (`/api/v1/utils/health-check/`)
  have one and build from their repositories. Conduit stays in Level A, and "an application without a health
  endpoint cannot reach autonomous" is recorded as a product limit to state, not worked around.
- 2026-11-01, pilot finding: the project's checks run in the agent's first cycle (`observe.head` → `baseline_checks`),
  not in `scan` (analyzers only); Level A waits for that record (bounded) instead of reading it after `scan`. The
  dependency images of development repositories were cached on this machine from earlier stages: Level A records
  whether the image was built in the run or existed before, and "environment reproduced" time is read with that.
- 2026-11-01, corpus selection done by the recorded rule (`corpus-candidates.md`): 14 independent repositories were
  found, not 20. Quota 1 (FastAPI applications with a database) filled 1 of 5 and quota 3 (Flask applications) 1 of
  3: at stars > 150 those topics are templates, libraries, LLM wrappers needing a paid key, or backend+frontend
  monorepos without a root manifest. No criterion was relaxed. An extension search under a wider, also recorded, rule
  (stars 50-150; `topic:sqlalchemy` / `topic:postgresql` applications) is being prepared as an option; the decision
  (34 repositories, or 34 + the extension's candidates) is David's and is asked before the frozen evaluation starts.
  Level B independent set, chosen now from the 14 by a rule and before any run: the two smallest applications with a
  database (`brightbean-studio`, `misago`), the Flask application (`traefik-manager`), the first three libraries in
  the rule's order (`oauthlib`, `rdflib`, `graphtage`), two CLIs (`pipx`, `harlequin`). Applications without a health
  endpoint will not reach autonomous (recorded as a product limit); libraries and CLIs run in autopilot.
- 2026-11-01, David's decisions before the freeze (verbatim where it matters): (1) corpus of **39** (12 development,
  19 independent = 14 by the base rule + `recruitops-agent`, `aiogramshopbot`, `gymhero`, `dinkydash`, `tracklater`
  by the recorded extension rule, 8 frontier), the FastAPI-with-database gap declared, no incompatible repository added
  to reach 40; groups and denominators kept. (2) Public copies `satisfymath/c12-<name>`, only of the selected public
  repositories, with: licenses, attribution and provenance kept; no existing repository overwritten; the upstream
  commit pinned, any campaign configuration in separate documented commits; no secrets, `.env`, personal data or other
  projects' configuration copied; no package published or external deploy through their workflows; the Meta API key
  never a GitHub Actions secret; upstream never modified. Before the freeze, on a development copy: a pull request
  starts the relevant checks; the checks belong to the PR's exact head; the product recognizes their result; red or
  absent CI prevents the merge; green CI lets it continue when the other conditions hold; the deploy that follows
  happens only in the authorized lab. The project's checks are never replaced by a workflow that always passes;
  changes needed to run CI in a copy are documented as human preparation and checked to keep their coverage.
  (3) codex-lb's misclassification corrected with a regression test and the case re-verified; humanize/msgfmt and
  conduit/gcc recorded with causes, no hidden repository-specific fixes; Spoolman's 108 calls left as a cost finding.
  (4) Then freeze code, wheel, harness, corpus, CI configuration, criteria and budget. (5) Level B composition: the 4
  development repositories and the 8 independent ones, two runs each; development results are not added as
  independent evidence. (6) The campaign runs inside the authorized envelopes without asking again; failures, blocks
  and retries are kept; no code changes during the evaluation. (7) Report apart: installation and onboarding; checks
  reproduced and coverage; discovery and experiments; pull requests published; CI observed; merges effective; deploys
  and verified effects; UI and recovery; interventions, latency and cost. (8) No pull request is forced when there is
  no valid improvement; seeded scenarios stay apart from natural findings.
- 2026-11-01, candidate moved for the freeze: `2f7eee5` (pilot) → `69b0702` (adds only the codex-lb classification fix,
  `unbidden/lab/testsuite.py` + tests); wheel sha256 `e8c7cc8a…` → `cffdf7ac…`, served from the same local server
  and installed into the campaign HOME; `corpus.yaml` keeps both pairs. Pilot records stay as measured on `2f7eee5`.
- 2026-11-01, copies (`bench/campaign12/copies.py`, frozen with the harness): per copy the pin is the upstream default
  branch; ONE campaign commit on top removes the workflow files that would deploy, release, publish or act as bots
  (the list and the reason per repository are in `COPIES`; Spoolman's `ci.yml` loses its two publishing jobs, the
  test jobs byte for byte); Dependabot is disabled in the settings and its pull requests are never counted. The local
  Level B checkout is restored at the copy's base head (pin + campaign commit) so a proposal's base matches the
  remote. The harness keeps observing a cycle while an open pull request of the agent has CI pending (it waits
  longer, within the bound; the agent is never told). The report's Level B section lists the nine dimensions per
  class with numerators and denominators; `dev` is labelled calibration.
- 2026-11-01, candidate moved once more before the freeze: `69b0702` → `8686674` (the classification rule's second
  iteration: `could_not_run` kept apart from `failed`; see FINDINGS); wheel sha256 `a9154175…`. The fst copy test
  (`pilot-copy`) ran on `69b0702`'s wheel (`cffdf7ac…`): the CI → merge → deploy path it exercises does not touch the
  changed code (the suite runner's failure classification), and the tool is never reinstalled under a running run.
  The frozen evaluation runs on `8686674` only. `corpus.yaml` keeps all three (candidate, wheel) pairs.
- 2026-11-01, pre-freeze test passed on the development copy (`pilot-copy/fst/B1`, details in FINDINGS): a pull
  request started the copy's own checks; the 13 check runs were on the PR's exact head; the product merged only after
  they were green (and had waited on the fork when none had run); the deploy that followed happened in the lab
  `c12-fst` only. Red CI is covered by the product's unit tests (no live reproduction without touching the agent's
  pull request). Copies, the per-copy campaign commit and the Dependabot setting are frozen as `copies.py` states.

## FREEZE (2026-11-01, phase 3)

Frozen for phase 4, nothing below changes until phase 6:
- **Code**: candidate `8686674327b6ce2fba44b4c2640977fecd0da2e2` (main `d560b6f` + product branch `901a5f9` + the
  Director's open-PR count fix + the suite runner's missing-executable classification in two commits).
- **Wheel**: `unbidden_ai-0.9.0-py3-none-any.whl` sha256 `a915417588329e4383cd5f07ba96499dc228976863792f8d51e46dfa634a3917`,
  served from `~/unbidden-lab/c12/dist/` over `127.0.0.1:8790` by `install.sh`, installed in `~/unbidden-lab/c12/home`
  (`unbidden 0.9.0`); `run_eval.sh` refuses to start on another hash.
- **Harness**: `bench/campaign12/` at the freeze commit (the commit that adds this section); `frontend/scripts/c12_ui_check.mjs`.
- **Corpus**: `bench/campaign12/corpus.yaml`, 39 repositories (12 dev, 19 independent, 8 frontier), pins as listed;
  Level B: `fst`, `spoolman`, `rich`, `marshmallow` (dev) and `misago`, `brightbean-studio`, `traefik-manager`,
  `oauthlib`, `rdflib`, `graphtage`, `harlequin`, `pipx` (independent), two runs each, from the restored state.
- **CI configuration**: the twelve copies `satisfymath/c12-<name>` as `INVENTORY.md` lists them (pin + one campaign
  commit per copy, `copies.py` `COPIES` for what each removes and why; Dependabot disabled); the base restored to pin +
  campaign commit before every run; no secret added anywhere.
- **Criteria**: sections 0-11 above and the dated amendments; the nine report dimensions per class; `dev` is
  calibration, never independent evidence; seeded scenarios apart.
- **Budget**: cap US$97.2945; `s12-pilot` 8.00 (spent 1.215 at the freeze), `s12-eval` 30.00 (0), `s12-dev` 17.00 (0),
  `s12-confirm` 5.00 (0); the evaluation runs under `s12-eval` only; no transfers.
- **Order**: `run_eval.sh all`: Level A over the 39 (US$0), then Level B run 1 over the 12, then run 2; one thing at a
  time on this host; a failed repository stays in its record and the next starts; no code or harness edit during the
  evaluation (a harness defect that invalidates records is a stop condition, section 9).
