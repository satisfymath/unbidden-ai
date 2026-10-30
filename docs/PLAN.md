# Plan: the next stage

Decision D-039. Verified against `feat/20-scale-eval@6a70947` on 2026-10-28.

## Context

The master document (`/Users/david/unbidden/docs/UNBIDDEN_Proyecto_Maestro_2026.md`, "Master") describes a private,
proactive, self-extending intelligence: it understands an environment, finds opportunities without tickets, decides
what to investigate, acquires missing capabilities within its permissions, experiments, and proves value (L1–L6).
An external review of `feat/20-scale-eval@2c191a6` found working components with weak connections, doubtful
evaluation validity and unproven generalization. This plan verifies that review against the current code
(`feat/20-scale-eval@6a70947`), corrects it, and turns it into a dependency-ordered sequence of small PRs that keeps
the ambition while making every claim trustworthy first.

**State verified.** Since `2c191a6`: 3 commits (`8aa0691` LanguageAdapter + Go with real-sandbox conformance;
`88f8f19` discovery audit; `6a70947` mealie L5 protocol). One untracked file, `docs/bench/eval/dev-all-v4.json`, is the
output of a v4 benchmark run still in progress (preserved, not interpreted here). No other local changes. Repo has no
CLAUDE.md/AGENTS.md; conventions come from `docs/ARCHITECTURE.md` and `docs/DECISIONS.md` (append-only, English).

Verification method: code read with file:line evidence; in-memory reproductions (no files written, no containers);
regex timings in killed subprocesses. Labels: **CONFIRMED** (reproduced), **CONFIRMED-static** (unambiguous code
path, not executed), **RESOLVED**, **INCORRECT**, **DESIGN LIMITATION**, **HYPOTHESIS**.

---

## 1. Diagnosis

**What works, shown in real runs.** Index found, written, measured (13.0→4.1 ms, L4), merged and deployed on
full-stack-fastapi-template (D-010/13); outage drill with rollback in 15 s (D-015); Rich crashes found blind and fixed
(L4, D-018); mealie index L3 on SQLite (reported as L4 in D-035; re-judged in D-040); Forge readers judged by a model-free oracle on unseen real data
(D-016, D-025); spend ledger reconciled to the cent; static evaluation reach 13/32 → 18/32 on validation (5 gained,
0 lost, p = 0.0625) and 8/15 → 13/15 on dev; the Director's CI rules declined thousands of environment findings.

**What does not yet hold.**
- *Evidence validity:* L4 can be granted when no test ran (A). Opportunity memory is erased by every rescan of a new
  commit (G1, new). CI-based declines trust a substring and a green that includes cancelled jobs (B).
- *Autonomy loop:* self-extension, investigation and continuous mapping exist as parts but are not wired into the
  autonomous cycle (C, D). The Director is a rule table with fixed constants (E). Memory is stored, mostly not used (G).
- *Safety boundaries:* several controls are declarative, not effective: build network, regex execution time,
  cancellation, kill switch reach, capture network, capability approval for stats readers (F, C).
- *Proof of value:* no valid L5 exists; no L6 logic; claims are never downgraded (J). Discovery precision on what the
  Director keeps is low: 1 of 7 repositories held a defect worth fixing (`docs/bench/eval/discovery-audit-v3.md`).

**What separates the product from the vision.** Not missing components so much as missing *contracts between them*:
a shared notion of valid evidence, of a capability need, of source freshness, of opportunity history, and a Director
that chooses among investigate / measure / acquire / experiment / abstain with real estimates. Coverage grew;
capability to improve systems has not been shown to grow with it.

---

## 2. Vision – implementation – evidence – gap

| Vision (Master) | Implementation (files) | Evidence | Gap |
|---|---|---|---|
| Opportunities without tickets (§6.1 L151–163, §14) | `observe/scan.py`, `world/checks.py`, `research/robustness.py`, `daemon/cycle.py` | Real: fst index, Rich crashes, mealie index; corpus audit 1/7 useful | Discovery precision low; probes are samples (humanize 1/13) |
| Continuous observation (§6.1 L161, §14.1 L559–565) | `daemon/loop.py:30-66` probes/logs/health; `discover` only after HEAD moves (`cycle.py:92-114`) | Deploys detected per round (real) | Map, checks, needs not refreshed without a commit (D) |
| Decide what to investigate; VOI (§15.2–15.3 L604–624) | `director/decide.py` fixed table, `p=0.6/(1+attempts)`; ordering by level, age (`cycle.py:221`) | Unit tests only | No VOI, no global budget, no INVESTIGATE/ACQUIRE actions; `research.investigate` never enqueued |
| Acquire missing capabilities, no new privileges (§9.3 L351–364, §13) | `forge/` (log adapters, stats readers, oracle, cards, reuse) | Real: 1,029/1,029 and 1,770 lines | Builds are CLI-only; stats readers used without approval (C) |
| Valid experiments (§16.1, §20.4) | `lab/evaluator.py`, `lab/testsuite.py`, three labs | Real L4s | L4 without tests run; inconsistent rules across labs (A) |
| L5 with confounders, L6 persistence (§16.2 L690–699) | `operate/ledger.py`, `observe/live.py:_outcomes`, `observe/impact.py` | Unit tests; real D-036 outcome = invalid | No valid L5; L6 never assigned; no downgrade; probes ≠ user traffic (J) |
| Local-first privacy (§11.1, §12, §17.4) | `brain/route_policy.py`, `bridge/`, `guardian/egress.py` | Real routing audits (D-018/19) | Structure and constants leave renamed code (documented); screenshots unscanned (F) |
| Guardian, effective limits (§17.2 L724–736) | `sandbox/runner.py` (effective), `provision.py` (declarative), `killswitch.py` | Runner limits verified | Build egress, regex time, cancellation, kill switch reach (F) |
| Memory that improves decisions (§10.3 L393–405) | store collections; Forge reuse; `attempts` | Forge reuse real | Decisions/hypotheses/experiments never read back; G1 erases history |
| Activity & Outcomes, no chatbot (§6.3 L177–190, §29.1 L1128) | CLI `inbox/why/show/deploys/spend/forge` | — | No aggregated outcomes, learning, held-or-not, cost per outcome (J) |
| Beyond software (§5.2, §18, Fase 4) | none | — | Out of scope now; keep contracts domain-neutral |

---

## 3. Findings, verified and prioritized

Severity: **S1** corrupts evidence or violates the mandate in autonomous mode; **S2** blocks the vision's loop or makes
results misleading; **S3** quality/scale. Confidence is about the finding, not the fix.

