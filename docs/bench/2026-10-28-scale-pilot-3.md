# Scale benchmark: pilot-3

Unbidden at `2b5d97b41abc`; manifest `bench/repos/scale.yaml`; settings {'split': 'pilot', 'workers': 2, 'minutes': 25.0, 'repo_budget': 0.08, 'profile': 'frontier', 'local_fallback': 'deny', 'fork_owner': 'satisfymath'}.
Nobody chose an opportunity, an experiment or a fix; no person intervened during the runs.

## Rates

| Measure | Eligible | Result |
|---|---|---|
| Stack supported | all repositories | 8/10 = 80% (95% CI 49%-94%) |
| Bootstrap (an analyzer complete or a probe run) | all repositories | 8/10 = 80% (95% CI 49%-94%) |
| At least one opportunity found | bootstrapped | 1/8 = 12% (95% CI 2%-47%) |
| Experiments that validated (L4) | experiments with a verdict | n/a (0 eligible) |
| Repositories with an L4 improvement | bootstrapped | 0/8 = 0% (95% CI 0%-32%) |
| Level 5 (verified deployed effect) | repositories with an authorized deployment | n/a: none here; these are third parties' upstreams and the mandate denies deploys |
| Opportunities declined by the Director | opportunities | 4/4 = 100% (95% CI 51%-100%) |
| Opportunities the lab could not measure | opportunities | 0/4 = 0% (95% CI 0%-49%) |
| Cycles past the wall-clock limit | all repositories | 0/10 = 0% (95% CI 0%-28%) |

False positives need a person to label each finding; they are not measured here. A declined or unmeasured
opportunity is not counted as a false positive.

## Cost and time

- Remote spend: US$0.0880 in total (list price x reported tokens; worst cost where unknown).
- Per bootstrapped repository: US$0.0110.
- Per opportunity found: US$0.0220.
- No validated improvement, so no cost per improvement.
- Local model compute: 0.0 min.
- No validated improvement.
- Robustness probes decided: 5 (5 run).
- Capabilities built by Forge: 0.

## Per repository

| Repository | Language | Shape | Outcome | Analyzers complete | Opportunities | Experiments | L4 | US$ | Minutes | Max RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|
| pyjwt | Python | library | nothing found | 1/2 | 0 | 0 | 0 | 0.0170 | 0.4 | 129.9 |
| humanize | Python | library | nothing found | 1/2 | 0 | 0 | 0 | 0.0180 | 0.5 | 128.9 |
| marshmallow | Python | library | found, not experimented | 2/2 | 4 | 0 | 0 | 0.0239 | 0.6 | 134.0 |
| starlette | Python | web framework | nothing found | 2/2 | 0 | 0 | 0 | 0.0156 | 0.6 | 140.0 |
| ky | TypeScript | library | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.1 | 127.5 |
| express | JavaScript | web framework | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.2 | 127.9 |
| healthchecks | Python | application | nothing found | 1/1 | 0 | 0 | 0 | 0.0135 | 0.5 | 157.5 |
| ufo | TypeScript | library | nothing found | 2/2 | 0 | 0 | 0 | 0.0000 | 0.2 | 125.1 |
| cobra | Go | library | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 125.6 |
| sinatra | Ruby | web framework | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 125.8 |

## Why each repository ended where it did

- **pyjwt** (nothing found): pyproject.toml without uv.lock: dependencies resolved at provisioning time; mypy: failed /deps/.venv/bin/python: No module named mypy; probe: investigate (probe jwt (38 public functions sampled)); probe result: 2 failed, 6 passed in 1.06s
- **humanize** (nothing found): pyproject.toml without uv.lock: dependencies resolved at provisioning time; mypy: failed /deps/.venv/bin/python: No module named mypy; probe: investigate (probe src/humanize (15 public functions sampled)); probe result: 1 failed, 7 passed in 1.45s
- **marshmallow** (found, not experimented): probe: investigate (probe src/marshmallow (38 public functions sampled)); probe result: 8 passed in 1.47s; opp_b291db9419914170: declined, the team's CI runs ruff and passes on this commit: these findings come from Unbidden's environment; opp_c8f8065e935b43c5: declined, the team's CI runs ruff and passes on this commit: these findings come from Unbidden's environment; opp_6c0524bd52a54d91: declined, the team's CI runs mypy and passes on this commit: these findings come from Unbidden's environment; opp_2c781139de5d4a77: declined, the team's CI runs mypy and passes on this commit: these findings come from Unbidden's environment
- **starlette** (nothing found): probe: investigate (probe starlette (77 public functions sampled)); probe result: 2 failed, 6 passed in 1.21s
- **ky** (nothing found): package.json without a lockfile: dependencies resolved at provisioning time
- **express** (nothing found): package.json without a lockfile: dependencies resolved at provisioning time
- **healthchecks** (nothing found): probe: investigate (probe hc (80 public functions sampled)); probe result: igured: Requested setting INSTALLED_APPS, but settings are not configured. You must either define the environment variable DJANGO_SETTINGS_MODULE or call settings.configure() before acce
- **ufo** (nothing found): nothing to report
- **cobra** (unsupported stack): Go (go.mod) is not analyzed: no checks, probes or experiments for that code
- **sinatra** (unsupported stack): Ruby (Gemfile) is not analyzed: no checks, probes or experiments for that code

## Notes added after the run (the record above is as produced)

- Same `unbidden/` tree for every row (`2c3f8d9`); the fixes of pilot 2 under test.
- **marshmallow**: the Director declined all four opportunities before any experiment: "the team's CI runs mypy (ruff)
  and passes on this commit: these findings come from Unbidden's environment". It read that through tox and the parent
  repository's checks; no rule names marshmallow. Pilot 1 had reported an L4 here, a false positive.
- **pyjwt** bootstrapped (its computed version is now static in the build context).
- **healthchecks**: the probe's tests did not run: Django's settings were not configured when they imported the
  package. A systematic failure for Django applications, fixed in general after this run.
- No fallback to the local model was attempted; US$0.088.
