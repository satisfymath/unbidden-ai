# Service health under injected faults, opentelemetry-demo, 2026-10-27

Criteria **health-v1** were committed (0f8bbc7) before any fault was injected:
- **Window:** the last 5 minutes, compared with the 30 minutes before them.
- **Errors:** at least 8 requests, at least 3 errors, and a ratio of at least max(5 %, 3× the baseline).
- **Latency:** p95 at least max(2× the baseline, the baseline + 50 ms).
- **Pass:** the injected service must be the first suspect within 5 minutes.

The faults were toggled with the demo's own feature flags by a scenario script, declared as such. Unbidden was never
told which flag was on: its only inputs were the project's Prometheus and, in the second run, its Jaeger. The
scripts and their raw logs are kept with the session's evidence. `bench/health_report.py` builds this table.

```
control minutes: 13, with an anomaly open: 0
| Fault | Expected | First anomaly (min) | Listed (min) | Top-1 (min) | Pass | Other suspects |
|---|---|---|---|---|---|---|
| paymentFailure 100% | payment | 3 | 3 | 3 | yes | - |
| productCatalogFailure on | product-catalog | None | None | None | no | - |
| adFailure on | ad | 2 | 3 | None | no | checkout |
| productCatalogFailure targeting:on | product-catalog | 0 | 4 | 4 | yes | checkout, quote |
| cartFailure 100% | cart | 5 | None | None | no | checkout |
```

**What the rows mean**

- **Control.** 13 minutes with no fault (10 before the first run, 3 before the second): no anomaly was open.
- **The first `productCatalogFailure` row is invalid**, and that is the operator's error. The flag's targeting
  returns `off` on both branches, so setting `defaultVariant` changed nothing, and product-catalog served no error
  in the window. It was rerun with the targeting branch set to `on`, which fails one product.
- **`adFailure` was detected but did not pass.** ad was named as an origin at minute 3, but a latency alarm on
  checkout opened at minute 2 and ranked first. checkout does not call ad. Its p95 was taken over about 15
  requests per 5 minutes, where a p95 is noise; the traces of that anomaly show no failing request.
- **`productCatalogFailure` (rerun) passed.** Traces through checkout agree: 10 failure origins in product-catalog,
  5 in checkout. A false alarm on quote opened first. quote is a chronic service (10 % errors in its baseline) that
  crossed 3× that baseline, and its traces confirm the errors start in quote itself.
- **`cartFailure` (an extra trial, not pre-registered) did not pass.** The flag fails one operation, `EmptyCart`:
  24 errors in 20 minutes among thousands of `GetCart` and `AddItem` calls. That is under 1 % of the service, so
  cart was never degraded; only checkout was, at minute 5.

**What health-v2 should change**

These are candidates only. They are not applied to the results above, and they must be calibrated before adoption,
as impact v2 was (D-014):
- judge each operation (`span_name`), not only each service;
- require a much larger sample for p95 than for error counts;
- for chronic services, use a threshold from the baseline's own variation rather than a fixed multiple.

## Holdout faults (fixed in a67e6c4, before they were run)

Live under health-v1, with traces and proxy counters recorded for each anomaly:

```
control minutes: 10, with an anomaly open: 6
| Fault | Expected | First anomaly (min) | Listed (min) | Top-1 (min) | Pass | Other suspects |
|---|---|---|---|---|---|---|
| paymentUnreachable on | payment | None | None | None | no | - |
| recommendationCacheFailure on | recommendation | 5 | 5 | 5 | yes | - |
| imageSlowLoad 5sec | image-provider | 2 | None | None | no | frontend-proxy |
```

Replaying the same Prometheus history under both versions (`bench/health_calibration.py`):

| Criteria | Clean minutes with an alarm | paymentUnreachable | recommendationCacheFailure | imageSlowLoad |
|---|---|---|---|---|
| health-v1 | 6 / 10 (checkout, payment, quote) | missed | minute 6 | missed (frontend-proxy degraded) |
| health-v2-candidate | 4 / 10 (frontend, quote) | missed | minute 6 | missed (frontend-proxy, flagd degraded) |

**What failed, and why**

- **Control minute 0: a host-wide slowdown.** checkout's p95 went from 276 to 4,625 ms, and 7 more services slowed at
  the same moment, just after the local model (35 GB) had built the Forge reader. Unbidden named five independent
  "origins" (cart, email, payment, shipping, ad). The right answer was one common cause outside the service graph.
- **quote flaps.** Bursts of errors over a baseline that is sometimes 0 %.
- **`paymentUnreachable`.** payment never sees the calls, so its server spans stay clean. The failure exists only in
  checkout's client spans to payment (6.9 of 8 failed in 8 minutes). checkout serves fewer than 8 requests per
  5 minutes, so it is never judged either.
- **`imageSlowLoad`.** Envoy injects the delay in frontend-proxy itself, which is where it was found. The
  pre-registered expectation (image-provider) was probably wrong, but it stands: the trial is counted as failed.

**Decision.** The v2 candidate is not adopted: two fewer false minutes, the same detections, new noise. Neither
version is reliable outside the faults it was designed on: 1 of 3 holdout faults found, and 40 to 60 % of clean
minutes alarmed. Next, for a v3 to be calibrated the same way:
- recognize a common cause when several unrelated roots degrade together (check host and container resources);
- localize by failing client spans to a peer, not only by server spans;
- say "not enough traffic to judge" for a service instead of staying silent;
- treat a flapping chronic service by its variation.

## Second holdout (fixed in 12164a5 before it was run)

| Criteria | Clean minutes with an alarm | paymentFailure 50% | loadGeneratorFloodHomepage | emailMemoryLeak 1000x |
|---|---|---|---|---|
| health-v1 (live, then replayed) | 7 / 10 (quote) | minute 4 | missed | missed |
| health-v2-candidate | 8 / 10 (frontend, quote) | minute 4 | missed | missed |
| health-v3-candidate | 8 / 10 (frontend, quote) | minute 3 | missed | missed |

**Decision.** v3 is not adopted: one minute earlier on payment, the same 1 of 3, and more alarms. health-v1 stays.

**Why each fault was missed**
- **The flood.** The flood of the home page did not raise frontend's errors or p95 past any version's thresholds.
- **The memory leak.** The leak grows memory, and every version judges request spans only. Container memory is
  already read and not yet judged.

**The alarm metric needs splitting.** The clean-minute alarms are mostly quote, which fails in bursts on its own (its
traces put the origin in quote). "Clean minutes with an alarm" mixes false alarms with real, persistent problems
nobody injected. The next calibration has to count them apart:
- alarms whose origin traces confirm;
- alarms that nothing confirms.

## Third holdout (fixed in 23b691e before it was run): v4 against v1

| Criteria | Clean minutes with an alarm | adHighCpu | emailMemoryLeak 100x | cartFailure 25% |
|---|---|---|---|---|
| health-v1 | 1 / 10 (quote) | missed | missed | missed |
| health-v4-candidate | 1 / 10 (quote) | **minute 5** | missed (a slower leak) | missed (one operation, diluted) |

**Decision.** On data it had not seen, v4 found one fault more than v1 with no more alarms, as it did on the second
holdout (the leak, at minute 4). It becomes the live criterion, `health-v4`. The evidence is thin: one blind
detection. It stays under measurement.

**Still missed:**
- a slow leak, which does not grow 1.5× within 35 minutes;
- an error confined to one operation, which per-operation judging (v2) caught on designed faults but which brought
  noise on the holdouts.
