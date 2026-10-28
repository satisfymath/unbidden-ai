# Architecture

Unbidden is one Python process per repository (`unbidden watch`). It keeps its state in a SQLite file and
runs everything that touches the repository's code in throwaway Docker containers. It has no server, no web
UI and no shared database. This document covers how the parts fit and which guarantees hold by
construction. The reasons behind each choice are in [`DECISIONS.md`](DECISIONS.md).

## The loop

```
 observe ──► director ──► lab ──► publish ──► operate ──► observe live
   │            │          │         │           │              │
 scan, map   decide      measure   PR with    merge, deploy   probes, verdict per deploy,
 world model utility     offline   evidence   (mandate)       L5 outcome, rollback + hold
                                                                 │
                                                  research ◄─────┘ (investigate, read-only)
```

Each arrow is a job in an idempotent queue (`store/sqlite.py`). Jobs are claimed in a transaction and
handled in `daemon/cycle.py`. Live probes run on a thread of their own (`daemon/loop.py`), so long lab work
cannot leave a deploy unjudged.

## Packages

| Package | Responsibility |
|---|---|
| `contracts/` | Pydantic models shared by everything: findings, opportunities, experiments, proposals, mandate, events, jobs, LLM requests. `contracts` and `guardian` are pyright-strict |
| `store/` | SQLite in WAL mode. Events and audit are append-only, enforced by triggers. Also holds the job queue, key-value state and probe rounds tagged by deploy |
| `observe/` | `health.py` judges each service against its own baseline from the project's metrics and localizes a degradation along observed calls. `stack.py` detects languages, package managers and workspaces. `ci.py` turns GitHub Actions workflows into the test plan and the lint scope. `compose.py` reads services. `analyzers.py` and `scan.py` run the repository's own tools in the sandbox. `probe.py`, `impact.py` and `live.py` handle production |
| `world/` | A world model of the running system: static facts (models, routes, tables), runtime facts, inferred relations, and generic checks that find opportunities without naming the target. Each fact names its connector (`connectors.py`), when it was seen and the revision or deploy it describes; `reconcile.py` merges each map into the previous one; `scope.py` walks from an anomaly to the components and gaps behind it |
| `director/` | Picks the next action for each opportunity by expected utility (p_success × value − cost − risk) within the mandate. Declines what lies outside the CI's scope. After each scan it also decides whether to probe the repository's own package for crashes (once per commit), and records why |
| `lab/` | `FixLab` (fixes for findings), `PerfLab` (migration plus a model-written workload run inside the team's own test command), `RobustLab` (fixes for crashes). `evaluator.py` compares base and candidate. `perfstats.py` provides Mann-Whitney and CIs |
| `sandbox/` | `runner.py`: `--network none`, read-only root, all capabilities dropped, uid 1000, snapshot at `/work`. `provision.py` builds dependency images, including code generation such as Prisma. `sidecars.py` starts databases on an `--internal` network |
| `brain/` | `router.py` routes each request with `route_policy.py` and `tasks.py`, repairs malformed answers and falls back between tiers. Providers: Ollama, OpenAI-compatible (Meta Model API), mock. `hardware.py` chooses the local model for the machine. Prompts are versioned files in `prompts/` |
| `guardian/` | Pure Python and deny-by-default. `injection.py` fences what the system under observation wrote, scans it for attempts to instruct a model and checks that cited evidence was read. `policy.py` holds capabilities. `classify.py` labels content. `scanner.py` finds secrets. `egress.py` is the outbound gate and records every attempt. Also approvals, the kill switch and mandate loading. It imports nothing from `brain/` |
| `bridge/` | The privacy bridge. `rename.py` renames every word that is neither the language's nor a declared dependency's. `service.py` adds the local outsider review, the send, the reverse renaming and dry runs |
| `research/` | `investigate.py` is a read-only tool loop (git log, git diff, service errors, read file). `robustness.py` covers property tests written by a model and parsing their crashes |
| `forge/` | Capabilities Unbidden builds for itself: regex log adapters and stats readers (`stats.py`, for text metrics endpoints no connector reads). Each carries a card (purpose, typed IO, permissions it cannot widen, privacy, limits, tests, failures, how to disable it) and is judged by a versioned oracle with no model (held-out real lines plus metamorphic variants) before it can be used. A format a reader already exists for is not built |
| `publish/` | Branches, PR bodies with their evidence, and pinned merges through the GitHub API |
| `operate/` | Deploys and rollbacks using the team's declared steps, holds, and the deploy ledger (`ledger.py`): which commit each set of running containers holds, and how that is known |
| `cli.py` | Every human interaction. `--json` everywhere |
| `bench/` | Benchmarks, outside the product: `scale.py` runs full autonomous cycles on pinned repositories and records each from state and the spend ledger; `scale_report.py` turns the record into rates with intervals |

## Models

`Brain.complete(request)`:

1. **Label the content.** The request's label is its most restrictive message `source` (prompt, repo,
   runtime, database, synthetic), raised further by the text classifier (secrets, env files, emails, IPs, log
   lines). Repository code is `public_code` only when GitHub confirms the repository is public.
