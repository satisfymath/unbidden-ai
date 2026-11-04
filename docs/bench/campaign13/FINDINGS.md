# Campaign 13 findings

Dated lines, newest last. Each says what was seen, where (record or log), and what follows.

- 2026-11-03 · plan · Campaign 13 opened on `main` 0.12.8 (`0cab77d`); campaign 12's fixes (`feat/64-campaign`,
  `726009d`) are ported by WS0, not merged. Criteria `docs/ROAD-TO-1.0.md`; protocol here; decision D-065.
- 2026-11-03 · WS0 · Campaign 12's product commits ported to `main` 0.12.8 on `feat/67-port-campaign12` (four
  commits replayed, conflicts in `lab/perf.py`, `daemon/cycle.py`, `tests/unit/test_cycle.py` resolved with main's
  asks and `say()`). Main's spend question amended the machine ledger while the router checks the mandate's cap; it
  now raises the mandate's cap and releases the held blocks. 1361 tests passed, pyright clean. No model spend. Not
  pushed: another session releases on main; the PR waits for David.
\n
- 2026-11-03 · release · v0.12.9 (port + docs), v0.13.0 (WS1 blocks/asks, WS2 typed claim, team type check),
  v0.14.0 (WS5 vulnerabilities + dependency lab), v0.14.1 (WS4 error ratios after a deploy) merged and tagged; each
  PR's CI green (check, frontend, installed, secrets).
- 2026-11-03 · WS5 real · fst copy (b874fa5): 80 installed packages looked up on PyPI; dnspython 2.8.0 with
  GHSA-45c3-73f7-pv4m; uv.lock re-resolved to 2.9.0; suite green both sides; L4, claim advisories 1 -> 0. First run
  marked it not improved: the project's own package 404s on PyPI and counted as a failed lookup (fixed). misago: 19 of
  77 installed packages carry advisories. No model spend.
- 2026-11-03 · WS7 real · graphtage checks: passed, 289 tests (campaign 12: infra_failed at `make`, then at
  `sphinx-build`); harlequin with Debian allowed: passed, 8 tests (campaign 12: blocked on git, then locale errors).
  No model spend.
- 2026-11-03 · pivot · David: environment preparation was being done wrong, the answer is simpler, stop the long
  run. Level A dev on 0.15.0 stopped at 18/39: every campaign-12 failure failed again for an environment reason.
  0.16.0 prepares the environment with the team's own CI job (act) and measures offline in its snapshot. Verified on
  15 corpus repositories (US$0): humanize, graphtage, oauthlib, codex-lb pass for the first time; harlequin,
  traefik-manager, pipx, timetracker run their full (or CI-scoped) suites; rich and fst unchanged; rdflib prepared
  but its own validation fails in its job; mediacms (tests in its own compose), conduit (CI broken upstream), mimirq
  (self-hosted) recorded. Each defect found on the way was general and has its test (matrix of objects, shell form
  of act's commands, step names with durations, runner locale, setup-uv cache prune, host ports, publishing vs
  installing, the network rerun).
