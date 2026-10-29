# Stage 8: Conduit as a regression (a new version; not out-of-sample evidence)

Conduit became development when stage 8's fixes were made from its frozen run (9ef6a60, kept as it is). This run
checks the new version on it, from clean states, B before A, as in stage 7: runs `B-2` (proactive, no goal) then
`A-3` (the same general goal), with `bench/ecosystem/conduit_eval.py --runs B-2,A-3` from a worktree at the commit
named below. Same preparation as stage 7 (`stage7-transfer-prep.md`); same mandate: PyPI only as registries.

One declared human answer: if Unbidden asks to add a package registry it names, a person adds exactly that one, once,
and the run continues for two more cycles. That is counted as an intervention. Nothing else is granted or told.
The `articlesCount` defect stays Claude's observation; the agent is not told about it.

Measured: whether the project is reproduced (its checks run at the base); what is read and with which deviations;
what is found and how it is explained; whether an experiment runs and what it shows (an improvement measured with the
checks green on both sides, or a discard with evidence); what is asked of a person; the second cycle's repeats;
calls, models, latency, spend.
regression version: adb803d

## Second regression version

The first version's runs (adb803d, `B-2`, `A-3`) showed five defects, each fixed generally, none with
Conduit-specific code: one request per need and the held work released on the grant; deviations counted once per
operation, field and value; reads bounded by records (50 requests had stopped the listing at 5,000 of 20,000); and
handlers of routes mounted with `include_router` prefixes located (two endpoints had no handler, so their joins went
unexplained). Same protocol, same preparation, same single declared answer: runs `B-3` then `A-4`
(`--runs B-3,A-4`) from a worktree at the commit named below.
regression version 2: 37e2324
