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

## Results (development, not evidence about other applications)

Each version is the product commit the runs used; the next version fixes, in general, what the previous one showed.
Proposals are local branches (L4 under perf-v3); nothing was pushed. Spend from the ledger, `dev` envelope.

| Version | Conduit B / A | LNbits | What it showed, fixed in the next version |
|---|---|---|---|
| v1 13c5ee3 | 1 / 1 proposals; no base checks yet; goal failed (strict live check) | blocked (unknown-name totals, schema) | tolerant connection checks; base checks; recursive schemas; SQL-derived endpoint-table relations (c3afd5e, 9e704a5) |
| v2 9e704a5 | 1 / 1; base checks 90 passed; goal blocked: incomplete reads | its checks did not start (infra) | CI read through reusable workflows; missing reads added to an integration; a row-limited query is partial (30e63b9, 8374dca) |
| v3 8374dca | 1 / 1; goals inconclusive, never "none" on a partial read | checks ran: 272, 2 fail (need network) | a false "19000 keys short" from unread keys taken as zero; lab output classified as production data; forge builds that raise (87b85d8) |
| v4 87b85d8 | 1 / 1 (B: favorites; A: commentaries); B's cycle reached 91 min | same | a read outside the credential's scope blamed on the credential (6bef496); lab ownership test leaked networks (704e03e) |
| v5-v7 704e03e, cda7544, 388d4e3 | not run | v5, v6: waiting for capabilities; v7: a consistency question inconclusive, one blocked | integrations offer only operations the credential's kind reaches (cda7544); reads wait out rate limits; a count on the empty page past the end not compared (388d4e3) |
| v8 977835c (after the evaluation) | **2 / 2** proposals (commentaries and favorites article_id), base checks 90/90, goals inconclusive with their reason | inconclusive (8 keys, query hit its limit) and blocked (a documented-vs-observed deviation) | none needed for the demo |

Conduit's two L4s held in v8 and in the demo, and the independent check confirms both; `commentaries.article_id`
was revoked at 18% under B-7's workload in the revalidation (`stage9-revalidation.md`) and measured 25% under these
runs' workloads: the verdict depends on the workload a model writes, a limit stated in `RELEASE.md`. The false L4
(`commentaries.author_id`) never came back: it measured as unmeasurable or as no change. LNbits: the environment is
reproduced and its checks run at the base (272 collected, the 2 failures need network, said so); no opportunity it
can measure; its consistency questions end inconclusive or blocked, each with the reason, never "none". Spend:
Conduit US$0.28-0.67 per run, LNbits US$0.19-0.35; the whole `dev` envelope US$8.32 of US$12.