| # | Finding | Review said | Verdict | Sev. | Evidence | Proposed solution (PR) |
|---|---|---|---|---|---|---|
| A1 | Both sides `["<suite>"]` 3/3 → `improved`, L4, `pre_existing` | yes | **CONFIRMED** | S1 | `evaluator.py:28-42,71-77`; `testsuite.py:67,125-158` | Test-evidence contract (PR1) |
| A2 | Base fails 1/3, candidate 3/3 → `pre_existing`, L4 | yes | **CONFIRMED** (reverse too) | S1 | `evaluator.py:34,40-41` | PR1 (flakiness and per-test deltas) |
| A3 | RobustLab L4 with `inconclusive` | yes | **CONFIRMED** (real `RobustLab.run` with fakes) | S1 | `robust.py:181-182` | PR1 (one judge for all labs) |
| A4 | Not collected = passed (pytest exit 5; exit-only runners without report) | — | **CONFIRMED** (new) | S1 | `testsuite.py:133-135` | PR1 |
| A5 | Propose ignores `verdict.tests`; merge ignores the PR's own CI; merges on first poll; deploy has no evidence check | partly | **CONFIRMED-static** (new detail) | S1 | `decide.py:136-144`; `publish/github.py:239-240,82-86`; `cycle.py:466-488`; `operate/deploy.py:47-56` | PR5 |
| G1 | Rescan at a new commit replaces `opp.details`: attempts, verdict, decision, reopened lost; L4 opportunity waits forever | — | **CONFIRMED** (new) | S1 | `observe/analyzers.py:129` | PR2 |
| B1 | `_verdict`: cancelled, neutral, skipped, stale, None → green | yes | **CONFIRMED** | S1 | `ci.py:349-353`, `tool_status` `:396` | PR3 |
| B2 | Partial state (only completed runs; one page, no pagination) cached per commit without expiry; `None` cached too | yes (only "except unreadable") | **CONFIRMED** (worse: `None` frozen) | S1 | `ci.py:345`; `cycle.py:64,293-301` | PR3 |
| B3 | Decline needs only `tool in ci_commands` (substring): `tsc`⊂`tsconfig`, `[tool.mypy]` in pyproject via tox, format-check counts as lint; no file/path, rules, config, version equivalence; DECLINED is terminal | yes | **CONFIRMED** (7 false declines reproduced) | S1 | `decide.py:102,111,117-124`; `ci.py:248-285,390,393`; `cycle.py:271-273` | PR4 |
| F2 | Regex admission misses alternation/optional forms; oracle times after matching, in-process; an accepted pattern takes 3.0 s–>5 s on 39 chars; production reads run in the probe thread | yes | **CONFIRMED** (4 accepted patterns ≥3 s or hung) | S1 | `forge/adapter.py:46-47,117-138`; `forge/stats.py:85-103,153-162`; `health.py:390-417` | PR6 |
| C1 | Stats readers used autonomously without approval or mandate (`use_new_capabilities` ignored); `forge approve` cannot approve stats | — | **CONFIRMED** (new) | S1 | `forge/stats_build.py:255-262`; `health.py:611`; `cli.py:682-698` | PR6 |
| F1 | `docker build` has full network; registries are a declared check; `runtime.stack_and_images` and `_scan_services` provision **with no policy check at all** | first half | **CONFIRMED** (bypass reproduced) | S1 | `provision.py:1-5,432-434`; `runtime.py:106-116`; `scan.py:47,184` | PR7a, PR7b |
| F3 | `wait_for` around `to_thread` leaves the work running; retries can run the same job concurrently | yes | **CONFIRMED** | S2 | `loop.py:128-131`; repro thread alive after timeout | PR8 |
| F4 | Kill switch blocks new jobs and Brain calls only; not running containers, in-flight handlers, pushes, merges, deploys, `visual_judge` | yes | **CONFIRMED-static** | S1 | `killswitch.py`; `loop.py:117`; `router.py:216`; `publish/*`, `operate/*`, `lab/ui.py:185` | PR8 |
| F5 | Playwright capture: default bridge network (internet + host gateway), no read-only/user/pids; screenshots kept forever; images not scanned | yes | **CONFIRMED-static** | S2 | `lab/ui.py:40-82`; `health.py:486-512`; `egress.py:67-89` | PR9 |
| F6 | Renamed code still leaves structure, constants, short names | yes | **DESIGN LIMITATION** (already in ARCHITECTURE "Not guaranteed") | S3 | `bridge/rename.py:321-402` | Keep documented; `local` profile for sensitive shapes |
| F7 | `discover()` blocks the event loop so `wait_for` cannot fire | — | **HYPOTHESIS** | S3 | `world/discover.py` sync calls | Measure in PR8 |
| C2 | Need recorded only as a BlindSpot suggesting a CLI command; no job builds, no resume; `research.investigate` never enqueued | yes | **CONFIRMED** | S2 | `discover.py:118-136`; `cycle.py:70-83` | PR10 |
| D1 | Map, checks and needs refresh only when HEAD moves; table-scan rates use a window = time between commits; topology changes unseen; source recovery waits for next map | yes | **CONFIRMED-static / DESIGN** (deploys are seen: RESOLVED) | S2 | `cycle.py:92-114`; `checks.py:31-71,160-167`; `reconcile.py:62-100` | PR11 |
| E1 | Fixed category values, constant cost, `p=0.6/(1+n)`; ordering by level then age; no cross-opportunity budget; L3 declined terminally; `reopen()` has no production caller | yes | **CONFIRMED** | S2 | `decide.py:21-37,62-71,145-156,170-188`; `cycle.py:221,243` | PR12 |
| G2 | decisions, hypotheses, experiment measurements, lab notes never read for decisions | yes | **CONFIRMED** | S2 | per-collection table in investigation notes | PR13 |
| H1 | Python/Node hard-coding: probes, perf, CI parity, `checked_dirs` ignores Go, FixLab falls back to node syntax; declared `probe`/`perf` capabilities never consulted | yes | **PARTIALLY RESOLVED** by `8aa0691` (contract + Go) | S2 | `cycle.py:126-167,347,507`; `lab/perf.py:402-629`; `fixlab.py:177,410` | PR17 |
| H2 | Subproject findings always WAIT; lab has no per-subproject environment | yes | **CONFIRMED** | S2 | `decide.py:88-91`; `scan.py:149-199`; `cycle.py:85-88` | PR18 |
| J1 | No L6; outcome recorded once and never re-checked; no `outcome.invalidated`; levels only rise (`max`) | yes | **CONFIRMED** | S2 | `live.py:299`; `contracts/common.py`; `fixlab.py:439`, `robust.py:223`, `perf.py:707` | PR14 |
| J2 | Impact from Unbidden's own probes only (5 GETs per round, parameterless endpoints) | yes | **CONFIRMED** (stated as confounder) | S2 | `probe.py:99-128`; `live.py:320` | PR14 (traffic signals via Forge log readers) |
| I1 | Review's evaluation claims (13→18/32; holdout 0/7 L4; Rich/DB useful; mealie L4 not L5) | yes | **CONFIRMED** with qualifiers: all wins on development systems; program holdout (28) not yet run; EVIDENCE.md "20 repositories" wording imprecise | — | `docs/bench/eval/PROGRESS.md`, `2026-10-28-scale-holdout.md`, D-036 | §6 |

What I could not verify: actual network traffic of a `docker build` (read, not observed); F7; the v4 benchmark result
(running); Go adapter behavior on the corpus (only the conformance fixture); anything requiring Meta credits.

---

## 4. Target architecture, incremental

**Kept as is:** SQLite store, events/audit append-only, job queue; sandbox runner (its limits are effective); Brain,
routing, spend ledger; Guardian policy engine; world-model provenance and reconcile; deploy ledger; the three labs'
mechanics; Forge's data-only capability model and model-free oracle; LanguageAdapter contract.

**Contracts that change or appear (each replaces an implicit convention, none is a framework):**

1. **TestEvidence** (`contracts/experiment.py`, `lab/testsuite.py`, `lab/evaluator.py`). Per round:
   `status ∈ {ran, not_collected, infra_failed}`, `collected`, `failed` names, `exit`. One judge,
   `judge_tests(base, cand) → {outcome, reasons}` with outcomes `PASSED`, `PRE_EXISTING_STABLE`, `REGRESSION`,
   `FLAKIER`, `NOT_RUN`, `INFRA_FAILURE`. Used by all three labs. Level rules: L4 only with `PASSED` or
   `PRE_EXISTING_STABLE` (identical failing set in every round on both sides) and `collected > 0` on both sides;
   `FLAKIER`/`NOT_RUN`/`INFRA_FAILURE` cap at L3 and are retried or reported, never proposed. Coverage starts minimal
   and honest: "no test collected" is insufficient; per-file coverage is later and only if measured to matter.
2. **Opportunity history** (`contracts/opportunity.py`, `observe/analyzers.py:record_report`). `details` split into
   `observation` (rewritten by scans) and `history` (attempts per commit and total, verdicts, decisions, reopenings,
   outcomes: append-only). Fixes G1; is the substrate for memory (G).
3. **CI evidence** (`observe/ci.py`). States `success, failure, pending, skipped, cancelled, neutral, unknown`;
   a commit-level summary that is `partial` while any run is pending. Cache only terminal, complete summaries, with
   TTL. **ToolCheck**: the CI job's invocation parsed into tokens (argv, not substring), its path scope, config file
   and tool version (from the lockfile). Decline-as-environment only when: job `success`, invocation is the same
   tool and subcommand, the finding's path is inside its scope, same config file, same locked version. Otherwise a
   new outcome `CI_DISAGREES` → `INVESTIGATE` (bounded), never terminal DECLINE.
4. **CapabilityNeed** (new entity, `contracts/capability.py`; job `forge.build`). Fields: kind, source, evidence,
   requested permissions (must be ⊆ mandate; Forge cannot widen), status `open → reusing | building → validated →
   approved → in_use → retired | failed | abandoned`, cost so far, utility observed. One use gate,
   `capabilities.usable(store, mandate, kind, source)`, shared by log and stats readers (closes C1).
5. **Source freshness** (`world/connectors.py`, new `observe.source:<name>` jobs). Each connector declares interval,
   cost class and whether it may call a model; the scheduler refreshes stale sources independently of HEAD;
   reconcile per source; checks re-evaluated on facts that changed; opportunities deduplicated by key and reopened
   when evidence returns. Model-backed inference (endpoint→tables) cached by content hash, never per interval.
6. **Director v2** (`director/decide.py`, `daemon/cycle.py`). Actions: `INVESTIGATE, MEASURE, ACQUIRE_CAPABILITY,
   EXPERIMENT, PROPOSE, WAIT, ABSTAIN` (DECLINE kept as explicit abstention with reason). Utility in one unit (expected
   net value in human-hours saved, an explicit, editable mandate table) minus total cost (model US$, compute minutes,
   expected human review minutes). Probabilities from Beta-binomial counts per (source, category, language) over
   history, with the current constants as priors. Global selection: highest expected net value per unit cost within
   a per-cycle budget. VOI used only for one decision where it is cheap to compute: whether to MEASURE/INVESTIGATE
   before EXPERIMENT. No bandits/RL until the history has hundreds of labelled outcomes.
