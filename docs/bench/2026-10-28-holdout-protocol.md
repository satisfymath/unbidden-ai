# Holdout protocol, frozen before the run (2026-10-28)

The ten `holdout` repositories of `bench/repos/scale.yaml` (pinned 2026-10-27, before any run) are run **once**, under
the conditions below. Nothing in Unbidden, its prompts, its criteria or this protocol changes because of what the
holdout shows. Fixes the holdout suggests are recorded and tested on development data afterwards.

| Frozen | Value |
|---|---|
| Unbidden code | `unbidden/` tree `bca94f907b35f191ecfde1579768dbfc874be7a8` (commit `3ebad11`) |
| Prompts | in that tree; sha256 prefixes: robustness_tests `43ce165874e08787`, robustness_refine `d16a3b634c8dc95f`, fix_findings `a63b781b0c833108`, fix_excerpts `f0a5390775331878`, robust_fix `cd792641e09f2ccd`, perf_workload `ade2c0bf0ce2e954`, perf_candidate `aea322acdfa03613` |
| Models | remote `muse-spark-1.3` (Standard) for every tier that leaves; the provider may update the model behind that name, which cannot be pinned from here. Local fallback **denied** |
| Profile | `frontier`; private code to frontier denied; public code confirmed by GitHub |
| Criteria | lab evaluator `CRITERIA` and CI parity as in the tree; Director rules as in the tree; L5 not eligible (no deployment) |
| Outcome classes | `bench/scale.py:classify`, unchanged since pilot 1 except that a probe counts as bootstrap only when its tests ran |
| Harness | `bench/scale.py`, workers 2, 25 minutes per repository, US$0.08 per repository, forks under `satisfymath` (pull requests there only, never upstream, no merges) |
| Budget | no verified credit balance: the US$1 unverified allowance, about US$0.51 left before the run |
| Development history | pilot 1 (method check), pilots 2 and 3, and the fixes between them: D-037, D-038 |

Reported as it comes out: every repository, every outcome, every failure. The same report generator as the pilots.
