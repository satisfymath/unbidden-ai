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