7. **Execution boundary** (`daemon/loop.py`, `forge/*`, `operate/*`, `publish/*`). Long jobs run in a child process
   with a lease, killable on timeout and on kill switch; containers labelled per job and killed with it; external
   effects (push, merge, deploy, remote calls including `visual_judge`) check the kill switch immediately before
   acting. Untrusted regexes execute only through a bounded executor (RE2 if adopted, otherwise a subprocess with a
   hard timeout), in the oracle and in production.
8. **Outcome lifecycle** (`observe/live.py`). Outcomes re-checked on scheduled windows; `outcome.held` → L6 after the
   mandate's persistence period; `outcome.invalidated` downgrades the opportunity and records why. Traffic-based
   signals (from Forge log readers) reported beside probe results, never mixed.

**Migrations:** history split migrates existing `details` (copy current keys into `history`, keep raw for audit);
CI cache is in memory (no migration); verdicts recorded before PR1 keep their level but get a `criteria: v1` tag and
are re-judged where raw test data exists; nothing deletes evidence.

---

## 5. Roadmap by dependency

Estimates are in working days of implementation plus review, as ranges; they are not dates.

**Phase 0 — evidence you can trust** (blocks every later measurement)

| PR | Goal | Scope / files | Tests | Acceptance | Risk | Est. |
|---|---|---|---|---|---|---|
| 1 | One test-evidence contract and judge for all labs | `contracts/experiment.py`, `lab/testsuite.py`, `lab/evaluator.py`, `lab/fixlab.py`, `lab/perf.py`, `lab/robust.py` | A1–A4 reproductions as failing-then-passing unit tests; per-lab tests; JUnit `tests` attribute read | No path grants L4 without tests run on both sides; FLAKIER/NOT_RUN/INFRA cap at L3 | Fewer L4 in benchmarks (intended) | 1.5–3 |
| 2 | Opportunity history survives rescans | `contracts/opportunity.py`, `observe/analyzers.py`, `director/decide.py`, `daemon/cycle.py`; migration | G1 reproduction; attempts total vs per commit; reopen path | Verdict and attempts persist across HEAD moves; `reopen` reachable by policy | Migration of live workspaces | 1–2 |
| 3 | CI state model and cache | `observe/ci.py`, `daemon/cycle.py` | each conclusion; pending→partial; pagination; TTL; `None` not frozen | Cancelled/neutral never green; no partial cached | GitHub API shapes | 1–2 |
| 4 | CI equivalence for environment declines | `observe/ci.py` (ToolCheck), `director/decide.py` | the 7 false declines → not declined; the correct decline still declined; `CI_DISAGREES` → INVESTIGATE | Zero false declines on the fixture suite; dev rerun shows declines only with equivalence | Fewer declines → more noise until PR12 | 2–4 |
| 5 | Proposal, merge and deploy gates | `director/decide.py`, `publish/github.py`, `daemon/cycle.py`, `operate/deploy.py` | merge waits for PR CI success; tests outcome required for propose; deploy checks evidence of merged proposals | No merge on pending/failed PR CI | Slower autonomy | 1–2 |

**Phase 1 — boundaries that are effective, not declared** (can run in parallel with Phase 0 after PR1)

| PR | Goal | Files | Tests | Acceptance | Risk | Est. |
|---|---|---|---|---|---|---|
| 6 | Bounded regex execution + one capability use gate | `forge/adapter.py`, `forge/stats.py`, `forge/stats_build.py`, `forge/logs.py`, `observe/health.py`, `cli.py` | the 4 accepted catastrophic patterns refused or time-bounded; stats use denied under `deny` | No untrusted regex can exceed its bound; stats need approval | RE2 dependency (decision 2) | 1.5–3 |
| 7a | Policy check on every provisioning path | `runtime.py`, `observe/scan.py` | deny-all mandate → no provision from runtime or subprojects | Bypass closed | none | 0.5–1 |
| 7b | Build egress actually restricted | `sandbox/provision.py`, new egress proxy on an internal network | a build that reaches an unlisted host fails | Only listed registries reachable from builds | Proxy compatibility with npm/uv/go; spike first | 3–6 |
| 8 | Cancellation and kill switch with real reach | `daemon/loop.py`, `daemon/cycle.py`, `publish/*`, `operate/*`, `lab/ui.py` | job killed on timeout (no live thread); kill switch stops a running container and blocks push/merge/deploy | Verifiable kill semantics, documented per effect | Process boundary for jobs | 3–5 |
| 9 | Capture confinement and retention | `lab/ui.py`, `observe/health.py`, mandate field | capture cannot reach the internet; artifacts pruned by mandate retention | Network scoped to the app; retention enforced | Pages needing CDNs render differently (said) | 1–2 |

**Phase 2 — the loop the vision describes**

| PR | Goal | Files | Acceptance | Est. |
|---|---|---|---|---|
| 10 | CapabilityNeed + `forge.build` job + resume | `contracts/capability.py`, `world/discover.py`, `forge/*`, `daemon/cycle.py` | A detected need is built, validated by the oracle, approved per mandate, used, and the waiting investigation resumes, with no CLI | 3–5 |
| 11 | Per-source observation scheduler | `world/connectors.py`, `world/discover.py`, `world/checks.py`, `daemon/*` | Data growth, topology change and source recovery each produce/reopen opportunities without a commit; model calls only on changed content | 3–5 |
| 12 | Director v2 (simplest evaluable policy) | `director/decide.py`, `daemon/cycle.py`, mandate value table | Global selection under budget; INVESTIGATE/MEASURE/ACQUIRE used; beats current policy and act-on-everything on the decision benchmark (§6) | 3–5 |
| 13 | Memory that changes decisions | `director/`, `lab/` (lab notes fed back), store queries | Out-of-sample: fewer wasted experiments at equal discoveries vs no-memory ablation | 2–4 |

**Phase 3 — value the user can see**

| PR | Goal | Acceptance | Est. |
|---|---|---|---|
| 14 | Outcome lifecycle: re-check, L6, invalidation, traffic signals beside probes | An outcome can hold (L6) or be downgraded, visibly | 2–4 |
| 15 | Activity & Outcomes (`unbidden activity` + static HTML report, no server) | Shows discovered, investigating, declined and why, built, awaiting approval, improved and held, spent, learned | 2–3 |
| 16 | Evaluation harness v2 (§6) | Seeded and healthy scenarios, baselines, ablations, local-model cycle | 3–6 |

**Environments (after Phase 0; expand only on measured benefit)**: PR17 consult declared capabilities everywhere
(probes, perf, CI parity per adapter, `checked_dirs` for all adapters); PR18 subproject lab context (per-directory
stack/images, `tool@dir`, cwd-aware FixLab/testsuite). Go's measured benefit (v4 run) decides whether Rust/PHP come next.

---

## 6. Evaluation protocol

Separate evaluations, one per capability, never pooled into one score:

| Capability | Dataset / scenario | Metric (denominator) | Baselines |
|---|---|---|---|
| Coverage | corpus-2026-10-28 dev/val/holdout (100) | reach per stage (all repos); root causes | prior versions, paired McNemar |
| Discovery | **Seeded suite**: dev-split repos with evaluator-known defects injected on a branch (crash, unindexed FK under load, duplicated test class, mutation of a guard) + **healthy controls** (unchanged repos with audited zero valuable findings) | recall of seeded defects; precision of kept opportunities (audited); false-alarm rate on healthy | static rules (act on all findings); full Unbidden |
| Decision | Recorded opportunity sets with audit labels (from discovery audits) | regret vs oracle choice under budget; wasted experiments; abstention correctness on healthy | current policy, act-on-everything, static priority |
| Capability acquisition | Held-out real log/stats samples of formats never seen; needs from the seeded suite | build success, oracle pass on unseen lines, reuse rate, time-bounded execution | no-Forge ablation (need stays open) |
| Experimentation | Lab runs on seeded defects; planted invalid evidence (suite not run, flaky test) | false-L4 rate (must be 0 on planted cases); L4 rate on real defects | — |
| Operational impact | mealie SQLite L5 (pre-registered protocol), fst; later forks | valid L5 count, outcome classes, confounders | — |
| Local-first | Tier F with profile `local` (Glimmer) on a dev subset | same metrics as remote, cost in compute minutes | remote Spark (only with verified balance) |