- 2026-11-03 · repair · David's rule: Unbidden repairs the team's failing tests only when the team's own CI fails
  them too. Checked on real repositories first, nothing opened, as the rule requires: timetracker now passes its
  169 CI tests (its earlier 3 failures were the environment's); rdflib's job fails without naming a test; archery
  (red on GitHub) passes all 1521 of its tests here and recruitops-agent's red CI is its runner lacking Playwright's
  browser (a failure that names the environment is never repaired). Archery needed three general fixes to prepare at
  all: steps that drive the host's Docker are left out, a service's fixed container name is dropped, and a fixed
  host port is kept when free (act runs the job on the host's network, as GitHub, so that is how localhost reaches
  the service); localhost forwarding to services at measurement; database clients in the runner image. Seeded
  scenario (humanize copy, a commit that breaks `ordinal(13)`, labelled seeded, calibration not evidence): the
  team's job fails its test step, one opportunity opens, the model's change is the exact inverse of the seeded
  defect, the test passes 3/3, no regression in 878 tests, L4. Two defects found on the way: an assertion's
  traceback never shows the code (the code the test calls is now found), and a 17 KB file exceeds the 20 KB
  per-call cap (excerpts, as FixLab). Spend: US$0.007 from s13-dev.
- 2026-11-04 · cleanup and regressions · Disk nearly full: Level A on 0.16.0 stopped at 15/39 (and an orphaned
  `unbidden watch` daemon of its home). Removed Unbidden's containers, images, build cache, named volumes, the CI
  environment cache and the campaign copies; 229 orphaned anonymous volumes identified (database data of CI services
  and sidecars, 26 Oct to 3 Nov, unused) and removed; Hosli's non-main stacks removed on David's word, ~/hosli main
  kept. 75 GB free -> 305 GB. The 15 records showed three regressions (marshmallow, pyjwt, timetracker), all in the
  measurement of the CI-job environment; fixed in 0.17.1 (marshmallow 1192, pyjwt 476, timetracker 169, humanize 878
  as control). US$0.
- 2026-11-04 · 0.18.0 · Built for the large autonomous run (David: many PRs, merges and L5, not only latency; every
  model answer as evidence). Unbidden brings an app up by itself (`unbidden host up`), L5 by verified deploy for
  security/quality/correctness, transcripts and `unbidden export`, the harness at scale. Real bring-ups on codex-lb,
  misago and TimeTracker taught seven general fixes (placeholder secrets, migrations in the app service,
  Flask-Migrate, local TLS, the seeder's separator, the drill across migrations, recon after a bring-up). Rehearsal on
  fst, rich, codex-lb (US$0.33, s13-dev): fst merged and deployed a security bump to L5 by verified deploy — the
  first L5 that is not latency; rich correctly proposed nothing; codex-lb ran autonomous on its own bring-up. Four
  defects found and fixed: Dependabot on the copies, a stale proposal never measured again, the exported spend of
  other campaigns, the tests' environment taken before the last test step.
- 2026-11-04 · final pass, starts · Launched on this Mac (David), 6 workers, OrbStack raised to 44 GB. Two product
  defects stopped it, both general, each fixed with its test and released before going on: (1) 0.18.1, five minutes
  in: sqlmodel, a library whose compose file serves its tests, refused at start ("recon incomplete: stack down")
  although its mandate denied deploys; a merge needs no running stack (0.18.2). (2) 0.18.2, half an hour in: six
  libraries ended with no proposal, because wherever the team's CI job prepares the environment its Python keeps the
  project where the job wants it (tox's environment), so the robustness probe found no pytest, mypy no `/deps/.venv`
  and the advisories listed nothing, silently, since 0.16.0. Unbidden's own environment now goes beside the CI job's
  (0.18.3); on marshmallow: mypy 3 findings, advisories 29, 6 opportunities where there were none, the probe runs.
  The partial records are kept (`final-0.18.1-aborted`, `final-0.18.2-stopped`, about US$0.23 of s13-final). The
  0.18.1 partial records were committed to main by mistake with 0.18.2 and are moved there.
- 2026-11-04 · final pass on 0.18.3, stopped after 13 libraries · Every library opened nothing; the records showed
  three more general causes, all in the security class: a requirement in `pyproject.toml` could not be bumped
  (pyjwt), the candidate's packages were read from the CI job's image and an unread list declined silently
  (marshmallow: advisories gone, suite 3/3 green, "no proven fix"), and `uv lock --upgrade-package` was given only the
  manifests (sqlmodel: pdm needs the licence and the package). The robustness lab's reproduction had the 0.18.3 cause
  too. Fixed in 0.18.4 with tests; conduit's own Dockerfile does not build (poetry 1.1), recorded. Records kept in
  `final-0.18.3-stopped`.
