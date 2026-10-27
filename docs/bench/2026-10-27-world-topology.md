# World Model accuracy against reference topologies, 2026-10-27

The references are in `bench/topologies/` and were committed before scoring (da019cb). The scorer is `bench/topology.py`. Every map was taken with `unbidden map --no-model`, so endpoint→table links are the ones the local model inferred during the event.

- **opentelemetry-demo** (5c8d404), deployed with `make start-minimal` (25 containers).
  - The reference comes from the official architecture diagram.
  - It was written before Unbidden ran on the system, so the first row below is blind.
- **full-stack-fastapi-template** (fork, 104feb4), only backend and db running.
  - The reference was written after Unbidden had mapped this system during the event, so this row is not blind.

Scoring rules are fixed by the reference files:
- Only `calls` and `uses_database` links between services count as claims.
- `depends_on` is start order and is listed separately.
- Edges into the telemetry plane are listed but not scored, because the diagram leaves them out on purpose.

| Run | System | Services P / R | Datastores P / R | Service links P / R | Endpoint→table P / R | Running commit |
|---|---|---|---|---|---|---|
| **blind**, code as registered (619f4b2) | opentelemetry-demo | 1.0 / 0.8 (20 vs 25) | 1.0 / 0.5 (1 vs 2) | **1.0 / 0.032** (1 vs 31) | n/a | 5c8d404 inferred, **wrong** |
| not blind, 619f4b2 | full-stack-fastapi-template | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 0.25 (1 vs 4) | 0.962 / 0.658 (26 vs 38) | 104feb4 inferred, correct |
| after fixes (5e262c0), not blind | opentelemetry-demo | 1.0 / 1.0 (25 vs 25) | 1.0 / 1.0 (2 vs 2) | 0.838 / 1.0 (37 vs 31) | n/a | unknown: pulled from a registry, correct |
| after fixes (5e262c0), not blind | full-stack-fastapi-template | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 0.25 (1 vs 4) | 0.962 / 0.658 (26 vs 38) | 104feb4 inferred, correct |

**Pre-registered goals for opentelemetry-demo** (stated as goals, not as gates):
- Service recall ≥ 0.9: **missed blind** (0.8). Met after the fixes.
- Recall ≥ 0.6 for service→service and service→datastore links: **missed blind** (0.032). Met after the fixes.

## What the blind run exposed, and what changed

| Symptom (blind) | Cause | Fix (general, not specific to this repository) |
|---|---|---|
| 30 of 31 links missed | Compose `- KEY` list entries were read as empty strings. Their values come from `.env` | Bare keys take their value from the tracked `.env` |
| Every `X → flagd` link and the proxy's routes missed | Host and port are given in separate keys (`FLAGD_HOST=flagd`) | Treat a bare service name as an address when the key ends in `_HOST`, `_HOSTNAME` or `_SERVER`. **Post-hoc**: added after seeing the misses |
| 5 services missing | They are declared in `compose.observability.yaml`, which Unbidden does not read | Running containers of services that are not declared are added from Docker, and the gap is named |
| valkey not counted as a datastore | The image pattern did not list it | Added valkey |
| "No tables yet" | The tables live in `astronomy_db`, in schemas `catalog` and `accounting` | Every database and non-system schema is read. Ids are qualified outside `public` |
| Running commit 5c8d404 (inferred) | The images were pulled from `ghcr.io`, so HEAD was the wrong answer | Images with a registry digest are not credited to the checkout. The commit is now `unknown`, with the digest as the reason |

The 6 extra links after the fixes are real configuration addresses that the diagram omits: frontend→flagd, the proxy's `/loadgen` and `/telemetry` routes, and the collector scraping Postgres, Envoy and nginx. None of them has been seen in traffic. They count against precision, as the rules say.

**Still missed in full-stack-fastapi-template:**
- The proxy→backend and proxy→adminer routes. They are declared in Traefik labels, which are not read.
- adminer→db. It is declared only as `depends_on`; adminer connects when someone logs in.
- The `user` read done by the auth dependency, missed in 11 of 13 endpoint→table cases. The local model sees the handler, not its dependencies.

## Change over time (AC3), live on opentelemetry-demo

These were three consecutive maps from a fresh workspace.

1. **Baseline.**
2. **`docker compose stop recommendation`.** Five facts became `obsolete`: the container, its image, `runs`, `runs_image` and `deploys`. No new deploy was recorded.
3. **`docker compose start recommendation`.** The same five facts were revived. There was still one deploy.

That one deploy was not right on the first attempt. The first run recorded the stop as a new deploy and would have tagged probe rounds with the wrong deploy index. Both bugs are fixed and tested.
