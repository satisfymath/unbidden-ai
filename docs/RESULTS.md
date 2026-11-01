# Results: the matrix of version 0.9.0 (experimental candidate)

The one matrix the campaign to v1.0 (`CAMPAIGN-v1.md`) asked for, closed at the freeze of 2026-11-01 (D-063) on
commit `0ea665d`. Development results and independent evidence are never mixed; every row says who did what
(Claude as developer, the harness, Unbidden, the independent checker).

## Promise and tested scope

**0.9.0 promises**: given a repository, a mandate and credential references, Unbidden prepares an isolated copy,
builds the dependency image with provenance, reads the CI's test job into a plan it can run offline, runs the
project's own checks and says what it could not run and why; looks for performance opportunities (foreign keys
without an index), writes a candidate and a workload, measures under perf-v4 and promotes only with mechanism,
functional equivalence, an A/A control and a confirmation; checks data consistency between an API and its store
under a declared comparison; probes endpoints that declare a credential; records every finding with its evidence
and cost. **v1.0 is not claimed**: its criteria (`CAMPAIGN-v1.md`, section 11) are unmet; see D-063.

**Tested scope**: Python applications and libraries, pytest, GitHub Actions, PostgreSQL for performance work; on
macOS arm64 native only. Linux/x86-64 is the first step of the product phase (`PLAN.md`).

## Capabilities: implemented, demonstrated, pending

