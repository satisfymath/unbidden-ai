# Scale benchmark: holdout-1

Unbidden at `b23e8b0bbaf8`; manifest `bench/repos/scale.yaml`; settings {'split': 'holdout', 'workers': 2, 'minutes': 25.0, 'repo_budget': 0.08, 'profile': 'frontier', 'local_fallback': 'deny', 'fork_owner': 'satisfymath'}.
Nobody chose an opportunity, an experiment or a fix; no person intervened during the runs.

## Rates

| Measure | Eligible | Result |
|---|---|---|
| Stack supported | all repositories | 8/10 = 80% (95% CI 49%-94%) |
| Bootstrap (an analyzer complete or a probe run) | all repositories | 7/10 = 70% (95% CI 40%-89%) |
| At least one opportunity found | bootstrapped | 1/7 = 14% (95% CI 3%-51%) |
| Experiments that validated (L4) | experiments with a verdict | n/a (0 eligible) |
| Repositories with an L4 improvement | bootstrapped | 0/7 = 0% (95% CI 0%-35%) |
| Level 5 (verified deployed effect) | repositories with an authorized deployment | n/a: none here; these are third parties' upstreams and the mandate denies deploys |
| Opportunities declined by the Director | opportunities | 5/5 = 100% (95% CI 57%-100%) |
| Opportunities the lab could not measure | opportunities | 0/5 = 0% (95% CI 0%-43%) |
| Cycles past the wall-clock limit | all repositories | 0/10 = 0% (95% CI 0%-28%) |

False positives need a person to label each finding; they are not measured here. A declined or unmeasured
opportunity is not counted as a false positive.

## Cost and time

- Remote spend: US$0.0549 in total (list price x reported tokens; worst cost where unknown).
- Per bootstrapped repository: US$0.0078.
- Per opportunity found: US$0.0110.
- No validated improvement, so no cost per improvement.
- Local model compute: 0.0 min.
- No validated improvement.
- Robustness probes decided: 5 (4 run).
- Capabilities built by Forge: 0.

## Per repository

| Repository | Language | Shape | Outcome | Analyzers complete | Opportunities | Experiments | L4 | US$ | Minutes | Max RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|
| markupsafe | Python | library | found, not experimented | 3/3 | 5 | 0 | 0 | 0.0000 | 0.5 | 126.5 |
| attrs | Python | library | nothing found | 3/3 | 0 | 0 | 0 | 0.0146 | 0.8 | 132.5 |
| tablib | Python | library | nothing found | 1/1 | 0 | 0 | 0 | 0.0137 | 0.4 | 129.0 |
| datasette | Python | application | nothing found | 1/1 | 0 | 0 | 0 | 0.0102 | 0.7 | 150.0 |
| requests | Python | library | nothing found | 2/2 | 0 | 0 | 0 | 0.0163 | 0.6 | 143.9 |
| cookie | TypeScript | library | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.2 | 126.9 |
| fast-json-stringify | JavaScript | library | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.5 | 125.5 |
| anyhow | Rust | library | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 125.7 |
| node-fetch | JavaScript | library | bootstrap failed | 0/0 | 0 | 0 | 0 | 0.0000 | 0.9 | 126.9 |
| chi | Go | library | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 125.5 |

## Why each repository ended where it did

- **markupsafe** (found, not experimented): probe: decline (no importable package with public functions under the source roots); opp_a1ee0d4dd30b4743: declined, the team's CI runs pyright and passes on this commit: these findings come from Unbidden's environment; opp_0a93c7f1f1cc49df: declined, the team's CI runs pyright and passes on this commit: these findings come from Unbidden's environment; opp_e59278570a614651: declined, the team's CI runs pyright and passes on this commit: these findings come from Unbidden's environment; opp_f05988f3fe86402f: declined, the team's CI runs pyright and passes on this commit: these findings come from Unbidden's environment; opp_56ea7c7551274ac2: declined, the team's CI runs pyright and passes on this commit: these findings come from Unbidden's environment
- **attrs** (nothing found): probe: investigate (probe src/attr (8 public functions sampled)); probe result: 2 failed, 3 passed in 1.90s
- **tablib** (nothing found): pyproject.toml without uv.lock: dependencies resolved at provisioning time; probe: investigate (probe src/tablib (30 public functions sampled)); probe result: 2 failed, 6 passed in 2.30s
- **datasette** (nothing found): pyproject.toml without uv.lock: dependencies resolved at provisioning time; probe: investigate (probe datasette (80 public functions sampled)); probe result: 8 passed in 1.37s
- **requests** (nothing found): pyproject.toml without uv.lock: dependencies resolved at provisioning time; probe: investigate (probe src/requests (50 public functions sampled)); probe result: 9 passed in 2.11s
- **cookie** (nothing found): nothing to report
- **fast-json-stringify** (nothing found): package.json without a lockfile: dependencies resolved at provisioning time
- **anyhow** (unsupported stack): Rust (Cargo.toml) is not analyzed: no checks, probes or experiments for that code
- **node-fetch** (bootstrap failed): package.json without a lockfile: dependencies resolved at provisioning time
- **chi** (unsupported stack): Go (go.mod) is not analyzed: no checks, probes or experiments for that code

## Notes added after the run (the record above is as produced; run once, under the frozen protocol)

- Every row ran the frozen `unbidden/` tree `bca94f9` (`2026-10-28-holdout-protocol.md`). Nothing was changed during
  or because of the run.
- **markupsafe**: five pyright opportunity groups, all declined before any experiment: the team's CI runs pyright and
  passes on this commit. The rule generalized to a tool and a repository it was not developed on. No probe ran: the
  package defines its public API in `__init__.py`, and the probe's sampler skipped every file whose name starts with
  `_`, `__init__.py` included. A general gap, recorded here and fixed afterwards on development data.
- **node-fetch**: Node was detected and its dependencies installed, but no analyzer applies (it lints with `xo` and
  tests with mocha; Unbidden runs tsc, eslint, biome and prettier) and probes exist only for Python. Classified
  "bootstrap failed" by the rules fixed before pilot 1; the cause is a missing capability, not an error.
- **anyhow** (Rust) and **chi** (Go): unsupported, named as blind spots.
- Five probes ran (attrs, tablib, datasette, requests, and none on markupsafe): no crash inside a package. A probe is
  a sample (humanize: 1 of 13); "nothing found" means nothing found by one probe.
- No fallback to the local model; US$0.055 in total.