Rules: dev for debugging; validation only with frozen versions; the program holdout (28) run once with the final
candidate. Wilson intervals, exact McNemar for paired binaries, bootstrap for continuous; denominators always stated;
negative results kept. Budget: static and local tiers first (US$0); remote tiers and the tool-agent baseline only
after a verified balance, capped per run by the spend ledger. Promotion of a version: no regression on dev reach,
false-L4 = 0 on planted cases, discovery precision and decision regret not worse on validation, explained per
repository.

---

## 7. First vertical slice

**Scenario:** mealie on SQLite, in a separate worktree and compose project (protocol already registered:
`docs/bench/2026-10-28-mealie-l5-protocol.md`), with data seeded to a large household.

1. **Discovery without a commit:** the per-source scheduler (PR11) refreshes the database connector as data grows;
   the unindexed-FK check re-scores the opportunity by rows and endpoints.
2. **Missing capability:** no reader exists for mealie's access-log format → a CapabilityNeed (PR10); Forge builds a
   log adapter, the oracle validates it on unseen lines, the mandate's approval gate admits it (PR6 gate); it is used
   to count real requests per endpoint.
3. **Decision:** the Director (PR12) prioritizes the opportunity by observed traffic and chooses MEASURE → EXPERIMENT.
4. **Valid experiment:** PerfLab measures on SQLite, the engine in use, with TestEvidence (PR1): tests collected and
   run on both sides.
5. **Operational result:** two `verified` deploys by Unbidden (baseline `e31c5fc`, change `a351dc2`), live probes,
   outcome classified per criteria v2, re-checked later (PR14).
6. **Explainable result:** `unbidden activity` (PR15) shows the chain with costs and evidence level, whatever the
   outcome (a negative result is a valid demonstration).

Plus an **abstention control**: a healthy repository from the audit where Unbidden must find nothing worth doing and
say so. Minimum for the slice: PR1, PR2, PR6 (gate part), PR10, PR11 (database + logs sources), PR12 (minimal),
PR15 (minimal). PR14 is needed only for the re-check step.

---

## 8. Product plan

- **Onboarding:** `unbidden init` → mandate with objectives stated as a value table (hours saved per category, risk
  appetite) → `doctor` → first discovery report within the first cycle, including what it cannot see. No chat needed.
- **Daily operation:** `watch` as a background service; the user opens `unbidden activity` (or its HTML report) to
  approve, release holds, read outcomes; notifications only for approvals and invalidated outcomes.
- **Visibility of value:** per outcome: evidence level, confounders, cost (US$ + compute + review minutes), and
  whether it held; an aggregate "verified net value per unit of cost" (Master §28.1) computed only from L5/L6.

---

## 9. Open decisions (each with a default)

1. **Hackathon (Nov 4) vs this sequence.** Default: Phase 0 PRs 1–3 plus PR6's capability gate before the demo; the
   demo shows real evidence (including the corrected L4 rules) rather than new features. Consequence: the vertical
   slice lands after the deadline.
2. **Bounded regex execution:** add `google-re2` (linear-time, but a native dependency and a subset of syntax) vs a
   subprocess with timeout (no dependency, slower). Default: RE2, with patterns RE2 cannot express refused.
3. **Build egress (PR7b):** an allowlisting proxy on an internal network vs accepting the documented limitation for
   now. Default: PR7a now, PR7b after Phase 0.
4. **Remote spend:** verify the Meta balance to unlock tiers P/F and the tool-agent baseline. Default: run local
   (Glimmer) tiers first; remote only after verification.
5. **Interface:** CLI + generated static HTML (consistent with D-001) vs a web app (Master suggests Next.js).
   Default: CLI + static HTML now.

---

## 10. Next concrete step

**First PR: PR1, the TestEvidence contract and one judge for FixLab, PerfLab and RobustLab.** It changes what every
later number means, so it goes first.

**Condition to start the next PR:** the A1–A4 reproductions exist as unit tests and pass (no L4 without tests run on
both sides, no `pre_existing` that hides a worsening, RobustLab follows the same judge), the full suite and pyright
are green, and the existing L4 records (D-010, D-018, D-035, pilots) are re-judged with the new contract where raw
data exists, with the results written as D-040 — including any that no longer hold.

**Firm sequence:** PR1 → PR2 → PR3 → PR4 → PR5 (evidence) ‖ PR6 → PR7a → PR8 → PR9 (boundaries) → PR10 → PR11 →
PR12 → PR13 (loop) → PR14 → PR15 → PR16 (value and evaluation); PR17/18 and new languages only when the evaluation
shows they are the limiting factor.

---

## Verification of this plan once implemented

Per PR: unit tests that reproduce each finding first (failing on the old code), then the suite, ruff, pyright; for
PR6–PR9 adversarial local tests (catastrophic regexes, deny-all provisioning, kill during a running container and
before a push, capture reaching an external host); for PR10–PR12 an end-to-end run of the vertical slice; for every
phase, a paired static rerun of dev and a frozen validation rerun with `bench/compare.py`, and an updated
`docs/bench/eval/PROGRESS.md`. This document is `docs/PLAN.md`; its decision is D-039 in `docs/DECISIONS.md`.

---

## Status, 2026-10-28

One stacked branch per PR on `origin` (satisfymath), each on the one before; no pull request opened. Every PR: the
finding reproduced as a test first, then the full unit suite (445), ruff and pyright clean.

| PR | Branch · commit | State | Shown beyond unit tests |
|---|---|---|---|
| 1 Test evidence | `feat/21-test-evidence` · ad11f06 | done | 24 recorded experiments re-judged (D-040): mealie D-035 is L3, not L4 |
| 2 Opportunity history | `feat/22-opportunity-history` · 43e84f3 | done | — |
| 3 CI states | `feat/23-ci-states` · cf660e7 | done | — |
| 4 CI equivalence | `feat/24-ci-equivalence` · 32f254c, `feat/34-ci-package-runners` · 85c9d03 | done | dev v4 → v5: Cirq's false decline ("copyright") gone; a gap (`bunx typescript@7`) found and fixed |
| 5 Propose / merge / deploy gates | `feat/25-action-gates` · e6a5afb | done | — |
| 6 Bounded regex + use gate | `feat/26-bounded-regex` · 8f12735 | done | the accepted patterns hang `re` (two past 5 s on 30 chars); RE2 runs them in < 0.1 ms |
| 7a Provisioning policy | `feat/27-provision-policy` · 4ffb241 | done | Go conformance e2e passes with the policy |
| 7b Build egress proxy | — | not started (after Phase 0, as planned) | — |
| 8 Kill reach | `feat/28-kill-reach` · 2cb49e9 | done | a labelled sandbox container killed in 3 s; 11 other containers untouched |
| 9 Capture confinement | `feat/29-capture-confinement` · e743e37 | done | a real capture: page loaded through the relay, internet requests failed, nothing left behind |
| 10 Capability needs | `feat/30-capability-needs` · 4991395, fab9344 | done; the Director does not yet put work on a need | — |
| 11 Map refresh | `feat/31-source-refresh` · 6b2e9de | done; one interval for all runtime sources | — |
| 12 Director v2 | `feat/32-director-v2` · 8f2a9ba | partial: learned p, value table, budget by expected value; no INVESTIGATE / MEASURE / ACQUIRE yet | — |
| 13 Memory in decisions | — | not started; PR12's learned p is its first use; acceptance needs PR16 | — |
| 14 Outcome lifecycle | `feat/33-outcome-lifecycle` · 7de1479 | done (re-check, L6, invalidation); traffic signals not yet | — |
| 15 Activity | `feat/35-activity` · 382b1a3 | done (CLI, JSON, static HTML) | on a copy of mealie's state: flags D-035's L4 as not granted today |
| 16 Evaluation v2 | — | not started | — |

Evaluation: dev v5 (PR1–PR9) paired with v4, reach unchanged, four decisions changed and read
(`docs/bench/eval/PROGRESS.md`). Validation and holdout untouched. US$0 of API.

Mealie L5: run under amendment 1 (D-041, `docs/bench/2026-10-28-mealie-l5-result.md`). D-035's suite failure was
diagnosed (xdist over the sandbox's memory, fixed in `feat/36-xdist-workers` · 09d0d14); the lab evidence was
revalidated to L4 with today's evaluator; the live result between two verified deploys is positive (11.8 → 2.2 ms,
probe traffic only). L6 is not claimed: it needs re-checks over the persistence period.

## PR12 completed and PR13 clarified (2026-10-28, before the code)

**PR13, as this plan defines it** (G2, §5 table): decisions, hypotheses, experiment measurements and lab notes are
stored but never read when deciding. PR13 makes that memory change decisions (`director/`, lab notes fed back,
store queries), accepted only out of sample: fewer wasted experiments at equal discoveries against a no-memory
ablation. It depends on PR12 (a Director that has somewhere to use what it remembers: PR12's learned success
chance is the first such use) and on PR16 (the ablation needs scenarios with a known truth and repeated runs).
So: PR12's actions first, then PR16's scenarios to measure them, then PR13's ablation on those scenarios.