| Capability | Implemented | Demonstrated where | Pending |
|---|---|---|---|
| Environment: isolated copy, stack with provenance, image, CI plan, checks, coverage and blocks | yes (`unbidden prepare`, `observe.prepare.checks_record`, one path for daemon and bench) | level A, 7 runs on 20 repositories: honest 13, 12, 14, 14, 14, 17, 18 of 20 (tool's own counts 15, 16, 17, 17, 18, 19, 19); 10 pass outright at run 7 (`stage10-campaign/level-a-*/README.md`) | a declared support matrix in `doctor` (product phase); Django's runner out of scope; TimeTracker unstable |
| CI plan robustness | conditions, matrices (Linux first, the job's own database, no compose-started engine), split suites, make, tox (tox.ini, legacy, `[tool.tox]`), interpreters, workspaces, requirement files and extras, install/check/build/report scripts, runner edits under sudo, apt packages into the image, every declared service container, service-port expressions, `UV_NO_SYNC`, the job's own environment | the same 7 runs; 20 general corrections, each with a unit test that failed before (`tests/unit/test_level_a_blocks.py` and earlier) | the long tail is infinite: the contract (what is supported) replaces further rules |
| Workloads | model-written, validated at the base (D-059); rule-written index over one- and multi-line columns; the migration named in the project's own convention (c840697) | Conduit, fst (L4 under perf-v4); codex-lb (two valid workloads in a full cycle, 3cf779d); mealie (first attempt valid at 10704dc) | construction from the project's resources first (C3, not started); c840697 unverified on codex-lb |
| Measurement and equivalence | perf-v4 (D-060); content comparison with correspondences (dec7ba2); host-load deferral with loads recorded | controls 7 of 7 at 0102ccb and **7 of 7 at the frozen commit 0ea665d** (`stage10-controls/0ea665d`); fst revalidated; deferral exercised on codex-lb (42 waits) | mechanism unobservable where the project's test job runs on SQLite |
| Consistency | reads by POST, whole SQL reads by key pages, a declared comparison before reading, anonymous probe of credentialed endpoints | Aegra (0 of 200 differ, recomputed by the checker) | cases where totals match but records differ; API reads at their bounds (codex-lb) |
| Discovery | unindexed foreign keys; crash probes; authorization deviations | fst, Conduit, Spoolman (absence), Rich (crashes), codex-lb (bearer-only endpoints) | non-FK queries, N+1 (C5); dependencies with known vulnerabilities (future family) |
| Product closing | install walk on one platform (stage 9) | — | the product phase: walks, `doctor` contract, CLI, report, cancel/recover/clean, demo, docs |

**What "improvement" means in 0.9.0**: verified improvements are performance only (perf-v4). Verified findings:
consistency, authorization, crashes. Detectors without a verifier are reported, never promoted.

## Development results (never independent evidence)

- fst: L4 (`item.owner_id` index) confirmed under perf-v4 with the dec7ba2 comparator (+72%, A/A -1%, confirmation
  +71%, same responses), repeatedly (`stage10-revalidation/`).
- codex-lb: two full cycles reaching a measured experiment (3cf779d): checks reproduced, two valid workloads, no
  proven fix twice (-2%, -1%), declined; correct, since the handler's filter is already covered by a unique index.
  The candidate migration failed the project's migration tests (fixed c840697, unverified).
- mealie: valid workload at the first attempt (10704dc), measured on PostgreSQL: +4% with the index used, no
  relevant change. Its stage-8 L4 (SQLite) is not confirmed on that engine.
- Conduit: L4 under perf-v4 (`stage10-regression/v4-3b5b99d`), judged by response digests; not revalidated under
  the dec7ba2 comparator; reported with that validity.
- Aegra: consistency of assistants' total verified (0 of 200 differ); the checks pass outright at run 7.
- Prefect: L4s of B-r14/A-r15/A-r16 outside its CI's tool scope; do not count.
- Level A series: `stage10-campaign/level-a-c840697` .. `level-a-0ea665d`, each README with every block read.

## Independent evaluation results

Stage 9 (`stage9-evaluation.md`): Spoolman and Prefect, four technical blocks, no false promotion. Stage 10
(`stage10-eval/README.md`): codex-lb, Aegra, rag-api; three technical blocks (the checks), zero experiments, zero
false promotions (not evidence of precision), Aegra's assistants total verified by the checker. The campaign's
reserved evaluation: not run (the campaign paused at the gate, D-063).

## Human interventions (stage 10's three applications, the harness's author)

| Application | Minutes of preparation (approx.) | Technical decisions | Auxiliary files written | Corrections to Unbidden it needed (commits) | Until checks ran |
|---|---|---|---|---|---|
| codex-lb | ~45 | dashboard auth mode `disabled`; five schedulers off; SQL seed from its models (its API cannot create accounts) | `bench/ecosystem/codex_lb_lab.py` (compose, seed) | f60bfb4, c4cc783, 6f48b39, bbb0f83, 60da8ac, 3cf779d, c840697 | 3 regression runs (r1-r3); first measured experiment at the 5th full-cycle run |
| Aegra | ~40 | image built from its Dockerfile; cron off; placeholder model key; assistants with distinct configs | `aegra_lab.py` | d582d15, 52e2d8c, d173adc, 0ea665d | 3 runs (r4-r6); passes outright at level A run 7 |
| rag-api | ~35 | lite image; no JWT secret; placeholder embeddings key; chunks tagged as it tags | `rag_api_lab.py` | 0c1df68, 15b694f, cbf1ecf | 3 runs (r7-r9) |
| the other 17 of level A | 0 (clones at pinned commits; no compose, data or role) | none | none | the 20 corrections of the level-A series, none naming a repository | 7 corpus runs |

## Precision and coverage observed

Controls: 7 of 7 at 0102ccb and 7 of 7 at 0ea665d (the evaluator, on the frozen commit). False promotions in evaluations: 0 of 0
promotions (not evidence). Development: one false L4 (stage 8, revoked), none since under perf-v3/v4; correct
abstentions on codex-lb (twice) and mealie. Coverage: 18 of 20 repositories' checks under the stated rule (10 apps
of 11, 8 libraries of 9), 10 outright.

## Cost and latency

Cumulative US$27.72 of US$37.29 at the freeze (US$9.57 available; nothing reset). A full cycle (B-1 + A-1) on a
database application: US$0.06-1.1 and 2-63 minutes per mode (Prefect up to 6 h; codex-lb's 63 min included 24
waiting for a quiet host); a revalidation US$0.03-0.15; checks on 20 repositories: US$0, about 25 minutes.

## Failures and limits

pytest only; discovery limited to foreign keys; Django's runner, JavaScript builds in Python jobs and other
languages out of scope; TimeTracker unstable (an xdist worker dies at the sandbox's limits, no CI baseline of its
own); mealie's L4 not confirmed on PostgreSQL; Conduit's L4 pending the current comparator; c840697 unverified;
workload construction depends on the model where the project's resources are not reused; API reads at their bounds;
no Linux walk yet; a natural improvement on an application nobody prepared for it has not been shown.

## Candidate commit, integration and rollback

Candidate: `0ea665d` on `feat/60-experiments` (version 0.9.0). Integration as `RELEASE.md` proposes (a person
carries it out: cherry-pick a77ef43, `make check`, one pull request; no PR, merge or tag from this work). Rollback:
the previous candidate (stage 9) stays on its branch; every run's records are under `docs/bench/` and
`~/unbidden-lab/<app>-runs/`.
