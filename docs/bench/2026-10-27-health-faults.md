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
