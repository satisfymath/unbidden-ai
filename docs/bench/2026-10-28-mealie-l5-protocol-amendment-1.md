# mealie L5 on SQLite: amendment 1, fixed before the run (2026-10-28)

The protocol (`2026-10-28-mealie-l5-protocol.md`) stays as written; this file records what changes, why, and was
committed before any deploy, seed or probe of this run. Authorized by David on 2026-10-28. Nothing below was chosen
after seeing a result of this run.

## What was known before this amendment

- The protocol's deploy step cannot run as written. mealie's `docker/docker-compose.yml` fixes
  `container_name: mealie`, `image: mealie:dev` and port 9091; D-036's stopped container holds that name (project
  `mealie`) and its image that tag. Running it would fail on the name or retag D-036's image.
- D-035's L4 does not hold under today's test rules (D-040): its suite reported `<suite>` in every round on both
  sides. Diagnosed since, on the baseline commit, with today's lab: the CI runs `pytest -n auto`, which counted the
  host's CPUs, and the workers outgrew the sandbox's 2 GB (exit 137). With workers capped at the sandbox's CPUs
  (`09d0d14`, a general lab fix) the suite runs at e31c5fc: 3604 passed, 18 failed, 18 skipped. The 18 fail on NLTK
  refusing a download directory under the sandbox's world-writable `/tmp`: environment, not mealie. This is the only
  observation made, and it is of the baseline's test suite, not of the change.
- A new workspace holds no opportunity or proposal for a live outcome to attach to.

## Changes

1. **Isolation, by an override outside both commits.** `~/unbidden-l5/mealie-sqlite.override.yml` (not in mealie's
   repository; the code deployed is unchanged) sets `container_name: mealie-sqlite`, `image: mealie-sqlite:l5` and
   publishes port 9092 instead of 9091. The compose project `mealie-sqlite` namespaces the volume
   (`mealie-sqlite_mealie-data`) and the network (`mealie-sqlite_default`). Before the first deploy,
   `docker compose config` is recorded and checked for: no name, volume, network, image tag or port shared with
   project `mealie`. Deploy step: `docker compose -p mealie-sqlite -f docker/docker-compose.yml -f <override> up -d
   --build --wait mealie`. D-036's container, volumes, image and workspace are not touched (listed before and after).
2. **Lab evidence revalidated before any promotion.** Before the operational run, `bench/revalidate_perf.py`
   re-measures the change with D-035's saved workload (SHA-256 `be9753e3…`, checked) and today's lab and evaluator:
   the fixed driver on both sides, the CI test job 3 rounds per side, `classify_tests`, `judge`, `level_for`. A live
   positive outcome promotes to L5 only if this revalidation reaches L4. Otherwise the operational run is still
   recorded, with its limits, and nothing is promoted (enforced in code: `observe/live.py` does not promote a
   positive outcome on lab evidence below L4).
3. **History imported as history.** `bench/import_history.py` copies D-035's opportunity
   (`opp_8f2cf46bd8864983`), experiment (`exp_ec2d1c4e89a94210`) and proposal (`prop_805ba2b63dc44029`) with their
   original ids, marks the opportunity `details.imported` (source, D-035, recorded level), and sets its level to
   what today's rules grant on its recorded test data. If the revalidation reaches L4, its new experiment (own id,
   `provenance.revalidates = exp_ec2d1c4e89a94210`) becomes the opportunity's verdict.
4. **Equivalence of the two sides, recorded.** Same compose files and override, same host, no other benchmark
   running; SQLite as bundled in each image (version read from each container); the same seeded data (seeded once,
   after the baseline deploy, `bench/mealie_seed.py`, seed 20261028; row counts read before each window; the
   candidate's migration adds an index and changes no rows); the same probe set and `probe_every_s: 5`; the judge's
   first two rounds of each window dropped as warm-up (criteria v2). Commits and the image id of each deploy come from
   the deploy ledger.
5. **Probe credentials.** mealie's default first user on a fresh database (`changeme@example.com`), given to the
   watcher through the credential broker, as D-036 did with its probe user.

## Unchanged

Criteria v2, at least 15 samples per side, outcome classes (positive, negative, inconclusive, invalid), the
invalidity conditions, the seeded data's shape. No threshold is changed after seeing data. What the probes measure
is Unbidden's own requests, not user traffic, and is reported as such.
