# Scale benchmark: method-check-pilot

Unbidden at `2d8f84ef1fad`; manifest `bench/repos/scale.yaml`; settings {'split': 'pilot', 'workers': 2, 'minutes': 20.0, 'repo_budget': 0.08, 'profile': 'frontier'}.
Nobody chose an opportunity, an experiment or a fix; no person intervened during the runs.

## Rates

| Measure | Eligible | Result |
|---|---|---|
| Stack supported | all repositories | 8/10 = 80% (95% CI 49%-94%) |
| Bootstrap (an analyzer complete or a probe run) | all repositories | 7/10 = 70% (95% CI 40%-89%) |
| At least one opportunity found | bootstrapped | 1/7 = 14% (95% CI 3%-51%) |
| Experiments that validated (L4) | experiments with a verdict | 1/1 = 100% (95% CI 21%-100%) |
| Repositories with an L4 improvement | bootstrapped | 1/7 = 14% (95% CI 3%-51%) |
| Level 5 (verified deployed effect) | repositories with an authorized deployment | n/a: none here; these are third parties' upstreams and the mandate denies deploys |
| Opportunities declined by the Director | opportunities | 3/4 = 75% (95% CI 30%-95%) |
| Opportunities the lab could not measure | opportunities | 0/4 = 0% (95% CI 0%-49%) |
| Cycles past the wall-clock limit | all repositories | 0/10 = 0% (95% CI 0%-28%) |

False positives need a person to label each finding; they are not measured here. A declined or unmeasured
opportunity is not counted as a false positive.

## Cost and time

- Remote spend: US$0.0571 in total (list price x reported tokens; worst cost where unknown).
- Per bootstrapped repository: US$0.0082.
- Per opportunity found: US$0.0143.
- Per validated improvement: US$0.0571.
- Local model compute: 6.4 min.
- Time to first validated improvement (min): [7.5].
- Robustness probes decided: 5 (5 run).
- Capabilities built by Forge: 0.

## Per repository

| Repository | Language | Shape | Outcome | Analyzers complete | Opportunities | Experiments | L4 | US$ | Minutes | Max RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|
| pyjwt | Python | library | bootstrap failed | 0/0 | 0 | 0 | 0 | 0.0000 | 0.3 | 124.1 |
| humanize | Python | library | nothing found | 1/2 | 0 | 0 | 0 | 0.0135 | 0.3 | 125.2 |
| starlette | Python | web framework | nothing found | 2/2 | 0 | 0 | 0 | 0.0171 | 0.6 | 137.1 |
| healthchecks | Python | application | nothing found | 1/1 | 0 | 0 | 0 | 0.0134 | 0.9 | 147.4 |
| ky | TypeScript | library | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.1 | 122.5 |
| express | JavaScript | web framework | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.5 | 121.3 |
| ufo | TypeScript | library | nothing found | 2/2 | 0 | 0 | 0 | 0.0000 | 0.4 | 121.0 |
| cobra | Go | library | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 120.2 |
| sinatra | Ruby | web framework | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 120.2 |
| marshmallow | Python | library | validated improvement (L4) | 2/2 | 4 | 1 | 1 | 0.0131 | 7.6 | 130.4 |

## Why each repository ended where it did

- **pyjwt** (bootstrap failed): pyproject.toml without uv.lock: dependencies resolved at provisioning time; dependency image for python failed to build:
error: No solution found when resolving dependencies
  cause: Because the current Python version (3.9.25) does not satisfy Python>=3.10 and pytest==9.1.1 depends on Python>=3.10, we can conclude that pytest==9.1.1 cannot be used.
ERROR: process "/bin/sh -c ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm  && npm install -g pyright@1.1.414  && pip install --no-cache-dir uv  && uv venv /opt/tools && uv pip install --python /opt/tools/bin/python ruff==0.17.2 pytest==9.1.1" did not complete successfully: exit code: 1
4.445 error: No solution found when resolving dependencies
4.445   cause: Because the current Python version (3.9.25) does not satisfy Python>=3.10 and pytest==9.1.1 depends on Python>=3.10, we can conclude that pytest==9.1.1 cannot be used.
--------------------
ERROR: failed to build: failed to solve: process "/bin/sh -c ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm  && npm install -g pyright@1.1.414  && pip install --no-cache-dir uv  && uv venv /opt/tools && uv pip install --python /opt/tools/bin/python ruff==0.17.2 pytest==9.1.1" did not complete successfully: exit code: 1; probe: investigate (probe jwt (38 public functions sampled)); probe result: environment: dependency image for python failed to build:
error: No solution found when resolving dependencies
  cause: Because the current Python version (3.9.25) does not satisfy Pytho
- **humanize** (nothing found): pyproject.toml without uv.lock: dependencies resolved at provisioning time; mypy: failed /deps/.venv/bin/python: No module named mypy; probe: investigate (probe src/humanize (15 public functions sampled)); probe result: 2 failed, 6 passed in 1.59s
- **starlette** (nothing found): probe: investigate (probe starlette (77 public functions sampled)); probe result: 2 failed, 6 passed in 1.24s
- **healthchecks** (nothing found): probe: investigate (probe hc (80 public functions sampled)); probe result: igured: Requested setting INSTALLED_APPS, but settings are not configured. You must either define the environment variable DJANGO_SETTINGS_MODULE or call settings.configure() before acce
- **ky** (nothing found): package.json without a lockfile: dependencies resolved at provisioning time
- **express** (nothing found): package.json without a lockfile: dependencies resolved at provisioning time
- **ufo** (nothing found): nothing to report
- **cobra** (unsupported stack): Go (go.mod) is not analyzed: no checks, probes or experiments for that code
- **sinatra** (unsupported stack): Ruby (Gemfile) is not analyzed: no checks, probes or experiments for that code
- **marshmallow** (validated improvement (L4)): probe: investigate (probe src/marshmallow (38 public functions sampled)); probe result: 2 failed, 6 passed in 3.23s; opp_d768ce2a4cc24d3e: declined, the team's CI does not run ruff: its style is not the team's standard; opp_42ae9cec24844568: declined, the team's CI does not run ruff: its style is not the team's standard; opp_05e2dc8166e84435: declined, 2 experiments found no proven fix; opp_f0e429a23a214563: proposed, evidence L4 meets the mandate's L4
