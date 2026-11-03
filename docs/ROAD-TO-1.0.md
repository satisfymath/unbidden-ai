# Road to 1.0

Written 2026-11-03 after campaign 12 (`docs/bench/campaign12/REPORT.md` on `feat/64-campaign`), recorded as D-065.
It replaces the criteria of `docs/CAMPAIGN-v1.md` §9-12, which stay as history. The product is 0.12.x,
"experimental candidate", until every line of §3 is met on a frozen candidate; then a person decides the tag.

## 1. Promise and scope of 1.0

Unbidden, installed with one line on macOS arm64 or Linux x86-64, set up in a repository with a few answers, finds
improvements it can prove in five classes (§2), measures them against the team's own checks, proposes them as pull
requests that carry their evidence and, in autonomous mode, merges on green CI, deploys with the team's steps,
watches the effect and rolls back. When it cannot go on it either retries, asks a person a question with options, or
says plainly that it cannot and why. It never acts outside its mandate.

Scope stays what campaign 12 measured: Python applications and libraries whose checks run under GitHub Actions;
FastAPI, Starlette, Django and Flask on PostgreSQL for runtime work; TypeScript and Go analysers as declared in
`unbidden doctor`. Anything else is said to be out of scope by `doctor` and `scan`, which is itself a criterion.

## 2. The five classes of improvement and what "proven" means

An improvement is proven when the measurement named below was made on both sides, by Unbidden in its sandbox, and the
team's own suite shows no regression. A claim always names its metric, unit, direction, threshold and source
(`contracts/metric.py`). Levels are those of `docs/EVIDENCE.md`: L4 offline with the team's checks, L5 measured after
deploy, L6 persisting.

| Class | Opens from | Proof | Threshold | Re-checked independently by | Highest level |
|---|---|---|---|---|---|
| Latency | unindexed foreign key, whole-table reads | perf-v4: session medians, A/A control, permutation test, confirmation in new sessions | ≥ 20% faster, p < 0.05, A/A within ±10% | replaying the workload at base and head in the lab | L6 |
| Correctness | a crash from the robustness probe, a property violation, a consistency discrepancy, a recurring error with a frame in the repository, an authentication deviation | a new test that fails at the base and passes at the head, then the team's suite on both sides | the new test fails 3/3 at base and passes 3/3 at head; no regression | running the new test at base and head | L4; L5 when the originating error signal drops after deploy |
| Reliability | error ratio, 5xx share, timeouts, restarts per service (probes, Prometheus, logs) | the failing requests replayed in the lab; after deploy, the same signal | error ratio lower with non-overlapping 95% Wilson intervals over ≥ 100 requests; no new restart | reading the signal at the previous and the new deploy | L6 |
| Security and dependencies | a known vulnerability (pip-audit, npm audit), a secret in tracked files, a high-severity high-confidence bandit rule, an authentication deviation | the dependency bumped with the team's own lock tool to the lowest fixed version, or the code patched; the scanner again; the suite on both sides | the advisory or finding gone; no new one; no regression | re-running the scanner at base and head | L4 |
| Quality judged by the team's CI | the team's own type checker, linter and formatter; a test flaky at the base; suite time | the candidate through the team's formatter and type check before measuring; flaky: N reruns | findings gone, no new ones under the team's tools; flaky: 0 failures in 10 reruns where the base failed ≥ 1; suite time as latency | the team's tools at base and head | L4; L5 when CI on the merged head is green |

A supported absence ("the engine shows no endpoint looks the table up by that column") is a valid result and never
counts as an improvement. A lint or format finding the team's CI already runs green is declined, as today.

## 3. Criteria for 1.0

Measured on the final pass (`docs/bench/campaign13/PROTOCOL.md` §7) on the frozen candidate, per class of repository,
with the corpus of campaign 12 (12 development, 19 independent, 8 frontier). Each threshold is set against what
campaign 12 measured; a development result is calibration, not evidence.

| # | Dimension | Development (12) | Independent (19) | Frontier (8) | Campaign 12 |
|---|---|---|---|---|---|
| 1 | Install, setup, doctor, start/stop, second start refused, dashboard | 12/12 | 19/19 | 8/8 | 39/39 twice |
| 2 | Project checks reproduced (default mandate; Debian allowed) | ≥ 10/12 | ≥ 9/19; ≥ 12/19 | out of scope said correctly 8/8 | 8/12; 3/19 and 7/19 |
| 3 | Classes of improvement with at least one experiment | ≥ 3 | ≥ 2 | reported | 2 (latency, lint) |
| 4 | Repositories with a published pull request whose claim the verifier confirms | ≥ 6 | ≥ 4 | reported | 3 and 1 |
| 5 | Published pull requests green on the team's CI at their exact head | ≥ 80% | ≥ 70% | reported | 57% dev before the formatter fix |
| 6 | Merges by the product on repositories with a lab (autonomous) | every lab repository | ≥ 2 | — | fst, spoolman |
| 7 | Deploys with a verified effect (L5) | ≥ 3 applications, ≥ 2 classes | ≥ 1 application | — | 2 applications, 1 class |
| 8 | Dashboard, recovery, seeded scenarios | all | all | — | 8/8 |
| 9 | Human interventions during runs; asks answered by the recorded policy; median spend per Level B run | 0; all recorded; ≤ US$1.00 | same | same | 0; —; US$0.07-0.28 |

Zero tolerance, any class: no false promotion (the verifier contradicts a claim, or a merged change regresses the
team's checks), no action outside the mandate, no secret in a model payload or a record.

Repeatable: every full chain of dimension 7 repeated from a clean state on the frozen candidate with the same outcome
class.

Walk and demo: a clean install walk on macOS arm64 by hand and Linux x86-64 in GitHub Actions on the frozen wheel; a
recorded demo of setup, a first cycle, an ask answered, a merge, a deploy and a rollback.

Any line not met keeps "release candidate", with the cause named in the final report. The tag is a person's decision.

## 4. Blocks: retry, ask, or declare

Every stop is one of three things, decided by its kind (`director/blocks.py`):

| Kind | What Unbidden does |
|---|---|
| `unavailable` (a service did not answer) | retries with backoff (2, 4, 8 … 60 min), at most 6 times, then declares it |
| `pending_person` (a person can grant something) | asks: one question with options per need, the job parked until the answer or until the mandate shows the need met; the answer re-runs the held work at once |
| `missing_capability` | builds the integration with the forge; if that is refused or fails twice, asks for approval or declares it |
| `compatibility`, `not_viable` | declares it with the cause; never retried at the same commit |

The questions cover every case a person can unblock: a model key, a connection credential, GitHub access or push, a
package registry, approval of a pull request, writes through a connection, a new capability, deploy steps, a rollback
drill, a merge left to a person, the monthly cap, the machine ledger, a hold. A spend limit, a kill switch, a policy
refusal or a busy host is a block, never a verdict on the opportunity.

## 5. What stays experimental in 1.0

Local-only models, Linux arm64, monorepos with the project outside the root, languages other than those `doctor`
lists, writes to production. They are said as such by `doctor` and the README.
