# Evidence

What Unbidden has shown, at the level each result reached, with what failed beside it. Every row links to the
decision record or benchmark file that holds its measurement. Nothing here is rounded up: a laboratory result (L4) is
never presented as a deployed one (L5), and a result with an invalid baseline is reported as invalid.

## The question

Can Unbidden enter a system it has never seen, understand it, find an intervention worth making, build what it lacks,
make the change, and show on its own whether the system improved, across many systems and without a person directing
each step?

**Short answer, today.** On single systems: yes, up to L4, and it has deployed and rolled back on its own. Across many
unseen systems: not yet shown. The first cross-repository pilot found one L4, and it was a false positive. Unbidden
then learned to reject that class of result by itself.

## Levels

| Level | Meaning | Who can claim it |
|---|---|---|
| L1 | Reasonable suspicion | any finding |
| L2 | Reproduced | a crash or finding reproduced in the sandbox |
| L3 | Improved in the lab | the candidate removes it offline |
| L4 | Functionally validated | the team's own checks and tests pass on both sides, and the CI's interpreter agrees (CI parity, D-038) |
| L5 | Operational result | measured live between two deploys whose code is verified or observed, with confounders |
| L6 | Persisted | L5 held over time |

## Results on single systems

| System | Result | Level | Record |
|---|---|---|---|
| full-stack-fastapi-template (fork) | Unindexed `item.owner_id` found by a generic World Model check; migration and workload written and measured: `GET /api/v1/items/` 13.0 → 4.1 ms, p = 3.4e-08 | **L4**, pending revalidation under perf-v3 (stage 9) | D-010 |
| same | Published, merged and deployed on its own. Live: 10.5 → 1.7 ms, but the pre-registered floor of that time (10 ms) said "no change claimed" | **L4, not L5** | D-013, D-014 |
| same | Outage drill: outage called in 11 s, rolled back in 15 s, hold set | rollback proven | D-015 |
| same | Read-only investigation named the breaking commit and line | L1 (capped at 0.60) | D-016 |
| Rich (fork), blind | Two crashes in `rich.cells.split_text` found by property tests Spark wrote, one matching an issue it was never told about; fix measured | **L4** | D-018 |
| mealie | Unindexed `shopping_list_items.food_id`; `GET /api/foods/empty` 10,934 → 8.1 ms in the lab (revalidated), 11.8 → 2.2 ms live, on SQLite | **L5** on SQLite, probe traffic only (first reported L4 was not valid: the suite had not run; revalidated in D-041); its lab L4 pending revalidation under perf-v3 (stage 9) | D-035, D-040, D-041 |
| same | Deployed to the local Postgres instance: 5.3 → 5.0 ms median, within noise; the baseline's code was inferred | **invalid L5** | D-036 |
| opentelemetry-demo | Health detector v1–v3 failed their blind holdouts; v4 adopted after one blind detection | detector, weakest part | D-026, D-029, D-031 |
| opentelemetry-demo | Forge built a reader for Envoy's `/stats` (no model in the judge): 1,770 unseen lines, 100 % | capability | D-025 |

## Across unseen repositories

Ten development repositories were chosen by written criteria and pinned before any run (`bench/repos/scale.yaml`):
Python, TypeScript, JavaScript, Go and Ruby; libraries, frameworks and an application with a database. Ten more are
held out, untouched.

**Pilot 1, method check** (`docs/bench/2026-10-27-scale-method-check-pilot.md`, US$0.06):

| Measure | Result (Wilson 95 % CI) |
|---|---|
| Stack supported | 8/10 (49–94 %) |
| Bootstrapped (an analyzer complete or a probe run) | 7/10 (40–89 %) |
| At least one opportunity | 1/7 (3–51 %) |
| L4 | 1 (marshmallow), **a false positive** |

The L4 removed two `type: ignore` comments that the sandbox's mypy called unused. The team's own mypy job was green on
that commit. Unbidden had measured under Python 3.10, while the team's CI also runs 3.14, where the ignores are needed:
the patch would have turned their CI red. Two general fixes followed, with no exception for marshmallow:
- the Director declines findings of any kind from a tool the team's green CI runs, and the autonomous cycle now reads
  the CI as `unbidden decide` did;
- **CI parity**: a candidate is checked again under the newest Python the CI uses. On the real candidate: 2 new mypy
  findings under 3.14, rejected.

**All runs** (each `docs/bench/2026-10-2*-scale-*.md`; development data except the holdout):

| Run | Bootstrapped | Repos with opportunities | Experiments | L4 | What it showed | US$ |
|---|---|---|---|---|---|---|
| Pilot 1 (method check) | 7/10 | 1 | 1 | 1, **false** | the false positive above | 0.06 |
| Pilot 2 | 7/10 | 1 | 2 | 1, outside the team's checked configuration | the false positive's new candidate **rejected by CI parity**; a 3.10-only typing fix the team does not check | 0.14 |
| Pilot 3 | 8/10 | 1 | 0 | 0 | marshmallow's environment findings **declined before any experiment** (CI read through tox) | 0.09 |
| **Holdout, run once, frozen** | **7/10** | **1** | **0** | **0** | markupsafe's 5 pyright groups declined the same way, on a tool and repo never seen | **0.055** |

Holdout, with Wilson 95 % intervals: stack supported 8/10 (49–94 %), bootstrapped 7/10 (40–89 %), an opportunity in 1/7
(3–51 %), validated improvements 0/7 (0–35 %), false L4s 0. The remote model was the only one called (local fallback
denied, none attempted). What the holdout exposed and was fixed afterwards on development data: a probe sampler that
skipped `__init__.py` (markupsafe), and no analyzer for `xo`/mocha projects (node-fetch, open).

**What this answers.** Across unfamiliar repositories Unbidden now bootstraps most Python and JavaScript projects on
its own, and it stops itself from claiming improvements that the team's own CI would contradict. It has **not** yet
found a validated improvement in an unseen, mature library: on 20 such repositories, its checks found only what the
teams' CI already rules out, and its crash probes found nothing beyond one narrow input-validation inconsistency. The
deeper wins (indexes measured at 3× to 2,000×, crashes in Rich) came from systems with databases, endpoints or open
bugs, and the benchmark's libraries offer few of those.

## What a probe finding is worth

humanize's `KeyError` in `naturaldelta(0, minimum_unit='')` is real: it reproduces directly and under 10 of 10 seeds.
A fresh probe found it 0 of 10 times, 1 of 13 overall (CI 1.4–33 %), because the model draws only documented units. It
is narrow: invalid input raising `KeyError` where the library raises `ValueError` for other invalid units. Kept at L2
(`docs/bench/2026-10-27-humanize-probe-variance.md`). One probe per commit is a sample, not a proof of absence.

## Cost

All remote calls went to Muse Spark 1.3 (Standard). US$1.24 at list price in total: US$0.70 before the machine-wide
ledger existed, US$0.54 since (the reconciliation of the first part is in `docs/bench/2026-10-27-spend-reconcile.md`).
The four benchmark runs cost US$0.35 together. No credit balance
has been verified on the dashboard yet, so the spend gate allows only a US$1 allowance; no paid overage is possible.

## Known limits

- Only Python and JavaScript/TypeScript are analyzed. Go, Ruby, Rust and others are named as blind spots.
- Production impact comes from Unbidden's own probes, not user traffic.
- The health detector has passed one blind holdout of three.
- Libraries have no deployment, so L5 is not available for most of the benchmark.
