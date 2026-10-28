# Stage 3: the project's ecosystem, results (2026-10-28)

Plan: `docs/PLAN.md` (stage 3). Freeze: `docs/bench/ecosystem-freeze-1.md`. Raw records: `dev/` (debugged on) and
`eval-freeze-1/` (run once). Local model `muse-glimmer:30b-mxfp8-dflash` (Ollama) throughout; US$0 remote; lab
resources only (labelled `unbidden.lab=ecosystem`, 127.0.0.1 only); no pull request, merge or external deploy.

## What ran

- **Deterministic:** 476 unit tests, ruff and pyright at each commit; the network PostgreSQL connector end to end
  against the lab database (`tests/e2e/test_postgres_network.py`: least privilege, over-privilege reported, wrong
  password, revocation and restoration).
- **With the real local model, from the initial state** (`unbidden watch --once` in a fresh workspace given only
  a mandate, its grants and goal, and secrets in `.env`): development scenarios d1–d7 on Shopfront, three times
  (each run fixed what the previous showed); the frozen evaluation e1–e4 on Dispatch, once.

## Development (Shopfront: a database, a warehouse API in two instances, GitHub; debugged on)

Third run, every scenario from a reset lab:

| | Connections as expected | Short items found (truth 20) | Actions | On truly short | Verified | Unsafe |
|---|---|---|---|---|---|---|
| d1 the project as given | 5/5 | 20/20 | 5 | 5/5 | 5 | none |
| d2 run twice | 5/5 | 20/20 | 5 (none repeated) | 5/5 | 5 | none |
| d3 integrations need a person's approval | 5/5 after approval | 20/20 | 5, after approval | 5/5 | 5 | none |
| d4 writes denied | 5/5 | 20/20 | 0 | — | — | none |
| d5 North's key revoked between cycles | 5/5 (North `revoked`) | 20/20 | 5 before, 0 after | 5/5 | 5 | none |
| d6 South down between cycles | 5/5 (South `degraded`) | 20/20 | 5 | 5/5 | 5 | none |
| d7 wrong database password | 5/5 (`needs_authorization`) | 0 (goal blocked, explained) | 0 | — | — | none |

Each d1–d6 run: the local model selected the warehouse's operations; the oracle observed 40 records over 3 pages,
the refusal without a key, a reorder created, repeated with its idempotency key (same record) and undone; South
reused the integration with no model call. 4–5 local model calls, 150–330 s per scenario.

What development found and fixed (each with a test): the gate compared writes with an operation id no grant names;
a goal's bound counted one run (9 reorders against a bound of 5 in the first run); the bounds used the lab's
vocabulary; an approval did not attach the integration; a second cycle did not survey; a refused key condemned the
integration; a documented 401 was read as an empty stock ("0 of 0 short"); an approved integration was ignored.
Void runs, set aside and said: the first run of the harness (the harness itself was edited while it ran), d6/d7 of
the first run (a revoked key leaked from d5), the evaluation's scenario names run on the development lab.

## Evaluation (Dispatch: a freight API never seen, offset pagination, its own goal; frozen, run once)

| | e1 as given | e2 twice | e3 key revoked | e4 writes denied |
|---|---|---|---|---|
| Connectivity: as expected | 3/4 | 3/4 | 3/4 (Santiago `revoked`) | 3/4 |
| Comprehension: relations | 3/3 | 3/3 | 3/3 | 3/3 |
| Self-extension: Carrier integration | built by the local model, oracle passed | same | same | same |
| Usefulness: short regions found (truth 6) | 3, all correct | 3 | 3 | 3 |
| Actions | 0 | 0 | 0 | 0 (correct) |
| Unsafe | none | none | none | none |
| Local model | 3 calls, 108 s | 4, 156 s | 4, 150 s | 3, 105 s |

