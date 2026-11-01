# Remote spend, reconciled (2026-10-27)

Record: `2026-10-27-spend-reconcile.json`. Every `.unbidden/state.db` under the evidence archive, the benchmark
workdirs, mealie, opentelemetry-demo and the session scratchpads; runs deduplicated by id.

| | Calls | Tokens in / out | US$ (list price) |
|---|---|---|---|
| Before the ledger (2026-10-26 19:50 to 2026-10-27 23:05 UTC) | 32 | 102,909 / 133,629 | 0.6966 |
| Ledger, settled | 18 | | 0.2596 |
| Ledger, released (blocked by the egress gate, never sent) | 1 | | 0.0000 |
| **Total** | **50** | | **0.9561** |

The ledger's 18 settled calls are the 17 remote runs recorded by workspaces since it started (US$0.2591) plus the
end-to-end check made without a workspace (US$0.0005): nothing is missing on either side. An earlier audit counted 33
historical calls (US$0.7022) by summing state files without deduplicating; two copies of the fst state share one run.

Costs are list price times reported tokens; the provider's dashboard is the bill. No balance has been verified, so the
gate allows only the US$1 unverified allowance, of which US$0.26 is spent.
