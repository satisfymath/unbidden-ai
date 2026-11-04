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
