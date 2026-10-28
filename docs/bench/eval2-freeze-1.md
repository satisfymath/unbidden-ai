# Evaluation v2, freeze 1 (2026-10-28): what is compared, fixed before the evaluation set ran

The evaluation set (`bench/eval2/eval_set.py`, `cases.py --set eval`, committed b639c5a) has not run. Nothing below
changes after it does; a result that disappoints is reported as it is.

| Version | Commit | `unbidden/` tree | What it is |
|---|---|---|---|
| prev | d7a53a0 | 0c0879d | before the plan's PRs (v4) |
| pre-PR12 | cf0de42 | a379a8e | PR1–PR15 and the mealie fixes, without PR12's actions |
| candidate | b639c5a | 468180f | PR12 completed (f697d18); `unbidden/` unchanged since |
| act on everything | — | — | experiment on every opportunity (Director-only cases) |

- **Model:** `muse-glimmer:30b-mxfp8-dflash` (Ollama id 14bd0cb8d43f, 32.3B, mxfp8), profile `local`, through each
  version's own router. Prompts: the version's `unbidden/brain/prompts` (candidate tree c3fc32e).
- **Budget:** no remote model (mandate `remote_models.destinations: []`, spend cap US$0); one experiment per
  planted repository, in the Director's order; `run_product.py`'s timeouts.
- **Criteria:** `bench/eval2/score.py` at b639c5a (a finding within 2 lines of a planted line is that defect;
  results checked by the project's tests plus the hidden check on a clean copy).
- **Inputs alike:** Director-only cases from one scan by the candidate's scanner of the evaluation repositories,
  frozen, with the CI context read once.
- **Order:** generate the set; product (scan, decide, experiments) per version; freeze opportunities; Director-only
  per version; score once.