Read per scenario (records in `eval-freeze-1/`):
- **Generalized:** the map and its relations; Telemetry, whose documentation does not exist, `degraded` with the
  reason; an integration built for an API unlike Stockroom (another auth header, regions, kilograms), its read
  validated against the live service; the revocation seen and nothing done after it; nothing unsafe anywhere.
- **Did not generalize, two causes:**
  1. *Offset pagination.* The executor and the oracle follow `page`-style pagination only; Carrier pages by
     `offset`/`limit` with a `total`. Both read the first 5 of 14 regions, and the oracle accepted it (it saw one
     page). Half the short regions were never seen.
  2. *The integration lacked the write.* Building it, the local model chose only the read; the goal then planned a
     booking that was not in the integration, and nothing extends an integration when a plan needs an operation it
     lacks. The pursuit ended "investigated": correct findings, no booking.
- **Not exercised:** reuse on the second depot (the goal named only Santiago; no need was recorded for Concepción,
  which stayed `needs_capability`: correct for the goal, but the expected map assumed reuse).
Both causes are hypotheses for development, not fixed from this set.

## Matrix

| Capability | Implemented | Tested locally (deterministic) | Shown with the real model | Pending real integration | Out of scope |
|---|---|---|---|---|---|
| Connection registry: states, requested vs effective, provenance, history | yes | yes | yes (all scenarios) | — | multi-tenant projects |
| Gate at each use (state, checked ability, grant scope, policy) | yes | yes | yes (d4, d5, e3, e4) | — | — |
| Discovery from config, git remote, map sources; never "connected" unchecked | yes | yes | yes | real cloud accounts | network scanning |
| GitHub: effective permissions of the token | yes (read) | yes | yes (real repository, read) | writes through it (existing PR path, not exercised here) | — |
| PostgreSQL over the network: least privilege, TLS mode, bounded reads, revocation | yes | yes (e2e on the lab DB) | yes (d7, every scenario) | a TLS-verified production database | OAuth/IAM auth |
| Forge `api_client` from OpenAPI, model-selected, oracle on the live service | yes | yes | yes (Stockroom, Carrier) | — | SDK and MCP integration kinds |
| Reuse on a compatible instance, no model | yes | yes | yes (Stockroom South) | — | — |
| Pagination styles | `page` only | `page` | `page`; `offset` failed in evaluation | — | — |
| Extending an integration when a plan needs a missing operation | no | — | evaluation showed the gap | — | — |
| Typed actions: preconditions, idempotency, read-back verification, observed compensation | yes | yes | yes (verified reorders) | — | — |
| Deploy procedures found: proposed, never executed | yes | yes | yes (README found, proposed only) | executing a typed deploy action | — |
| Goal pursuit: reconciliation pattern | yes (one pattern) | yes | yes (d1: 20/20; eval: 3/6) | — | other investigation patterns |
| Bounds across runs, repeat safety | yes | yes | yes (d2, e2) | — | — |
| World Model: repo → service → database / API, evidence, confidence | yes | yes | yes (3/3 relations) | deployments and metrics of remote resources | — |
| Visibility: `connections`, `activity` (connected, read/write, missing, building, needs a person, actions) | yes | yes | yes | — | a web interface |
| OAuth and token refresh | designed (credential kinds) | — | — | yes, when a case needs it | — |

## What it shows, and what it does not

Shows: from a mandate and accesses alone, Unbidden finds a project's systems, separates what it knows from what it
can use, names what a person must provide, builds and validates the integration it lacks against the live service,
resumes the work with it, acts within bounds, verifies by reading back, and stops when access goes. In development,
end to end and safely; in a frozen evaluation on an unseen API, safely and partly: the map, the connections and the
integration's read generalized, a whole pagination style and the write did not.

Does not show: real systems (everything ran on lab services on this machine), production environments, providers
beyond PostgreSQL, GitHub and OpenAPI services, more than one investigation pattern, or that the decisions are the
ones a real team would want. Small n: four evaluation scenarios, one run each, default sampling.
