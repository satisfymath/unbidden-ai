# Scale benchmark: pilot-2

Unbidden at `f64fafd53aae`; manifest `bench/repos/scale.yaml`; settings {'split': 'pilot', 'workers': 2, 'minutes': 25.0, 'repo_budget': 0.08, 'profile': 'frontier', 'local_fallback': 'deny', 'fork_owner': 'satisfymath'}.
Nobody chose an opportunity, an experiment or a fix; no person intervened during the runs.
Code under test differed between rows: ['045d7756538f', 'f64fafd53aae'].

## Rates

| Measure | Eligible | Result |
|---|---|---|
| Stack supported | all repositories | 8/10 = 80% (95% CI 49%-94%) |
| Bootstrap (an analyzer complete or a probe run) | all repositories | 7/10 = 70% (95% CI 40%-89%) |
| At least one opportunity found | bootstrapped | 1/7 = 14% (95% CI 3%-51%) |
| Experiments that validated (L4) | experiments with a verdict | 1/2 = 50% (95% CI 9%-91%) |
| Repositories with an L4 improvement | bootstrapped | 1/7 = 14% (95% CI 3%-51%) |
| Level 5 (verified deployed effect) | repositories with an authorized deployment | n/a: none here; these are third parties' upstreams and the mandate denies deploys |
| Opportunities declined by the Director | opportunities | 3/4 = 75% (95% CI 30%-95%) |
| Opportunities the lab could not measure | opportunities | 0/4 = 0% (95% CI 0%-49%) |
| Cycles past the wall-clock limit | all repositories | 0/10 = 0% (95% CI 0%-28%) |

False positives need a person to label each finding; they are not measured here. A declined or unmeasured
opportunity is not counted as a false positive.

## Cost and time

- Remote spend: US$0.1408 in total (list price x reported tokens; worst cost where unknown).
- Per bootstrapped repository: US$0.0201.
- Per opportunity found: US$0.0352.
- Per validated improvement: US$0.1408.
- Local model compute: 0.0 min.
- Time to first validated improvement (min): [1.2].
- Robustness probes decided: 5 (5 run).
- Capabilities built by Forge: 0.

## Per repository

| Repository | Language | Shape | Outcome | Analyzers complete | Opportunities | Experiments | L4 | US$ | Minutes | Max RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|
| pyjwt | Python | library | bootstrap failed | 0/0 | 0 | 0 | 0 | 0.0000 | 0.3 | 129.4 |
| humanize | Python | library | nothing found | 1/2 | 0 | 0 | 0 | 0.0135 | 0.4 | 128.6 |
| starlette | Python | web framework | nothing found | 2/2 | 0 | 0 | 0 | 0.0353 | 0.9 | 139.2 |
| healthchecks | Python | application | nothing found | 1/1 | 0 | 0 | 0 | 0.0110 | 0.7 | 158.1 |
| ky | TypeScript | library | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.1 | 127.8 |
| express | JavaScript | web framework | nothing found | 1/1 | 0 | 0 | 0 | 0.0000 | 0.1 | 128.0 |
| ufo | TypeScript | library | nothing found | 2/2 | 0 | 0 | 0 | 0.0000 | 0.1 | 125.1 |
| cobra | Go | library | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 125.6 |
| sinatra | Ruby | web framework | unsupported stack | 0/0 | 0 | 0 | 0 | 0.0000 | 0.1 | 125.8 |
| marshmallow | Python | library | validated improvement (L4) | 2/2 | 4 | 2 | 1 | 0.0810 | 2.5 | 135.8 |

## Why each repository ended where it did

- **pyjwt** (bootstrap failed): pyproject.toml without uv.lock: dependencies resolved at provisioning time; dependency image for python failed to build:
error: Failed to build `pyjwt @ file:///deps`
  cause: The build backend returned an error
  cause: Call to `setuptools.build_meta.get_requires_for_build_editable` failed (exit status: 1)
             pyprojecttoml.apply_configuration(self, filename, ignore_option_errors)
             config = read_configuration(filepath, True, ignore_option_errors, dist)
             return expand_configuration(asdict, root_dir, ignore_option_errors, dist)
             return _ConfigExpander(config, root_dir, ignore_option_errors, dist).expand()
             raise ModuleNotFoundError(module_name)
         ModuleNotFoundError: jwt
