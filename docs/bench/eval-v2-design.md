# Evaluation v2: scenarios with a known truth (PR16), design fixed before any run

Coverage runs (dev/validation/holdout of the 100-repository corpus) say how far Unbidden gets into a repository.
They cannot say whether what it found was real, whether it chose well, or whether a promotion was earned, because
nobody knows the truth of those repositories. v2 adds scenarios whose truth the evaluator knows and the agent does
not. Development only: the corpus's validation and holdout stay untouched until a candidate and its protocol are
frozen.

## Five capabilities, scored apart

| Capability | Question | Scored on |
|---|---|---|
| Discovery | Did it find the planted opportunity without being told where it is? | recall over planted defects; precision over what it would act on |
| Decision | Did it choose a useful, proportionate action? | the chosen action is in the scenario's acceptable set |
| Execution | Did the investigation or experiment it chose run correctly? | ran / blocked / failed, with the reason |
| Result | Did it produce a valid improvement? | the oracle's hidden check passes with the candidate, the repository's suite validates it; false promotions to L4 |
| Abstention | Did it refrain where nothing was worth doing or the evidence was not enough? | no experiment or proposal on healthy, low-value and environment scenarios |

No count of actions taken or findings declined is a score by itself.

## Separation of agent and oracle

Each scenario is generated into its own git repository with neutral history (`initial import`, `update`): code, the
project's own tests and CI declaration, nothing else. The oracle (`bench/eval2/oracle/<id>.json` plus hidden
checks) lives outside that repository and is read only by the scorer, after the agent finished. Names, comments and
commit messages in a scenario never say what was planted. The agent may run the repository's own tests; it never
sees the hidden checks.

## Scenarios (development set)

| Id | Kind | What it holds | Acceptable decisions | Truth |
|---|---|---|---|---|
| crash-shadowed-import | planted defect | a handler whose local import makes a module name local to the whole function: one branch raises `UnboundLocalError`; no project test covers it | experiment | one opportunity at the planted line; a fix passes the hidden check |
| hidden-duplicate-test | planted defect | a test class defined twice; the first copy's tests never run | experiment | one opportunity; fixed when both copies' tests run |
| healthy | healthy system | the base project, unchanged | wait, decline | nothing worth acting on |
| vendored-noise | environment | vendored third-party code the project excludes from its own linting, which Unbidden's baseline rules flag | wait, decline | the findings are not this project's defects |
| low-value-style | low value | style findings in a scripts directory the CI never checks | decline | not worth a person's review |
| unmeasured-fk | needs measurement | a foreign key without an index; the data volume is not known | measure / investigate, wait | its value depends on rows not yet observed |
| unread-logs | missing capability | a slow-endpoint opportunity whose priority needs traffic per route; the service's access log has no reader | acquire capability, wait | the need must be filled (built or reused) before deciding |
| data-growth | data change without a commit | a declined index opportunity whose table then grows from 10,000 to 30,000 rows, same commit | reopen, then experiment | the decline no longer holds |
| flaky-candidate | apparent improvement | a candidate that "improves" while a test fails more often with it | no promotion | not L4 |
| noise-improvement | apparent improvement | before/after samples from the same distribution | no promotion | not improved |
| suite-never-ran | apparent improvement | a candidate measured while the suite crashed on both sides (D-035's case) | no promotion | not L4 |

## Three ways of running them

1. **Director only, same input.** Each policy decides the same opportunity sets: for planted repositories, the set
   one scan with the current scanner produced, frozen to a file; for world-level scenarios, a synthetic set. This
   separates a better decision from better discovery.
2. **Evaluator only.** The planted evidence of the last three scenarios goes through each version's judge.
3. **Whole product from the initial state.** `init`, `scan`, `map`, `decide`, then the chosen experiments with the
   real local model (Muse Glimmer through Ollama), on the scenario repository alone: no opportunity or ticket given.
   Model, configuration, calls, durations and results are recorded from the workspace's own state. If the local
   model is not available, this part is reported as pending, never replaced by a mock.

## Policies compared

- **Previous:** the Director at `d7a53a0` (feat/20-scale-eval, before the plan's PRs), run from its own worktree.
- **Current:** the commit under evaluation.
- **Act on everything:** experiment on every open opportunity, a simple reference.

Same scenarios, same access, same budgets (no remote model, US$0; local model as configured).

## Reported

Per scenario and in aggregate, with denominators: discovery recall and precision where the truth is known, decision
accuracy, executions by outcome, false promotions to L4, regressions, abstentions where due, blocks, model calls,
local compute time, wall time, human approvals asked. A version is not promoted on an aggregate that hides a
regression in any scenario.

## What it cannot show

Behaviour on systems unlike these small ones; value for a real team; anything about remote models. Scenarios are
written by the same people who write Unbidden: they test what we thought of. That is why the corpus's validation and
holdout remain the independent check, run once a candidate is frozen.