2. **Choose a route.** `decide_route(profile, task, label)` returns a tier, a fallback and the reasons. Light
   tasks stay local. Heavy tasks go to Spark first when their content may leave. Unknown purposes are light
   and local-only.
3. **Check at the gate.** Before a remote call, `_gate` re-checks the label (secret and production_data are
   never remote) and the egress gate scans the exact payload, then records it.
4. **Validate the answer.** Answers are validated: JSON against a schema, code as fenced `# file:` blocks when
   `expect_files` is set. A bad answer gets one repair attempt, then falls back to the other tier.
5. **Record the run.** Every `ModelRun` stores the route, the reason and the model that actually answered.
   Proposals credit that model.

**Spend.** Promotional credits are one balance for every workspace, so remote spend is kept in one ledger per machine
(`brain/spend.py`, `~/.unbidden/spend.db`), not per workspace. Before a remote call leaves, its worst cost (every
payload byte a token, plus all of `max_tokens`, at list price) is reserved in one transaction against the balance a
person read on the dashboard (`unbidden spend --verified-balance`), minus a reserve only a person releases. After the
call the reservation becomes the reported usage; a call that may have been billed without reporting usage keeps its
worst cost. Without a verified balance only a small allowance is spent. `-contributor` models, whose data-use terms
differ, are refused unless the config allows them. Each call carries the run that caused it (`UNBIDDEN_RUN`).

## Privacy bridge

The bridge is used for private code that needs a frontier model:

1. **Collect.** `private_names` collects every word in the affected files, then keeps out language keywords
   and builtins, the standard library, and names from packages declared in a manifest.
2. **Rename locally.** Glimmer suggests neutral names, and code applies them deterministically. Unsafe
   suggestions are rejected.
3. **Review locally.** Glimmer reads the renamed text as an outsider would, and flags words that still reveal
   the owner. Those are renamed too, for up to two rounds. If the review cannot run, nothing is sent.
4. **Check at the gate.** The egress gate checks the payload against the private names.
5. **Measure.** The answer is renamed back and measured offline like any other candidate.

A model is never the control. Code decides what leaves.

## Production

Production work only happens with a mandate that declares `operations` (deploy steps, probe auth, sample
sizes) and an autonomy mode that allows it.

- **Probes.** Each deploy gets its own window of probe rounds. A version deployed again (after a rollback)
  starts from zero.
- **Verdicts.** Each deploy is judged once against the last well-measured deploy. Criteria v2 set the
  effect floor at max(0.2 ms, 3 MADs of the baseline). A 5xx threshold applies, 429 is not counted as
  latency, and without enough samples the result is INSUFFICIENT_EVIDENCE rather than HEALTHY.