**PR12's three actions**, each routed through a mechanism that already works, no second flow:

| | MEASURE | ACQUIRE_CAPABILITY | INVESTIGATE |
|---|---|---|---|
| Resolves | the value of a world opportunity depends on an observation not made yet (a table's rows unknown) | deciding needs a capability that does not exist (traffic per route sits in a log no reader parses) | the cause of a runtime signal is unknown |
| Evidence it needs | the table's row estimate from the database connector | a validated reader for the service's access log | the incident's good and bad versions and its signal |
| Mechanism, permissions | `world.refresh` (PR11), `runtime.read`; no model | `forge.build` (PR10): `capability.build` (local model, under `run_experiments`), then the one use gate | `research.investigate` (exists; live.py already queues it for incidents), local model |
| Budget | at most 3 refreshes per opportunity and commit; no model | Forge's: 2 builds per need, local only | the investigation's own step limit, local only |
| Ends | rows observed: decided normally; 3 refreshes without them: waits, "cannot be measured", until the commit changes | need in use: what waited resumes; awaiting approval: waits for a person; abandoned: decided without it, saying so | a hypothesis is recorded, or none |
| Returns | `run_checks` writes the rows into the opportunity | the need's `resume` queues a sweep | the hypothesis, recorded with its subject |
| Cannot repeat | count per opportunity and commit in `details.measure`; idempotent job keys | one need per (kind, source); attempts capped | one per opportunity and reopening (job key) |

Plus one decision fixed from the dev scenarios: a style finding (lint, format) in files the team's own linter is
not run on is declined; the scope is the linter's invocation (PR4's argv reading), not where test steps run.

INVESTIGATE has no PR16 scenario yet (its inputs are incidents on a running system); it is wired and unit-tested,
and reported as not exercised.

## Status, 2026-10-28 (second stage)

Branches continue the stack: `feat/36-xdist-workers` → `feat/37-mealie-l5-amendment` → `feat/38-eval-v2` →
`feat/39-director-actions` (head 285964f). No pull request, merge or external deploy.