ERROR: process "/bin/sh -c uv sync --no-install-project --all-groups --project /deps  && (/deps/.venv/bin/python -c \"import pytest\" 2>/dev/null      || uv pip install --python /deps/.venv/bin/python pytest==9.1.1      || uv pip install --python /deps/.venv/bin/python pytest)  && (/deps/.venv/bin/python -c \"import hypothesis\" 2>/dev/null      || uv pip install --python /deps/.venv/bin/python hypothesis==6.170.12      || uv pip install --python /deps/.venv/bin/python hypothesis)" did not complete successfully: exit code: 1
0.594              raise ModuleNotFoundError(module_name)
0.594          ModuleNotFoundError: jwt
--------------------
ERROR: failed to build: failed to solve: process "/bin/sh -c uv sync --no-install-project --all-groups --project /deps  && (/deps/.venv/bin/python -c \"import pytest\" 2>/dev/null      || uv pip install --python /deps/.venv/bin/python pytest==9.1.1      || uv pip install --python /deps/.venv/bin/python pytest)  && (/deps/.venv/bin/python -c \"import hypothesis\" 2>/dev/null      || uv pip install --python /deps/.venv/bin/python hypothesis==6.170.12      || uv pip install --python /deps/.venv/bin/python hypothesis)" did not complete successfully: exit code: 1; probe: investigate (probe jwt (38 public functions sampled)); probe result: environment: dependency image for python failed to build:
error: Failed to build `pyjwt @ file:///deps`
  cause: The build backend returned an error
  cause: Call to `setuptools.build_me
- **humanize** (nothing found): pyproject.toml without uv.lock: dependencies resolved at provisioning time; mypy: failed /deps/.venv/bin/python: No module named mypy; probe: investigate (probe src/humanize (15 public functions sampled)); probe result: 8 passed in 0.96s
- **starlette** (nothing found): probe: investigate (probe starlette (77 public functions sampled)); probe result: 8 passed in 1.19s
- **healthchecks** (nothing found): probe: investigate (probe hc (80 public functions sampled)); probe result: igured: Requested setting INSTALLED_APPS, but settings are not configured. You must either define the environment variable DJANGO_SETTINGS_MODULE or call settings.configure() before acce
- **ky** (nothing found): package.json without a lockfile: dependencies resolved at provisioning time
- **express** (nothing found): package.json without a lockfile: dependencies resolved at provisioning time
- **ufo** (nothing found): nothing to report
- **cobra** (unsupported stack): Go (go.mod) is not analyzed: no checks, probes or experiments for that code
- **sinatra** (unsupported stack): Ruby (Gemfile) is not analyzed: no checks, probes or experiments for that code
- **marshmallow** (validated improvement (L4)): probe: investigate (probe src/marshmallow (38 public functions sampled)); probe result: 8 passed in 1.27s; opp_efbdf021116448f6: declined, the team's CI does not run ruff: its style is not the team's standard; opp_3eae04f4b6f34609: declined, the team's CI does not run ruff: its style is not the team's standard; opp_1d7a7d72c3ee43ba: declined, 2 experiments found no proven fix; opp_eb00e1507b2a4219: proposed, evidence L4 meets the mandate's L4

## Notes added after the run (the record above is as produced)

- **Code under test.** Rows record `HEAD`. A commit made during the run (`f64fafd`, `docs/EVIDENCE.md` only) moved it;
  `git diff 045d775 f64fafd -- unbidden` is empty, so every row ran the same Unbidden code. From now on the harness
  records the content hash of the `unbidden/` tree.
- **marshmallow, two opportunities from mypy (the team's mypy job is green on this commit):**
  - `tests/test_fields.py`, the false positive of pilot 1: Muse Spark's candidate passed under Python 3.10 and was
    **rejected by CI parity**: under 3.14, which the team's CI runs, mypy reports 2 new findings. After 2 experiments
    the Director declined it.
  - `src/marshmallow/fields.py` ("Module 'typing' has no attribute 'Unpack'" under 3.10): the candidate replaces
    `try: from typing import Unpack / except ImportError` with a `sys.version_info` check. It is clean under 3.10 and
    3.14 and behavior-preserving, so the lab's L4 holds. It is not an improvement to the team's product: their CI does
    not type-check under 3.10. The Director should have declined it as an environment finding and did not: it could
    not tell that the CI runs mypy, which happens through `tox -e ${{ matrix.tox }}` and tox.ini. Counted here as
    **an L4 outside the team's checked configuration, not a validated improvement**.
- **Publishing.** The branch was pushed to the fork `satisfymath/marshmallow` (`185c5f5`), never upstream. The pull
  request failed with GitHub 422: the mandate's base was `main`, and the fork's default branch is `dev`. A shallow
  fetch has no `origin/HEAD`, so `init` assumed `main`.
- **pyjwt** did not bootstrap: its version is dynamic from `jwt.__version__`, and the build context holds only
  manifests.
- **Spend.** US$0.141, Muse Spark only; the local model was never called (local fallback denied, 0 fallbacks).
