# Campaign 13: what the development runs measured

While 0.16.0 to 0.18.0 were built, Unbidden ran on 23 of the 39 corpus repositories (copies under
satisfymath, nothing upstream). These runs are not the final pass: they are the evidence each fix was made from, kept
as records. Every line links its record; failures and declared repositories are listed with the rest.

## Totals

- **15** team test suites pass under Unbidden's measurement: **18,734** tests, each suite in the
  environment the team's own CI job prepares (act), run offline.
- **3** applications brought up by Unbidden itself from their own compose file (codex-lb, misago,
  TimeTracker); **2** rollback drills passed, one declared.
- **1** L5 by verified deploy (fst, a security bump): opened, CI green, merged, deployed and checked running.
- Model spend: **US$0.34** (s13-dev). Preparing and measuring environments costs no model calls.

## Per repository

| Repository | Kind | Tests passing | Outcome | Record |
|---|---|---:|---|---|
| fst | app (FastAPI, Postgres) | 58 | Security bump (dnspython 2.8.0 to 2.9.0) opened, the copy's CI green, merged, deployed, L5 by verified deploy: the first L5 that is not latency. Latency L5 in campaign 12. | [rehearsal-0.18/fst/B1.json](rehearsal-0.18/fst/B1.json) |
| codex-lb | app (FastAPI, Postgres) | 6422 | Passes all 6422 tests for the first time (campaign 12: failed for the environment). Brought up by Unbidden itself (`unbidden host up`), rollback drill passed, ran autonomous on it. | [dev-host/codex-lb.json](dev-host/codex-lb.json) |
| misago | app (Django, Postgres) | — | Brought up by Unbidden itself, rollback drill passed. Its suite (8977 tests collected) fails under 0.15.0 for the environment; not re-run since. | [dev-host/misago-final.json](dev-host/misago-final.json) |
| timetracker | app (Flask, nginx, Postgres) | 169 | All 169 of its CI tests pass (campaign 12: 3 failures, the environment's). Brought up by Unbidden itself behind its TLS proxy, 500 users and 20000 activities seeded. Rollback drill declared: its head adds a migration. | [dev-host/timetracker-final.json](dev-host/timetracker-final.json) |
| spoolman | app (FastAPI, SQLAlchemy) | 278 | Suite passes. Latency L5 in campaign 12. | [dev-0.16/spoolman/A.json](dev-0.16/spoolman/A.json) |
| aegra | app (FastAPI, Postgres) | 2429 | Suite passes; 6 opportunities found. | [dev-0.16/aegra/A.json](dev-0.16/aegra/A.json) |
| ctfd | app (Flask) | 679 | Suite passes; 10 opportunities found. | [dev-0.16/ctfd/A.json](dev-0.16/ctfd/A.json) |
| archery | app (Django) | 1521 | Red on GitHub, all 1521 tests pass in its own CI job here: nothing to repair, nothing opened (the rule). | [dev-ci-env/repair_archery4.log](dev-ci-env/repair_archery4.log) |
| humanize | library | 878 | Passes for the first time (campaign 12: environment). Seeded calibration: a broken `ordinal(13)` repaired by the model, 3/3 rounds, no regression in 878 tests, L4, US$0.007 (labelled seeded, not evidence of a real fix). | [dev-ci-env/repair_humanize4.log](dev-ci-env/repair_humanize4.log) |
| rich | library | 981 | Suite passes. In the autonomous rehearsal it proposed nothing: its lint findings are already gated by the team's CI (a correct abstention). | [rehearsal-0.18/rich/B1.json](rehearsal-0.18/rich/B1.json) |
| graphtage | library | 289 | Passes for the first time (campaign 12: environment). | [dev-ci-env/ci_real-v6.jsonl](dev-ci-env/ci_real-v6.jsonl) |
| oauthlib | library | 902 | Passes in 0.15.0 and the first CI-job runs; later offline runs need the network to build (recorded). | [dev-0.15/oauthlib/A.json](dev-0.15/oauthlib/A.json) |
| marshmallow | library | 1192 | Passes; a 0.16.0 regression in reading its CI was found by this run and fixed in 0.17.1. | [dev-0.15/marshmallow/A.json](dev-0.15/marshmallow/A.json) |
| pyjwt | library | 476 | Passes; a 0.16.0 regression was found and fixed in 0.17.1. | [dev-0.15/pyjwt/A.json](dev-0.15/pyjwt/A.json) |
| sqlmodel | library | 268 | Suite passes; 5 opportunities found. | [dev-0.16/sqlmodel/A.json](dev-0.16/sqlmodel/A.json) |
| traefik-manager | app (Flask) | 2192 | Passed all 2192 once; its own suite is flaky (other runs 1 and 50 failures). | [dev-ci-env/ci_real-v5.jsonl](dev-ci-env/ci_real-v5.jsonl) |
| harlequin | app (TUI) | — | Runs its full suite (2214 collected) with 4 to 6 failures (campaign 12: blocked on git, then locale). | [dev-ci-env/ci_real-v6.jsonl](dev-ci-env/ci_real-v6.jsonl) |
| pipx | CLI | — | Runs its full suite (2224 collected), 50 failures. | [dev-ci-env/ci_real-v7.jsonl](dev-ci-env/ci_real-v7.jsonl) |
| brightbean-studio | app (Django) | — | Suite runs (2737 collected), 50 failures. | [dev-ci-env/ci_real-v6.jsonl](dev-ci-env/ci_real-v6.jsonl) |
| rdflib | library | — | Declared: its own CI job's validation fails here without naming a test. | [dev-ci-env/ci_real-v8.jsonl](dev-ci-env/ci_real-v8.jsonl) |
| mediacms | app (Django) | — | Declared: its CI runs the tests inside its own compose (not yet supported). | [dev-0.16/mediacms/A.json](dev-0.16/mediacms/A.json) |
| conduit | app | — | Declared: its CI is broken upstream. | [dev-0.16/conduit/A.json](dev-0.16/conduit/A.json) |
| mimirq | app | — | Declared: its CI needs a self-hosted runner. | [dev-0.16/mimirq/A.json](dev-0.16/mimirq/A.json) |

## Records

- `dev-0.15/`, `dev-0.16/`: Level A (setup, doctor, scan, checks, opportunities, lifecycle, UI) on 0.15.0 (18
  repositories, before the CI-job environment) and 0.16.0 (14, stopped when the disk filled; FINDINGS 2026-11-04).
- `dev-ci-env/`: one JSON line per repository and attempt of the CI-job environment, `ci_real` to `ci_real-v8` in
  the order the fixes landed; the repair runs (archery, the seeded humanize).
- `dev-host/`: the bring-ups of codex-lb, misago and TimeTracker. misago's record names mailpit's page as its health;
  that was a defect, found while compiling this page and fixed in 0.18.1 (a tool beside the application is never
  its health; misago now answers on its own port).
- `rehearsal-0.18/`: the autonomous rehearsal on fst, rich and codex-lb.
- `dev-evidence.json`: this page as data (for the site).
