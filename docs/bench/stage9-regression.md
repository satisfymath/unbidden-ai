# Stage 9: development regressions on Conduit and LNbits (not independent evidence)

Conduit and LNbits were both used to develop Unbidden (stages 7-9); nothing here is out-of-sample. These runs check
the stage 9 version before the frozen evaluation: the corrected performance criteria (perf-v3), completeness judged
by behaviour, proactive consistency questions, lab ownership, and Meta's API as the only model backend.

**Models and budget (D-052):** every workspace's mandate says `profile: frontier`, `private_code_to_frontier: allow`
(the code is public), `local_fallback: deny`, `local_inference: deny`; routes `muse-spark-1.3`. Every call is charged
to the `dev` envelope (US$12, enforced before each call). Wonder, vision and SAM: not used unless a run records why.

**Conduit** (`bench/ecosystem/conduit_eval.py --envelope dev`): runs `R9-B<n>` (proactive, no goal) then `R9-A<n>`
(the stage 7 general goal, unchanged: no index, file or defect named), each from a restored state (repository at
029eb77, data re-seeded, fresh token, a new `.unbidden`); two cycles, the one declared answer (a package registry
Unbidden names), two more cycles; the workspace archived whole. Measured: reproduction before experimenting;
experiments under perf-v3 (outcome per candidate); proposals; the second cycle repeating nothing; reads and their
completeness; consistency questions and how they ended; requests to a person; time; spend per run from the ledger.
`articlesCount` stays a person's observation: if a consistency question reaches it, that is reported as found by a
check written after the observation, on a development project, not as an autonomous discovery.

**LNbits** (`bench/ecosystem/lnbits_eval.py --envelope dev --run R9-<n>`): proactive only, as I-1. Measured:
whether the environment is reproduced and the project's own checks run; what is found; whether an abstention is
backed by observation (tables read, checks run, questions answered) or is an inability to observe.

Every attempt is kept with the product commit it ran at (`docs/bench/stage9-regression/<version>/`). A cause found
here is fixed generally and the next attempt is a new version; none of these runs becomes evaluation evidence.