| Stage | Ran | Changed | Evidence shows | Cannot conclude | Blocked / next condition |
|---|---|---|---|---|---|
| Mealie L5 (D-041) | amendment committed first; isolated project; lab revalidation; two verified deploys; probes | xdist workers = sandbox CPUs; no L5 on lab evidence below L4; imported outcomes kept as past | L4 revalidated (suite 3/3 per side); live 11.8 → 2.2 ms on SQLite | effect on users (probes only), Postgres, typical sizes, persistence | L6 needs PR14's re-checks over 7 days on a running deployment |
| PR16 evaluation v2 | dev set (debugged), frozen evaluation set (once), real local model | scenarios, oracle, policy runner, product runner, scorer | candidate Director 9/11 vs 4/11 (prev) on the same inputs, no false L4 | product-level gain beyond decisions; discovery 1/2 unchanged; small n; acceptable actions defined by us | more scenarios and repeated runs before any claim of significance |
| PR12 completed | MEASURE / ACQUIRE_CAPABILITY / INVESTIGATE through existing jobs; linter-scope decline | `director/decide.py`, `daemon/cycle.py` | each fires where defined, bounded, in unit tests and both scenario sets | that they are the best policy for a real team | INVESTIGATE not exercised by a scenario |
| PR13 memory | not started | — | — | — | ablation on dev scenarios with repeated runs (needs PR16's harness: done) |

Dev hypotheses from the evaluation set (to fix on dev, then re-test on a new frozen set): B006 not reported by
ruff-baseline where the project configures ruff; pytest fixtures injected by name read as F811.

---

# Stage 3: the project's ecosystem, connected and extended (2026-10-28)

Goal (Master §9, §10, §13): given a project, its objectives and authorized accesses, Unbidden finds the systems it is
made of, tells what it merely knows from what it can connect to, read and change, names what is missing, reuses or
builds the integration it lacks within its permissions, uses it to resume useful work, acts within the mandate,
checks the effect, and keeps that knowledge current.

## Diagnosis against the goal (verified at c5b37a2)

| Ability | Today | Gap |
|---|---|---|
| Find the systems | compose-scoped: `world/runtime.py` reads containers, published ports, OpenAPI, Postgres **inside its container** (`docker exec … psql`), Prometheus, Jaeger; `ConnectorSpec` describes each | nothing outside the observed compose project; GitHub known only through the mandate |
| Known vs connected vs changeable | `ConnectorSpec.read_only`, `modifies` are descriptions; no per-resource state | no record of a resource's connection, effective permissions, last check, block reason |
| Missing access named | blind spots (text) | no "what access, for what" a person can act on; nothing stops dependent actions when access goes |
| Reuse a connector | Forge reuse for log/stats readers only | no general lookup of capabilities by kind and compatibility |
| Build a missing integration | Forge: `log_adapter`, `stats_reader` only (`contracts/capability.py`) | no API or database integration kind; no contract tests against a live service |
| Resume work with it | needs' `resume` jobs (PR10) | only a sweep; no task that combines sources |
| Act and verify | deploy/rollback = `mandate.operations.deploy_steps` (argv a person declared); merges; holds; kill switch | no typed action with preconditions, idempotency, verification, verified compensation |
| Keep it current | `world.refresh` (PR11), reconcile by source | access changes (revocation) not modelled |

Credentials: `guardian/credentials.py` hands values out per purpose and audits it; policy: `guardian/policy.py`,
deny by default, network allowlists. Both are reused, not replaced.

## What is reused

Connectors' discovery code (`world/runtime.py`, `world/prometheus.py`, `world/jaeger.py`, GitHub client),
`ConnectorSpec`, the World Model and reconcile, the credential broker, the policy engine and Guardian's egress gate,
Forge's need lifecycle (`forge/needs.py`) and its data-only, oracle-judged capabilities, the deploy executor, holds,
the kill switch, the live watcher.

## Contracts that change or appear

1. **Connection** (`contracts/connection.py`, store collection `connections`): resource id, project, environment
   (local / development / staging / production), service kind and protocol, location, discovery provenance,
   credential **reference** (a broker name, never a value), permissions requested and effective, capabilities
   (read / measure / write, each with how it is known), state (`discovered`, `needs_configuration`,
   `needs_authorization`, `connected`, `degraded`, `revoked`, `gone`), last check, limits, network scope, relations,
   block reason and next step. Effective permissions are only ever what a check observed.
2. **Connector protocol** (`connect/base.py`): `validate(config)`, `check()` → identity, reachability, effective
   permissions; `discover()` → World Model facts; `read(op)` / typed `actions()`; `verify(action, result)`; errors
   classified (auth, permission, unreachable, rate-limited, invalid). Common: states, checks, evidence, limits,
   timeouts, retries. Provider-specific: what identity and permission mean (a database role's grants, a token's
   repository permissions, an API key's scope) and every operation.
3. **Integration capability** (Forge kind `api_client`): an OpenAPI document reduced to the operations a need
   requires, each typed (parameters, request and response schemas), marked read or write, with destinations,
   credential reference, limits, contract tests, version and provenance. Data, not code: one fixed executor runs it,
   and the policy and the broker are applied there, at execution. The local model selects operations and drafts the
   contract; acceptance is a model-free oracle against the live service (responses validated against the
   document's own schemas, list/get consistency, errors as documented), never the model's own expectations.
4. **Typed action** (`contracts/action.py`, `operate/actions.py`): target connection and environment, typed
   parameters, preconditions, required capability, idempotency key, timeout, evidence, post-check, compensation
   (declared available only once verified). The deploy-steps executor becomes one action kind; proposing, validating
   and executing a procedure stay distinct (a found script or workflow is a proposal, never an authorization).
5. **Mandate**: `connections` (what a person authorizes: location, environment, credential reference, permissions
   granted per connection) and `goals` (objectives in words, with bounds on actions).

## First vertical slice (local lab, isolated)

`bench/ecosystem/`: an application repository with a staging compose project; a PostgreSQL reachable over the
network outside that project (its own container and network, a read-only role); **Stockroom**, a synthetic but real
HTTP service with an OpenAPI document and an API key, unknown to Unbidden, in two compatible instances (A, B);
GitHub through the existing client, read only. Goal given in the mandate: keep staging orders from failing for lack
of stock, with reorders bounded. The agent gets the mandate and the accesses, not steps. It must map, find the
missing integration, build and validate it, observe through it, resume the investigation (which SKUs will run out:
orders from the database × stock from the API), place a bounded reorder in staging if allowed, verify it, and reuse
the integration on instance B. Also: access denied, revocation, a partial failure, a repeated action.

## PRs, by dependency

| PR | Scope | Acceptance |
|---|---|---|
| 40 | this plan | — |
| 41 | Connection contract, store, states; connector protocol; existing connectors (compose, Postgres-in-container, OpenAPI, GitHub) report checks | `unbidden connections` shows each with state and effective permissions; nothing "connected" before a check |
| 42 | Network PostgreSQL connector: config, broker reference, TLS mode, least privilege, bounded read-only queries, real permission check; missing / invalid / revoked credentials | against a live lab Postgres: grants observed, a write refused, revocation moves the connection and stops dependents |
| 43 | Forge `api_client`: need → search existing → fetch the authorized document → local model selects and specifies → oracle on the live service → register → enable by mandate | built with the real local model; oracle passes on instance A; reused on B without a rebuild; refuses a spec that does not match the service |
| 44 | Typed actions and their executor; deploy steps as one kind; verified compensation only | idempotent repeat, timeout, post-check, compensation verified before declared |
| 45 | Ecosystem map: connections and their relations in the World Model, project grouping; `activity`, `map`, `doctor` show connected / readable / writable / missing / building / needs a person | discovered never shown as connected; read-only never shown as control |
| 46 | Vertical slice and its evaluation: dev scenarios, a new frozen evaluation set, connectivity / comprehension / self-extension / usefulness scored apart | the run with the real local model, end to end, recorded with its limits |

## Out of this stage

OAuth flows and token refresh (designed in the Connection contract as a credential kind, built when a case needs
it); SDK and MCP integration kinds (OpenAPI first: the lab's service publishes one); Kubernetes, cloud accounts;
multi-tenant projects; remote models (no budget authorized). PR13 (memory) stays as defined: it needs repeated runs
of PR16's harness, independent of this stage, and will gain inputs from it (connection checks and capability use
are history it can learn from).

## Stage 3 status, 2026-10-28

Branches: `feat/40-ecosystem-plan` → `41-connections` → `42-postgres-network` → `43-forge-api-client` →
`44-typed-actions` → `45-ecosystem-loop` → `46-ecosystem-eval` → `47-ecosystem-dev-fixes` (head). No PR, merge or
external deploy. Results and the implemented / tested / shown / pending / out-of-scope matrix:
`docs/bench/ecosystem/RESULTS.md`.

| Stage | Ran | Evidence shows | Cannot conclude | Next condition |
|---|---|---|---|---|
| PR41–45 | unit + e2e (lab DB) + development d1–d7 ×3 with the local model | the full chain on Shopfront: map, need, integration built and validated, reuse, goal, bounded verified actions, revocation and denial handled | behaviour on real, remote or production systems | — |
| PR46 evaluation | Dispatch e1–e4, frozen, once | map, connections, an unseen API's read integration and safety generalized | that pagination styles or writes generalize: they did not (3/6 found, 0 bookings) | dev hypotheses below fixed on development scenarios, then a new frozen set |

Development hypotheses from the evaluation (not fixed from it): offset/limit/total pagination in the executor and
the oracle; an integration extended (a new need, a re-selection) when a plan needs an operation it lacks.
PR13 stays as defined (memory, ablation on repeated runs); stage 3 gives it new history to learn from (connection
checks, integration outcomes, goal runs).

---

# Stage 4: a reliable cycle on a new API, with Meta's models, then multimodal (2026-10-28)

Starting point verified: `feat/47-ecosystem-dev-fixes` @ 3eb43d9 is the latest branch; no later work. The Dispatch
evaluation (stage 3) stays as recorded; its failures (offset pagination, the missing write) now inform development
and are not a new out-of-sample result.

**Meta, as found** (D-006 updated by a check today): the key lists `muse-spark-1.1/1.2/1.3` (+ contributor),
`muse-wonder-1.0`, `muse-image-1.0`, `muse-voice-transcribe-1.0`, `sam-3.1`. The API has no balance or usage
endpoint (404); official pricing (dev.meta.ai): Spark $1.25/$4.25 per M tokens, Wonder $4/$20, Image $0.01 per image,
SAM $2.50 per 1,000 images, Voice $0.18 per hour; whether billing continues after credits is not documented. The
ledger therefore stays unverified until a person enters the balance read on the dashboard (`unbidden spend
--verified-balance`), and no paid call beyond the existing allowance is made before that.

| Block | PR | Depends on | Acceptance |
|---|---|---|---|
| 1.1 Oracle authorization | 48 | — | DENY and REQUIRE_APPROVAL without a valid approval send no mutating request in build, reuse or extension; ALLOW or an approval: effects only in scope; oracle effects audited and counted against the connection's write budget; revocation and kill switch checked before each effect |
| 1.2 Postconditions and compensation | 49 | 48 | an action is VERIFIED only when the named field of the named record changed as expected and nothing else did; COMPENSATED only when re-read back; adversarial fixtures (wrong field, success without effect, undo without reversal, repeat that duplicates, timeout after a write) all end UNVERIFIED or reconciled, never verified falsely, never duplicated |
| 1.3 Complete reads | 50 | — | page, offset/limit/total and cursor pagination; completeness complete / incomplete / unknown; truncation, repeated pages, no progress detected; an independent oracle check (another page size, the declared total) catches a service that skips a page; a decision needing completeness is blocked or narrowed |
| 1.4 Integration extension | 51 | 48, 50 | a plan needing an absent operation records a specific need, re-reads the document, adds documented and permitted operations, validates them before enabling, keeps existing ones, resumes the goal; bounded attempts; a specific block when permission, documentation or a verifiable operation is missing |
| 2.5 Routing by task | 52 | — | planning, documentation reading and integration building go through the router by task, modality, data class, cost and latency; local kept where context must stay local; model, version, reason, fallback, latency and cost recorded per call |
| 2.6 Budget | with 52 | balance from a person | a stage budget within the confirmed balance, a reserve for evaluation and demo, concurrency 1, retries bounded, enforced by the existing ledger |
| 2.7 Local vs hybrid in development | — | 48–52 | the same corrected code under both model policies on the development scenarios (new fixtures, not Dispatch), measured: goals completed, correct effects, read coverage, interventions, false verifications, latency, spend |
| 3.8–3.9 Multimodal | 53+ | 2.7 | an objective documented before implementation that needs visual evidence plus code/API/data, solved and verified functionally and visually; reuse the visual judge; SAM / Image / Voice only where they add measured utility |
| 10 New evaluation | — | all above | frozen code, model configuration, harness, oracles, scenarios, metrics, budget and repetitions; questions A (APIs) and B (multimodal) reported apart |

Out of this stage: PR13, OAuth, additional cloud providers, web interface.

# Stage 5: the multimodal cycle, then two evaluations apart (2026-10-28)

Starting point: `feat/54-blocked-needs` @ 6bdd2a8 (no later commits). The block 3 objective and feasibility stand
(`docs/bench/2026-10-28-multimodal-objective.md`); Spark is the default model, Wonder the comparison, SAM where it
measures something; the local model and routing are unchanged. Image and Voice are not integrated.

| # | Step | Depends on | Acceptance |
|---|---|---|---|
| 1 | Send-time authorization for every mutating attempt | — | done (`ddae5b0`): 503 → DENY → no second write; same for an expired or deleted approval, revocation, kill switch, budget; oracle, action and undo; every attempt recorded and counted |
| 2 | The visual goal's contract (amendment 1 to the objective) | — | written before any board code: shortage and its source of truth, visible / legible / bound to its row, occlusion tolerated, scrolling, false alarm, what VERIFIED needs, what the agent may not do; truth computed independently of the board |
| 3 | The board and the cycle, one defect and the healthy control | 2 | goal (no hint) → data → board observed → discrepancy → cause in code → fix in a worktree → checks → lab deploy → functional and visual verification by an independent checker → a second cycle that changes nothing |
| 4 | The other development defects and variants | 3 | occlusion, wrong formula, wrong style, healthy control; badge size/position, partial and total occlusion, red elements that are not alerts, reordered rows, healthy pages styled differently |
| 5 | Three cumulative observation methods | 3 | A browser/DOM (text, rows, computed style, geometry, scroll, `elementFromPoint`), B = A + Spark on screenshots, C = B + SAM; same tools and information otherwise; regions bound to row ids with viewport/scroll/scale mapped |
| 6 | Perception and full cycle measured apart | 4, 5 | perception: same states and captures for every method; full cycle: each method from a clean copy; independent verifier; evidence with hashes |
| 7 | Frozen evaluations A (APIs, a new service) and B (multimodal, a new board) | 1–6 | code, harness, oracles, configuration, metrics, budget and repetitions frozen before running; no change during runs; failures kept |
| 8 | Test-timing sensitivity (`test_forge_stats`), docs, decisions, demo | all | functional tests separate from timing measurements; PLAN, RESULTS, objective, decisions updated; a reproducible demo |

Out of this stage: PR13, OAuth, new providers, a web interface; external PRs, merges or deploys.

## Stage 5 status, 2026-10-28

Steps 1-6 done in development (RESULTS.md, stage 5; D-043). Step 7: both evaluation sets written (8437b48) and the
protocol and budget in `docs/bench/stage5-freeze.md`; it runs after a person releases the reserve. Step 8: the test
timing fixed; the demo is `bench/ecosystem/board_demo.py`.

# Stage 6: consolidation (2026-10-28)

Starting point: `feat/55-send-time-authorization` @ c804aaf, no later work. Budget: D-044 (US$10 from
2026-10-28T22:44:23Z: dev 3, evaluation 5, demo and contingency 2). The 2793504 trial is closed by amendment 1 of
`docs/bench/stage5-freeze.md`.

| # | Step | Depends on | Acceptance |
|---|---|---|---|
| 1 | Budget recorded, card correction, protocol amendment | — | D-044; amendment 1; ledger starting point |
| 2 | OpenAPI schemas by declared version (3.0 `nullable`, 3.1 type arrays) for parameters, bodies, responses | — | tests fail on c804aaf; invalid values still rejected; unsupported features refused with a reason |
| 3 | Invalid page observations are inconclusive, before and after a repair | — | non-JSON, incomplete or schema-invalid answers never give page_ok or page_fixed; bounded retry, then blocked |
| 4 | Perception metrics separated (alerted, hit one, hit all, false alarms, precision, recall, inconclusive) | — | tests with right, wrong, mixed and absent reports |
| 5 | Stage 5 summaries recomputed from records | 4 | the 6-vs-8 defective states explained; originals kept |
| 6 | Development regression on Larder (post-evaluation) and adversarial cases; the visual cycle with agent vs checker apart | 2, 3 | full chain without duplication; adversarial cases end safe |
| 7 | New frozen evaluation: A (a new service), B (stage 5 states + cases without a healthy version in history) | 2-6 | predeclared repetitions and budget; perception apart from repair; history-aided repairs apart from others |
| 8 | Reproducible release, branch integration order, demo; PLAN, RESULTS, decisions | all | from a clean checkout |

## Stage 6 status, 2026-10-29

Done: steps 1-8. Fixes with tests (D-045); stage 5 summaries recomputed; Larder regression (7 scenarios); the frozen
evaluation at 94765da (A: Linen 12/12; B: perception per method, 30/30 repairs verified); the demo recorded
(`docs/bench/stage6-demo.md`); the release and the integration order (`docs/RELEASE.md`). Spend: US$5.94 of US$10
before the demo, US$0.07 the demo. Pending, by evidence: the checker's next version counts visible false flags;
PR13, OAuth, other cloud providers and an interface stay for after consolidation; no PR or merge was made.

# Stage 7: checker v2, verifiable acceptance, and a real application (2026-10-29)

Starting point: `feat/56-consolidation` @ 536fafe (release f8d3fc2, evaluation 94765da), no later work. Stage 6 is
closed and its records stay as they are. Stage 6's results, stated precisely: A, 12 runs on one service (Linen);
B, 30 repair runs accepted by the original checker, 27 on seeded defects and 3 on healthy controls, over a small set
of states: runs, not 30 independent problems.

**Budget.** No new authorization: the stage 6 one (D-044), US$10 from 2026-10-28T22:44:23Z, of which US$6.01 spent;
US$3.99 available (ledger checked 2026-10-29). Planned: development US$1.20, the frozen transfer evaluation US$2.00,
contingency US$0.79. If that is not enough, what was done is delivered and a concrete extension is asked for.

| # | Step | Depends on | Acceptance |
|---|---|---|---|
| 1 | Plan, budget | — | this section |
| 2 | Checker v2: which row a flag belongs to, which row(s) it is drawn over, what a person sees | — | rules written before code (objective, amendment 2); healthy and adversarial tests; stage 6 records re-read with no model call; original and v2 results side by side |
| 3 | Acceptance inside the product: conditions with source, observation, outcome, and what happens when unverifiable | — | proposed / model-says-resolved / objective checks passed / inconclusive or rejected kept apart in state and `activity`; a model cannot weaken a condition after its repair fails; tests for each listed case |
| 4 | A real application, chosen and pinned before the agent runs | — | not built by us, not Mealie, runs locally isolated, stack in scope, observable behaviour, own checks; reasons and limits recorded; every human setup step counted |
| 5 | Transfer (a general goal) and proactive discovery (no ticket) on it | 2-4 | frozen version, configuration, criteria, budget and repetitions before the runs; "no demonstrable improvement" is a valid result |
| 6 | Release from a clean checkout following only RELEASE.md; integration proposal from the real git graph | — | every instruction executed as written |
| 7 | PLAN, RESULTS, RELEASE, decisions | all | — |

## Stage 7 status, 2026-10-29

Done: checker v2 and the stage 6 re-read (step 2); acceptance in the product with its tests and `activity` (step 3);
the application chosen and its protocol written (step 4, part); the release walked from a clean checkout and
corrected, and the integration proposal from the git graph (step 6). Blocked: building and running Conduit (needs a
person's permission), and so the transfer and proactive runs (step 5). Spend: US$6.06 of US$10; US$3.94 left.

## Stage 7 closed, 2026-10-29

Steps 1-7 done. The transfer ran once as frozen (B-1, A-1, A-2): two natural findings, reproduction blocked by the
sandbox's interpreter and toolchain; the goal blocked by the app's inaccurate OpenAPI; no improvement demonstrated.
Spend: US$6.12 of US$10 (stage 7: US$0.11); US$3.88 left. Next version (D-047): the project's interpreter and a
toolchain in experiments; documented-vs-observed deviations as evidence; reads in the endpoint map. Then a second
application for out-of-sample evidence. Unchanged: PR13, OAuth, other cloud providers and an interface are later.

# Stage 8: reproduce the project, controlled API compatibility, findings tied to real queries; a 1.0 candidate (2026-10-29)

Starting point: `feat/57-transfer` @ 800422e, no later work. The Conduit evaluation frozen at 9ef6a60 stays as it is:
two natural candidates found, no improvement demonstrated. Conduit is now development and regression for this
stage. The `articlesCount` defect was seen by Claude, not by Unbidden; it stays so attributed, and it is never given
to the agent as a hint in a proactive run.

**Budget:** no new authorization. The ledger (checked now) reads US$6.12 spent of US$10, US$3.88 left. Split:
development and Conduit regression up to US$1.30; the independent test US$1.80; contingency US$0.78.

| # | Step | Depends on | Acceptance |
|---|---|---|---|
| 1 | Plan, budget | — | this section |
| 2 | Reproduce the project's environment: interpreter from its declarations (pyproject, lock, Dockerfile, CI), conflicts resolved by a written rule; build tools detected from the project and from observed errors; provisioning (network) apart from execution (isolated) | — | the original project installs its dependencies and runs its checks before any repair, or the concrete cause is said and no evidence is promoted; tests: incompatible choice, conflicting sources, build failures; a real run on Conduit |
| 3 | Controlled API read compatibility: a deviation on an accessory field degrades the read with the deviation recorded; on identifiers, relations, filters or compared values it blocks the conclusion; pagination or count inconsistencies make completeness unknown; writes stay strict | — | the document kept as published; per operation and field: declared contract, observed difference, provenance and time, decisions affected, reason; tests: accessory and critical nulls, invalid ids, missing fields, inconsistent totals |
| 4 | Findings tied to real queries (endpoint -> query -> filter or join -> column -> volume -> observed cost), reads included; inferred apart from observed | — | a missing index is a candidate until reproduced, measured on both sides, the project's checks run on both sides, and its write and storage cost weighed |
| 5 | Human requests that unblock: blocked operation, evidence, the minimum needed, what continues; states kept apart | — | a request is pertinent to the block it names (tests) |
| 6 | Conduit regression, a new version, B before A from clean states | 2-5 | each capability's outcome recorded; human preparation counted |
| 7 | An independent application, chosen and frozen before running | 6 | a proactive run with its own checks and an independent measurement |
| 8 | A 1.0 candidate commit, clean-checkout install, integration proposal, exit-criteria matrix | all | 1.0 only if every exit criterion has evidence; otherwise "experimental candidate" and what blocks 1.0 |

## Stage 8: status and exit criteria (2026-10-29)

Spend: US$7.29 of US$10 on the ledger (stage 8: US$1.17; it read 6.1204 at the start); **US$2.71 left**. The
counter was never reset. Development and the Conduit regression: US$1.17 of the US$1.30 planned (six regression
versions, B before A each); the independent test: US$0.00 of US$1.80 (its model calls stayed local); contingency
untouched. No billing change, no other charge.

| # | Exit criterion | Evidence | Met? |
|---|---|---|---|
| 1 | The project's environment is reproduced before experimenting | Conduit: the interpreter chosen by rule (3.9 from the CI and the Dockerfile), Debian's build tools through the one authorized request, the CI's PostgreSQL as a sidecar; its suite ran at the base in every experiment of B-7/A-8 (90 tests, 3 rounds, none failed). LNbits, in its evaluation (I-1): the interpreter chosen right (3.12, as uv chose independently), but the project could not be imported, so its tests never ran; fixed after the evaluation (da7a595), and no experiment ran there since | partly: on the regression application, not on the independent one in its evaluation |
| 2 | Incompatible data produces no false conclusion | Tests for cases A-D (`test_api_deviations.py`); Conduit: optional nulls recorded per operation and field with a count, the listing read whole (20,000) and judged "unknown" because no total is declared under a known name, so the goal blocked instead of concluding; writes strict | yes |
| 3 | Findings are explained and prioritized with evidence | The chain endpoint -> SQL query -> join or filter -> column -> volume, read from the code and the live system; candidates with estimated index size and write cost. Independently checked (`conduit_indep.py`): of three L4 claims, two confirmed (comments listing 8.43 -> 0.06 ms; article delete 0.60 -> 0.20 ms with comments indexed), **one a false positive** (`commentaries.author_id`: the delete uses the primary key) | partly: one false L4 |
| 4 | Permissions, budgets and revocations are respected | No push or pull request (denied by the mandate; `github.com` not an allowed destination: the refusal is in the log); registries only as granted, the grant asked once; the ledger checked before and after every run, never reset; send-time authorization, revocation and spend caps under test (`test_send_time_authorization.py`, `test_connections.py`, `test_spend.py`) | yes |
| 5 | Acceptance tells applied, claimed by the model, verified and inconclusive apart | Stage 7's contract (`contracts/acceptance.py`: proposed, applied, accepted, rejected, inconclusive, stale; the model's claim apart) and its tests and runs (D-046); not exercised in stage 8's runs, whose goal blocked before any change | yes (stage 7 evidence; not re-exercised) |
| 6 | A useful cycle on an independent application, with human preparation declared | LNbits I-1: preparation declared; no improvement, and not a justified abstention (no table mapped, the project not importable). The post-evaluation repeat (I-2) mapped and abstained consistently with the independent measurement, but it was tuned on I-1 and is not out-of-sample evidence | **no** |
| 7 | Installation and operation documented and reproduced | From a clean checkout in a fresh HOME, only the documented commands, at the candidate 36e1a59: install, `make check` (641 tests), `doctor` (Docker, models, credentials, budget), a mandate and a compatible run (one cycle, local models only, accepted and confirmed by the independent checker), evidence (`activity`, `connections`, `egress`), stop and cleanup (`kill`/`resume`, labs down). Two earlier walks failed and were fixed (`RELEASE.md`, "The walk"); on Linux or x86-64: not done | yes, on the one platform tested |
| 8 | A candidate commit and integration prepared | candidate 36e1a59; the integration proposal from the git graph in `RELEASE.md`; nothing merged, published or deployed | yes |

**Verdict: experimental candidate, not 1.0.** What blocks 1.0: (6) a useful cycle, or a justified abstention, on an
application never used in development, frozen before running; (1) the same application's own checks run by Unbidden
at its base in that evaluation; (3) a measurement criterion that does not grant L4 to an effect the query plan
cannot explain (an absolute floor, or base and candidate measured in one session).

**Next, in order:** (1) the false L4: measure base and candidate in the same session, alternating, and require the
changed query in the plan; (2) a second independent application, frozen first, with experiments expected (an
unindexed foreign key under load in an asynchronous or SQL-first project); (3) completeness for listings whose count
is named differently (read the declared response schema for a count field, never guessed); (4) proactive runs that
build an API integration when a finding needs one.

## Stage 9: status and exit criteria (2026-10-30)

**Spend (D-052).** Cap US$37.29 cumulative (US$7.29 spent before + US$30 authorized); the ledger reads US$16.99
spent, **US$20.31 available**; stage 9 spent US$9.69, every call through an envelope, reserved before sending and
settled after: `dev` US$8.32 of 12 (development, revalidation, regressions v1-v8, post-evaluation repeats), `eval`
US$0.84 of 12 (the frozen evaluation), `demo` US$0.53 of 6 (the demo; the walks made no model call). Meta's API
only (Spark; Wonder not used in this stage's runs); no local model call; no redistribution between envelopes. The
counter was never reset; no billing, card or credit setting changed.

**Development vs evaluation, kept apart.** Development (Conduit, LNbits; `docs/bench/stage9-regression.md`,
`stage9-revalidation.md`): perf-v3 replayed on Conduit's controls (A/A and an irrelevant index: no relevant change),
two of three earlier L4s revoked with their history, Conduit's cycle stable at two confirmed L4s. Evaluation
(Spoolman, Prefect; `docs/bench/stage9-evaluation.md`): four technical blocks, no useful improvement, no false
promotion; their causes fixed afterwards and repeated as regressions only.

| # | Exit criterion | Evidence | Met? |
|---|---|---|---|
| 1 | The project's environment is reproduced before experimenting | Every cycle runs the project's own checks at the base (`observe.checks`, D-056) and shows them in `activity`: Conduit 90 passed (every run since v2), LNbits 272 collected (2 need network, said so), Spoolman 278 passed (evaluation and repeats); Prefect: its install diverged from its CI in the evaluation (fixed after, c5ea5ee) and its sharded suite is a stated limit | partly: three of four applications, Prefect not |
| 2 | Incompatible data produces no false conclusion | Completeness from behaviour (D-055, `tests/unit/test_complete_reads.py`, `test_consistency.py`); totals under unknown names judged by structure; partial reads (row limit, unknown completeness) withhold "none" (Conduit, LNbits, Spoolman: every such question inconclusive with its reason); writes strict; `articlesCount` remains a person's finding | yes |
| 3 | Findings are explained and prioritized with evidence; no false L4 | perf-v3 (D-053, `test_perfstats.py`): controls give no change; `commentaries.author_id` (false L4) revoked, never promoted again; `commentaries.article_id` revoked at 18% and found L4 at 24-25% under other workloads (workload-dependent: a limit); the demo's two L4s confirmed independently; Spoolman's findings were real but misexplained (fixed after: a primary-key join is not a lookup) | partly: no false promotion in stage 9, but the verdict depends on a model-written workload |
| 4 | Permissions, budgets and revocations are respected | Envelopes enforced before each call (`test_spend.py`); labs owned by identity, `down` only its own lab, volumes kept (`test_lab_ownership.py`, two labs plus foreign resources; walk 5 left the other labs untouched); Hosli, Mealie and frozen worktrees untouched; no push of a proposal, no PR, merge, tag or deploy | yes |
| 5 | Acceptance tells applied, claimed, verified and inconclusive apart | Stage 7's contract (D-046); verdict outcomes now improved / no relevant change / regression / inconclusive / blocked, revocations kept (`test_revoke.py`, `unbidden activity`) | yes |
| 6 | A useful cycle on an independent application, frozen first | Spoolman and Prefect, frozen at 466739e by a rule written first: four technical blocks, no useful improvement, no verified absence | **no** |
| 7 | Installation and operation documented and reproduced | `RELEASE.md` (platforms, scope, requirements, permissions, models and budget, limits, install to cleanup, recovery, levels); walk 5 from an empty HOME at 1c4cab7: 18 of 18 steps (`docs/bench/stage9-walk/`); Linux, x86-64 and a walk with the Meta key not done | yes, on the one platform tested |
| 8 | A candidate commit, a reproducible demo and an integration prepared | candidate 1c4cab7 (`make check`: 691 passed); demo `docs/bench/stage9-demo.md` (harness vs Unbidden declared, independently checked); integration from the graph in `RELEASE.md` (a77ef43 to bring, cherry-pick and `--no-ff` merge tested clean); nothing merged or published | yes |

**Verdict: experimental candidate, not 1.0.** Criterion 6 is unmet, and 1 and 3 are partly met. The false L4 of
stage 8 is retired; the measurement no longer promotes what the engine does not show; but no useful cycle has run on
an application not used in development.

**Next, in order:** (1) performance workloads that run on a new application: the measure must not depend on a model
writing a test from scratch (Spoolman's five attempts each failed; a workload from the endpoints' own calls and the
project's fixtures); (2) a pre-registered larger set of applications (several, frozen together, before any run), so
one block does not end the evaluation; (3) reads by `POST .../filter` declared read-only by the document or a
person, and sharded CI suites run as their groups; (4) revalidate the remaining pending L4s (fst, mealie) under
perf-v3; (5) Linux and x86-64 walks.
