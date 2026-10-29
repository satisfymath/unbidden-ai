# Stage 7: the transfer, frozen (written before the runs)

- **Product and harness:** commit filled in below at the freeze; run from `~/unbidden-ai-eval7` detached at it
  (`uv run python -m bench.ecosystem.conduit_eval ~/unbidden-ai-eval7 --out ~/unbidden-lab/eval7`).
- **Application:** Conduit at 029eb7781c60d5f563ee8990a0cbfb79b244538c, prepared as `stage7-transfer-prep.md` says.
- **Order and isolation:** B-1 (proactive, no goal), then A-1 and A-2 (the goal). Before each: the repository reset
  to the pinned commit (lab files kept), the same synthetic data re-seeded, a new token, a new workspace; after each,
  the whole workspace moved out. B never sees A's goal, findings or proposals.
- **Each run:** two cycles of `unbidden watch --once`. Models: Spark on the `code` route, profile local-first (content
  leaves only as the route policy allows), the local model as recorded fallback. Caps (the workspace's monthly cap):
  B US$1.20, each A US$0.40; the ledger is read before and after every run.
- **Measured, per run:** what was found (useful, false, abstentions), what was reproduced, what was decided and why,
  capabilities reused, built or blocked, experiments and their evidence level, changes proposed (none can be
  applied: no deploy, no PR), acceptance states, interventions (none planned), calls, models, fallbacks, latency,
  spend. Utility as `stage7-transfer.md` defines it; nothing else counts as value.
- **Rules:** no change to code or harness during the runs; every result kept, including blocks, false opportunities,
  abstentions and "no demonstrable improvement"; any fix after these runs is another version.
