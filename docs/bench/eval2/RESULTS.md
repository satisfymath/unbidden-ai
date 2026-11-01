# Evaluation v2: results so far (2026-10-28)

Design `../eval-v2-design.md`; freeze `../eval2-freeze-1.md`. Records in `dev/` (debugged on) and `eval-freeze-1/`
(run once, after the freeze). US$0 remote; local model `muse-glimmer:30b-mxfp8-dflash` through Ollama.

## What was run

- **Deterministic:** the unit suite (452), ruff, pyright, at each commit; the evaluator and world cases through each
  version's own code (no model).
- **With the real local model:** the whole product from the initial state (`init`, `scan`, `decide`, one experiment
  per planted repository) on the development set (prev, pre-PR12) and on the evaluation set (prev, pre-PR12,
  candidate). 2 model calls per version per set, about 30 s of local compute each (`model_seconds` per row).

## Evaluation set (frozen, run once)

**Director only, same inputs** (11 cases: 5 decisions on opportunities a scan found, 2 world-level decisions, 1 data
change, 3 planted evidence for the judge):

| Policy | As the oracle accepts | False L4 |
|---|---|---|
| prev (d7a53a0) | 4 / 11 | 0 |
| pre-PR12 (cf0de42) | 5 / 11 | 0 |
| **candidate (b639c5a)** | **9 / 11** | 0 |
| act on everything | 1 / 7 (decisions only) | — |

Candidate against prev, paired on the same 11 cases: 5 the candidate gets right and prev does not, 0 the other way;
exact McNemar p = 0.0625. Not significant at 0.05 on this n.

**Whole product from the initial state** (5 repositories):

| | prev | pre-PR12 | candidate |
|---|---|---|---|
| Discovery: planted defects found | 1/2 | 1/2 | 1/2 |
| Actions on real defects / all actions | 1/5 | 1/5 | 1/3 |
| Decisions the oracle accepts | 2/5 | 2/5 | 3/5 |
| Abstained where due | 1/3 | 1/3 | 2/3 |
| Valid improvements (oracle) | 2 (one is a style fix in examples) | 2 (same) | 1 |
| False L4 | 0 | 0 | 0 |
| Wall time, s | 86 | 85 | 80 |

Per scenario: every version fixed `debit-identity` (`is` against a string literal) with the local model, L4, and the
hidden check passes. No version reported `shared-default` (a mutable default that skips a second import): a
discovery miss. Every version acted on `fixture-injection`, pyflakes reading a fixture injected by name as a
redefinition (F811): environment noise, cause 2 of `../eval/discovery-audit-v3.md`, still unfixed; the lab rejected
the model's candidate as a regression, so nothing was promoted. Only the candidate declined `example-style`.

## Development set (debugged on; not evidence of generalization)

Director only: prev 4/9 (1 false L4: a suite that never ran), pre-PR12 6/9, candidate 9/9 after two dev fixes
(the linter's own scope for style findings; CI context in the cases). Product: both versions found both planted
defects and fixed them with the local model to oracle-valid L4.

## What it shows, and what it does not

- Shows: on the same inputs, the candidate's Director chooses a measurement, a capability or a decline where the
  previous ones experimented, without losing any case they got right; no version promotes planted invalid evidence
  except prev on a suite that never ran (development set).
- Does not show a better product overall: discovery is unchanged (1/2), and the two misses are discovery's.
- Circularity, stated: the acceptable actions of the measurement and capability cases were defined by the same
  person who defined those actions (PLAN.md, PR12). They test that the actions fire where intended and nowhere else
  in these cases, not that they are the right policy for a real team. The corpus's validation and holdout remain the
  independent check.
- Small n: 11 and 5 cases; one run each, the model at its default sampling (no seed is set).

## Next, and what allows it

- Dev hypotheses from the evaluation set (not fixed from it): ruff-baseline's B006 not reported where the project
  configures ruff; fixture parameters read as F811.
- PR13 (memory) needs repeated runs: an ablation (with and without the learned success chance and lab notes) over the
  development scenarios, then a new frozen evaluation set.
- Validation of the corpus: once a candidate is frozen for it, as the protocol says.
