# mealie L5 on SQLite: result (2026-10-28)

Protocol `2026-10-28-mealie-l5-protocol.md`, amendment 1 (`…-amendment-1.md`, committed d4aed41 before the run).
Raw records in `docs/bench/mealie-l5/`. Unbidden's code: d4aed41 for the run (frozen worktree); 9308f45 for the
outcome attachment (it changes only `bench/`).

## What ran, in order

1. **Isolation checked.** Resolved compose config (`compose-config.yml`): project `mealie-sqlite`, container
   `mealie-sqlite`, image `mealie-sqlite:l5`, port 9092, volume `mealie-sqlite_mealie-data`, network
   `mealie-sqlite_default`. D-036's container, volumes, image and network listed before and after: unchanged.
2. **D-035 imported as history** (`opp_8f2cf46bd8864983`, `exp_ec2d1c4e89a94210`, `prop_805ba2b63dc44029`, original
   ids): recorded L4, granted today **L3** (`infra_failure`: its suite never ran on either side).
3. **Lab revalidation** (`revalidation.json`, new experiment `exp_aabdd6f98cc24811`), D-035's saved workload
   (SHA-256 matches), today's lab and evaluator, SQLite:
   - the CI test job ran in 3/3 rounds per side, 3,640 tests collected each round; the same 18 tests fail in every
     round on both sides (NLTK refuses a download directory under the sandbox's world-writable `/tmp`: the sandbox,
     not mealie) → `pre_existing`, which validates;
   - `GET /api/foods/empty` with 200,000 synthetic items: median 10,934 ms → 8.1 ms, p = 3.4e-8;
   - **L4 under today's rules**; this verdict replaced D-035's on the opportunity (D-035's kept in `past_verdicts`).
4. **Baseline deploy** of e31c5fc through `unbidden deploy` (ledger: `verified`, built by Unbidden's steps, image
   `sha256:5fb4b0e12b0f`, SQLite 3.46.1).
5. **Data** seeded once through mealie's API (`seed.json`): 5,000 items over 580 foods in 50 lists, 80 % checked,
   as asked; the same counts read inside the container after the candidate deploy.
6. **Baseline window**: 37 rounds, watcher stopped before the candidate's image build.
7. **Candidate deploy** of a351dc2 the same way (`verified`, image `sha256:4b875c9cb93a`, SQLite 3.46.1, the index
   present, rows unchanged). **Candidate window** until the watcher judged the deploy (19 rounds).

## Result

| `GET /api/foods/empty`, live, mealie on SQLite | Baseline (e31c5fc) | Candidate (a351dc2) |
|---|---|---|
| Median of round medians | 11.8 ms | 2.2 ms (−82 %) |
| p95 | 14.4 ms | 3.1 ms |
| Rounds used (after 2 warm-up rounds) | 30 | 17 |

Deploy verdict: `improved` (1 endpoint improved, 56 healthy, none worse), p = 3.2e-8 at judging time. Outcome class
**positive**, both deploys `verified` by Unbidden, lab evidence L4 → the opportunity is at **L5**.

## Deviations, disclosed

- **The outcome was attached after the verdict, not at it.** The imported record carried D-036's live outcome
  ("invalid"), and the watcher attaches an outcome only to an opportunity without one; the run's outcome was
  therefore not recorded when the deploy was judged. Fixed in 9308f45 (an imported outcome is kept as past). The
  outcome was then classified with the watcher's own code on the rounds in the store; by then deploy 1 had 19 rounds
  rather than the 17 present at judging, so its p-value is 8.8e-9 instead of 3.2e-8. Same criteria, same class.
- The 18 failing tests are the sandbox's, identical on both sides; they are not fixed or excluded.

## What it shows, and what it does not

- Shows: on SQLite, mealie's default engine, at a large household's data, the index Unbidden found and wrote makes
  `GET /api/foods/empty` about five times faster under the same requests, between two deploys whose code is known.
- Does not show: an effect on real users. The requests are **Unbidden's own probes** (5 per round, one user), not
  traffic. Nor anything on Postgres (D-036), nor at mealie's typical sizes (this is a large household), nor that the
  result holds over time (L6 needs the re-checks of PR14 over the persistence period; the container is stopped).
