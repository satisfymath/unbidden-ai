# Results

The one matrix the campaign to v1.0 (`CAMPAIGN-v1.md`) delivers, kept current as runs finish. Development results and
independent evidence are never mixed; every row says who did what (Claude as developer, the harness, Unbidden, the
independent checker). Last updated 2026-10-31, during the campaign's development phase.

## Promise of v1.0 and tested scope

Not yet claimable. Proposed scope: `CAMPAIGN-v1.md` section 1. Tested so far: macOS arm64 native only.

## Capabilities: implemented, demonstrated, pending

| Capability | Implemented | Demonstrated where | Pending |
|---|---|---|---|
| Environment: stack, image, CI plan, checks, coverage and blocks | yes (`observe.scan`, `observe.checks`) | checks reproduced on 9 database applications of the corpus (stage 8-10 records; `stage10-regression/checks`) | the clone and compose as product input (C1); breadth on the 20-repository corpus (level A, pending) |
| CI plan robustness | conditions, matrices (entry on the job's own database), split suites, make, tox, interpreters, workspaces, test requirements, container runtimes, environment, reports | codex-lb, Aegra, rag-api, Prefect, Spoolman (regressions) | measured breadth (level A) |
| Workloads | model-written, validated at the base (D-059); rule-written index over one- and multi-line columns | Conduit, fst (L4 under perf-v4); codex-lb (full cycle at 3cf779d: two valid workloads, no proven fix, correct) | construction from the project's resources first (C3); the candidate migration named in the project's own convention (`migration_name`, after codex-lb's 3 new failures at 3cf779d; unverified on codex-lb until its next cycle); mealie's rerun |
| Measurement and equivalence | perf-v4 (D-060), content comparison with correspondences (dec7ba2), host-load deferral | controls 7 of 7 (`stage10-controls/0102ccb-run4`); fst revalidated; deferral exercised on codex-lb (42 waits, loads recorded) | mechanism not observable where the project's test job runs on SQLite (codex-lb) |
| Consistency | reads by POST, whole SQL reads by key pages, a declared comparison before reading, an anonymous probe of endpoints declared to need a credential | Aegra (0 of 200 differ, recomputed by the checker) | cases where totals match but records differ (tests); API reads at their bounds |
| Discovery | unindexed foreign keys; crash probes | fst, Conduit, Spoolman (absence), Rich (crashes) | non-FK queries, N+1 (C5, after C2/C3) |
| Product closing | install walk on one platform (stage 9) | — | diagnosis, guided config, report, demo, Linux/x86-64 walks |

## Development results (never independent evidence)

See `docs/bench/stage10-regression/` (checks, full cycles), `stage10-revalidation/` (fst confirmed; mealie
unconfirmed), `stage10-controls/`. Level A on the 20-repository corpus: pending.

## Independent evaluation results

Stage 9 (`stage9-evaluation.md`): Spoolman and Prefect, four technical blocks, no false promotion. Stage 10
(`stage10-eval/README.md`): codex-lb, Aegra, rag-api; three technical blocks (the checks), zero experiments, zero
false promotions (not evidence of precision), Aegra's assistants total verified by the checker. The campaign's
reserved evaluation: not run (gate not reached).

## Human interventions (stage 10's three applications, the harness's author)

| Application | Minutes of preparation (approx.) | Technical decisions | Auxiliary files written | Corrections to Unbidden it needed (commits) | Until checks ran |
|---|---|---|---|---|---|
| codex-lb | ~45 | dashboard auth mode `disabled`; five schedulers off; SQL seed from its models (its API cannot create accounts) | `bench/ecosystem/codex_lb_lab.py` (compose, seed) | f60bfb4, c4cc783, 6f48b39, bbb0f83, 60da8ac, 3cf779d | 3 regression runs (r1-r3); first measured experiment at the 5th full-cycle run (3cf779d) |
| Aegra | ~40 | image built from its Dockerfile; cron off; placeholder model key; assistants with distinct configs | `aegra_lab.py` | d582d15, 52e2d8c, d173adc | 3 runs (r4-r6) |
| rag-api | ~35 | lite image; no JWT secret; placeholder embeddings key; chunks tagged as it tags | `rag_api_lab.py` | 0c1df68, 15b694f, cbf1ecf | 3 runs (r7-r9) |

## Precision and coverage observed

Controls: 7 of 7 (the evaluator); false promotions observed in evaluations: 0 of 0 promotions (not evidence);
development: one false L4 (stage 8, revoked), none since under perf-v3/v4. Coverage: pending level A.

## Cost and latency

Cumulative US$27.69 of US$37.29 (2026-10-31, after the codex-lb full cycle at 3cf779d: US$0.34, 63 min, of which about 24 waiting for a quiet host). A full cycle (B-1 + A-1) on
a database application: US$0.06-1.1 and 2-20 minutes per mode (Prefect up to 6 h per mode); checks only: US$0.

## Failures and limits (open)

Workload construction depends on the model where the project's resources are not reused (C3); API reads at their
bounds (codex-lb's request logs at 100,000); discovery limited to foreign keys; no Linux walk. Promotions judged
before the content comparison of dec7ba2: fst revalidated under it (holds); Conduit's L4 of `stage10-regression/
v4-3b5b99d` (judged by response digests) is pending revalidation under it and is reported with that validity until
then; mealie's L4 unconfirmed.

## Candidate commit, integration and rollback

None proposed. Stage 9's integration proposal (`RELEASE.md`) stands as the shape; a candidate is named only when the
exit criteria hold.