- **Deploys.** A deploy is a new set of application containers. Its commit is `observed` (image revision label),
  `verified` (Unbidden's own deploy steps built those images from that commit; a cached build is the same
  build), `inferred` (the checkout's HEAD when first seen, said as such) or `unknown`.
- **Outcomes.** A merged proposal gets its outcome on the first deploy that carries its merge commit: positive,
  negative, inconclusive or invalid, with structured confounders and the version of the criteria applied. Only a
  positive outcome between two deploys whose commits are verified or observed is level 5.
- **Bad deploys.** A degraded deploy or an outage leads to a hold, a read-only investigation job, and, when
  the mandate allows rollback, a deploy of the last healthy version.

## Guarantees and limits

Guaranteed by code, and covered by tests:

- **Secrets and production data.** In all three profiles, secrets and production data are never sent to a
  remote model: the policy for every profile and label (`tests/unit/test_route_policy.py`), the router with a
  secret in the prompt and with production data under `frontier` (`tests/unit/test_router.py`). A planted
  secret never reaches stored state either (`tests/e2e/test_secret_plant.py`).
- **Private code.** Private code leaves only renamed, unless a person sets `private_code_to_frontier: allow`.
- **Merges.** Nothing is merged below L4, while the previous deploy is still being judged, or before the pull
  request's own CI passed on the measured commit; nothing is proposed that the team's suite did not validate; an
  autonomous deploy ships only a merged L4 proposal (`tests/unit/test_publish.py`, `tests/unit/test_director.py`).
- **Holds and the kill switch.** Holds are released only by a person. The kill switch stops new jobs and model
  calls; a running job's sandbox containers are killed (they carry its label) and its code stops at the next
  checkpoint; pushes, pull requests, merges, deploys, rollbacks and the remote visual judge check it immediately
  before acting. A job stopped by a timeout or the switch is retried only once its threads have ended
  (`tests/unit/test_daemon_limits.py`). Not reached: a thread inside a single blocking call, until that call returns.
- **Provisioning.** Every dependency image is built only when the mandate allows the language's registries:
  `provision()` takes the policy, so no path can skip it. The build's own network is not yet restricted (PR7b).
- **Model-written patterns.** Log and stats readers Forge built run on RE2, in time linear in their input, and
  Unbidden uses one on its own only when a person approved it or the mandate allows `use_new_capabilities`
  (`tests/unit/test_forge.py`, `tests/unit/test_forge_stats.py`).
- **Sandbox.** Sandboxed code has no network. Sidecar databases sit on an internal network.
- **Level 5 needs known code.** No level 5 between deploys whose commit was inferred or unknown
  (`tests/unit/test_live.py`).
- **Metrics and traces.** The project's own Prometheus and Jaeger are read with fixed queries only; only this
  project's services and containers are taken in, and span attributes are dropped on parsing
  (`tests/unit/test_health.py`).
- **Spend.** No remote call leaves without a reservation that fits the verified budget, across every workspace on the
  machine; refused calls send nothing; the reserve is not spent unless a person releases it; contributor models are
  refused by default (`tests/unit/test_spend.py`). The costs are list price times reported tokens: an estimate, the
  provider's dashboard is the bill.
- **Credentials.** Unbidden's secrets are held by a broker (`guardian/credentials.py`), not the process environment.
  Each one is given only for the purposes granted, every use is audited without its value, and the egress gate
  refuses any payload that contains a held value (`tests/unit/test_credentials.py`). It is not a vault: the values
  are in the process's memory.
- **Untrusted text.** Tool output reaches the investigator fenced; text that tries to instruct a model is recorded,
  and evidence found only in it lowers the hypothesis to the floor (`tests/unit/test_injection.py`).
- **Docker scope.** Only containers of the workspace's compose project are read, checked on each container's
  label as well as by the listing (`tests/unit/test_ledger.py`).
- **Knowledge ages, it is not erased or kept fresh by default.** A fact its source no longer sees becomes
  obsolete; a fact whose source could not run keeps its original time (`tests/unit/test_world_reconcile.py`).

Not guaranteed:

- **The bridge.** The bridge removes identifiers and revealing words, but the structure of the code still
  leaves. Use `local` for code whose shape is itself secret.
- **Production impact.** Production impact is measured from Unbidden's own probes, not user traffic, and is
  reported with its confounders.
- **Log history.** `docker compose logs` covers only the current container, so errors from a container that a
  rollback replaced cannot be read afterwards.
- **Remote provider.** While free credits are in use, the remote provider may use what it receives for
  product improvement. That is one more reason only labeled-safe content leaves.
