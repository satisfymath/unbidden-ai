# Deploy-impact criteria calibration, 2026-10-27

Real probe rounds of full-stack-fastapi-template at 104feb4 (index deployed), 5 requests per round,
disjoint pairs of 15-round windows (warm-up of 2 dropped). A/A: consecutive halves of the same version.
Injection: the second window scaled. v1: absolute floor 10 ms. v2: floor = max(0.2 ms, 3 x MAD of the
baseline's round medians). Both: one-sided Mann-Whitney p < 0.01 and >= 20 % relative.

| Endpoint | Criteria | Median ms | Pairs | A/A claims | +20% | +30% | +50% |
|---|---|---|---|---|---|---|---|
| GET /api/v1/items/ | v1 | 1.70 | 5 | 0/5 | 0/5 | 0/5 | 0/5 |
| GET /api/v1/items/ | v2 | 1.70 | 5 | 0/5 | 3/5 | 5/5 | 5/5 |
| GET /api/v1/users/me | v1 | 0.98 | 5 | 0/5 | 0/5 | 0/5 | 0/5 |
| GET /api/v1/users/me | v2 | 0.98 | 5 | 0/5 | 3/5 | 5/5 | 5/5 |
| GET /api/v1/utils/health-check/ | v1 | 0.41 | 5 | 0/5 | 0/5 | 0/5 | 0/5 |
| GET /api/v1/utils/health-check/ | v2 | 0.41 | 5 | 0/5 | 0/5 | 0/5 | 3/5 |

Five pairs per endpoint is little evidence: v2 is adopted for deploys judged from now on and re-checked as
rounds accumulate. Verdicts already recorded under v1 are not re-judged.
