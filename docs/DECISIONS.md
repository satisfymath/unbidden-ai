# Decisions

Append-only log of design decisions, with date and reason. Newest last.

## D-001 · 2026-10-26 · A CLI with a background agent, not a web app

Unbidden is installed like a developer tool and lives in the repository it improves: `unbidden init`, then
`unbidden watch`. Everything a person needs (the inbox, approvals, the reasons behind each decision and the
exact payload of every outbound call) is a CLI command with `--json` output. No web server, no browser.

## D-002 · 2026-10-26 · Meta models only; private context never leaves the machine

- `local` tier: Muse Glimmer 30B through Ollama (MLX). The only tier that sees real code, logs or names.
- `frontier` and `code` tiers: Meta's Model API. They receive only synthetic tasks that passed the egress
  gate: no secret and no identifier of the real environment. The gate records every attempt with its exact
  payload (or only its hash when blocked).
- Hosting partners (OpenAI-compatible) plug into the same provider by `base_url` if a fallback without a
  local GPU is needed.

## D-003 · 2026-10-26 · SQLite in one process instead of a database server

State is one SQLite file per workspace (`.unbidden/state.db`). One process owns it, so jobs are claimed in
a transaction; events and audit are append-only by trigger. Installing Unbidden needs no database server.

## D-004 · 2026-10-26 · Guardian is pure Python and deny-by-default

Unknown capabilities are denied; each capability that may use the network is limited to its own allowlist
(package registries, the remote model API, GitHub). The guardian package imports nothing from the model
layer, so no model can be its own safety control.

## D-005 · 2026-10-26 · Code is exchanged as fenced `# file:` blocks, never inside JSON

Decisions come back as JSON validated against a schema; code comes back as fenced blocks headed by
`# file: <path>`, parsed with path checks and normalized to exactly one trailing newline.

## D-006 · 2026-10-26 · What the Meta Model API offers our key, measured

`GET /v1/models` lists `muse-spark-1.3`, `-1.2`, `-1.1` (and `-contributor` variants), `muse-wonder-1.0`,
`muse-image-1.0`, `muse-voice-transcribe-1.0` and `sam-3.1`. There is no Muse Code model, so the `code` tier
routes to Spark until a benchmark shows a better choice. The API accepts only `tool_choice: "auto"`; a
required tool call is stated as an instruction and still enforced by the router. While free credits are in
use the provider may use content for product improvement, which is one more reason only synthetic tasks
are sent.

## D-007 · 2026-10-26 · Routing chosen by the first benchmark

Measured in `docs/bench/2026-10-26-models.md` (5 runs per task):

- `local`: `muse-glimmer:30b-mlx`, `think=low` (25/25; with thinking off the privacy rewrite leaked real
  names 5/5, so thinking stays on for every local call).
- `frontier` and `code`: `muse-spark-1.3` (20/20, 2.3 s median).

## D-008 · 2026-10-26 · The privacy bridge renames with code, not with the model

When the local model cannot prove a fix, FixLab asks Muse Spark through the bridge:

1. Code extracts every private name of the affected files: definitions, imports (module and imported
   symbols), path parts and the repository name.
2. Glimmer, locally, suggests neutral names and a one-sentence description of the problem.
3. Code applies the renaming deterministically and rejects unsafe suggestions (a name already in the code,
   a private name, a duplicate), inventing neutral ones instead.
4. The egress gate judges the exact payload against the private names before it is sent.
5. Code reverses the names in the answer; FixLab measures the result offline like any other candidate.

A model is never the control: if Glimmer leaks a name (it did 5/5 with thinking off), the rename or the gate
catches it. A test caught that imported symbols were missing from the private names; they are included now.
Known limit: words in comments or string literals that are not identifiers are not renamed.

First real run (`ledger` sample repository, pyright `reportArgumentType`): 7 private names replaced,
1,276 bytes sent to `api.meta.ai`, the returned fix measured at L4 (3 test rounds per side), 52 s end to end.

## D-009 · 2026-10-27 · Tests and measurements run the way the repository's CI runs them

A repository's checks are judged in its own terms: the test job of its GitHub Actions workflow becomes the
plan (its scripts and working directories, minus installs, Docker and reports), the compose services the job
starts come up as throwaway containers on an internal network, and the app service's environment applies.
Performance measurements run as one more test inside that same command, selected with `PYTEST_ADDOPTS -k`,
so they inherit the team's fixtures and environment. Running pytest bare from the root missed both the
working directory and a variable set inside the team's test script.

## D-010 · 2026-10-27 · Generic World Model checks find opportunities; nothing names the target

The first check reads only observed and inferred facts: a foreign-key column that leads no index, on a table
an endpoint reads. On full-stack-fastapi-template it found `item.owner_id`, read by five endpoints; nothing
upstream reported it. PerfLab measured the local model's migration (index on owner_id, created_at):
`GET /api/v1/items/` median 13.0 → 4.1 ms (69 % faster), one-sided Mann-Whitney p = 3.4e-08, 95 % CI of the
median difference [8.7, 9.2] ms, CI tests green 3 rounds per side: L4. 200,000 synthetic rows over 2,000 owners.

## D-011 · 2026-10-27 · The 8-bit Glimmer for long local tasks (to confirm by benchmark)

With `muse-glimmer:30b-mlx` (nvfp4) the workload failed six attempts out of six across two runs (invalid SQL,
an unquoted reserved word); with `muse-glimmer:30b-mxfp8-dflash` (35 GB) it ran on the first attempt. One
observation, not yet a measurement: the benchmark decides the default.

## D-012 · 2026-10-27 · Three autonomy modes, and rollback only when it is proven

David asked that Unbidden act when something big fails and nobody is watching. The master document allows
"advanced autopilot" for specific, low-impact production operations "covered by explicit policies, audit,
exposure limits and **tested rollback**" (§7.1). The earlier prototype had decided the opposite (holds only a
person releases, no automatic recovery). This changes that, under conditions:

- `unbidden mode supervised | autopilot | autonomous`, switched by a person, audited. Merging and deploying
  exist only in `autonomous`.
- `autonomous` refuses to switch on unless the mandate declares the team's deploy steps and a rollback drill
  (deploy the previous version, health green, deploy back) has passed and is recorded.
- Automatic rollback has two triggers only: a deploy by Unbidden judged DEGRADED, or an outage (health down or
  5xx over threshold) after any deploy. It returns to the last version with a HEALTHY verdict and sets a hold
  that only a person releases. Fixes still go through the lab; nothing is "fixed forward" unmeasured.
- Merges: L4 only, pinned to the measured commit, at most `max_merges_per_hour`, never while the previous deploy
  is still being judged.

Carried over from the prototype's impact guard as design, re-measured here: percentiles on pooled individual
latencies; windows of exactly the previous and the new build with warm-up dropped; INSUFFICIENT_EVIDENCE, never
HEALTHY, without enough samples; effect ≥ 20 % and ≥ 10 ms; 5xx over 1 % with ≥ 100 requests and ≥ 3 errors;
HTTP 429 is throttling, not latency.

## D-013 · 2026-10-27 · The first autonomous run, what it got right and what it exposed

On full-stack-fastapi-template (fork), in `autonomous` mode after a passed rollback drill, with nobody
intervening:

- It withdrew two lint proposals outside what the team's CI checks, published the index PR
  (satisfymath/full-stack-fastapi-template#1), merged it pinned to the measured commit and deployed it with the
  team's steps; production then had `ix_item_owner_created` and Alembic at the model's revision.
- It found two lint findings its own migration had introduced in `models.py`, fixed one to L4 and merged it
  (#2); #3 went stale when the base moved.

Exposed, and fixed:

1. PerfLab did not run the repository's checks on its candidate; now it does, both sides, and feeds new
   findings back to the model.
2. #2 was merged five minutes after #1 while probes were starved by queued lab work: #1's deploy got four
   rounds and no verdict. Probes now run on their own thread; a merge waits for the last deploy's verdict;
   a deploy too short to judge is skipped as a baseline and named as a confounder.
3. An endpoint the probe user may not read (403) kept every verdict waiting; a scripted edit claiming to fix
   it had silently not applied. Fixed and covered by a test.

## D-014 · 2026-10-27 · No level 5 for the index: the pre-registered floor said "no change claimed"

The deploy carrying the index was judged against the last well-measured version (f4bcfab):
`GET /api/v1/items/` median 10.5 → 1.7 ms. Under criteria v1 (an absolute floor of 10 ms, inherited from a
system whose endpoints sat near 60 ms) a difference of 8.8 ms is not claimed, so the verdict is HEALTHY and
the opportunity stays at L4. That verdict stands: criteria are not changed after seeing their data.

Criteria v2 replace the fixed floor with the baseline's own noise (max(0.2 ms, 3 MADs of round medians)),
calibrated before adoption on rounds not used to choose them (`docs/bench/2026-10-27-impact-calibration.md`:
A/A 0/15 claims, +30 % caught on 10/15, +50 % on 13/15). v2 applies to deploys judged from now on.

## D-015 · 2026-10-27 · The outage drill, and why deploy windows are per deploy, not per version

A scenario script (declared as such) deployed a release whose health check fails. In `autonomous` mode Unbidden
judged it an outage 11 s after first seeing it, rolled back to the last healthy deploy (104feb4) in 15 s with
the team's own steps, and set a hold only a person releases; health returned to 200.

Exposed, and fixed:

1. After the rollback, the redeploy of 104feb4 was judged "improved" against f4bcfab using every round ever
   taken of that version, including those that had motivated criteria v2. That verdict is invalid and is not
   used for any claim. Probe rounds now carry the deploy they belong to: a version deployed again starts a
   window of its own, and an outage deploy is never a baseline.
2. Level 5 could never have been recorded: proposals are squash-merged, so the branch commit is never an
   ancestor of what is deployed, and the check also passed a deploy id where a commit was needed. Proposals
   now keep the merge commit GitHub returns; a proposal gets its outcome only on the first deploy carrying it.
3. Forge's first adapter listed the statuses it had seen (200|403|404) and passed an oracle with no 500 in the
   held-out lines. The oracle now runs metamorphic checks (statuses and methods not in the sample), adapters
   carry the oracle version that judged them, and only those judged by the current one are usable.

## D-016 · 2026-10-27 · Forge escalates through the bridge; the investigator explains the outage

- **Forge, first real build** (backend logs of full-stack-fastapi-template, uvicorn access format). The local
  model failed five attempts (patterns that did not compile or did not match its own tests). Escalated through
  the privacy bridge: 7 path segments renamed and addresses replaced; the first escalation was blocked by the
  egress gate because the tests in the prompt quoted real paths (fixed: renaming now covers the whole text).
  Muse Spark returned `"(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/[\d.]+" (?P<status>\d{3})`, judged locally by
  oracle v2: 1,029 / 1,029 unseen real lines, every metamorphic variant read, 1.7 µs per line. An earlier
  local adapter (`status` limited to 200|403|404) had passed oracle v1 and is no longer usable.
- **Investigation of the outage drill**, read-only, local model, four tool calls (git log, git diff, service
  errors, read file): "the health-check endpoint was changed in release 1.6 to raise RuntimeError
  unconditionally". Correct, citing the commit and line, and not misled by the exception's text about a
  database pool. Claimed confidence 0.95, capped at 0.60 because nothing was reproduced (L1).
- Blind spot recorded: `docker compose logs` returns the current container's lines, so errors of a container
  replaced by a rollback are not readable afterwards.

## D-017 · 2026-10-27 · Model routing by profile, from what each message holds

Routing used to be a fixed tier per call: the local model did nearly everything and Muse Spark only came in through
the bridge after local failures (five failed local attempts before Forge escalated; minutes per robustness round).
Protection depended on where a module called from, not on what it sent.

- Every `Message` declares its `source` (prompt, repo, runtime, database, synthetic). Undeclared means private code.
- A deterministic classifier labels the request with its most restricted part: instructions < synthetic <
  public_code < private_code < production_data < secret. Text patterns (secrets, environment files, emails,
  non-documentation IPs, log lines) can only make it stricter. Repository code is public only when GitHub confirms
  it (`private: false`); anything else, including an unreachable API, is private.
- Profiles in the mandate: `local`, `local-first` (default) and `frontier`, plus `private_code_to_frontier`
  (deny by default). Secrets and production data stay local in every profile; private code leaves only renamed by
  the bridge unless a person allows it in `frontier`.
- Tasks declare a weight. Heavy work (fixes, migrations, workloads, property tests, adapters) goes to the frontier
  model first when its content may leave, with the local model as fallback; light work starts local. Unknown
  purposes are light and never leave.
- The egress gate re-checks the label: secret and production_data are refused there too, whatever was decided.
  Code answers now have a contract (`expect_files`), so a frontier answer without file blocks is repaired or falls
  back to local instead of being accepted.
- `unbidden models`, `unbidden route` (dry explanation per task) and `unbidden egress --payload`.

## D-018 · 2026-10-27 · Routing measured on real repositories, and Rich searched blind

Routing (D-017), checked with `unbidden route` on three real workspaces:
- a private repository of the author's (private confirmed by GitHub's 404 without a token): private code stays local or leaves only renamed
  through the bridge in every profile; logs and data never leave; `frontier` without `private_code_to_frontier`
  behaves like `local-first` for private content. A run sending content derived from it (even renamed) was
  refused by the session's permission layer pending David's explicit consent, which is the right default.
- full-stack-fastapi-template and Rich (public, confirmed): heavy work goes to Muse Spark first, local fallback.

Rich, never told about its open issues (#4238, #4239, #4242):
- With Spark writing the property tests (public code), a full probe took 17 s instead of minutes locally.
- Two refinement rounds turned an over-strict round-trip property on `markup.escape` (failing first on control
  characters, which rendering drops by design) into a narrower one that still fails: `render(escape("\\")).plain`
  is `"\\\\"`. Kept as L1, for a person: it may be a broken promise or an acceptable edge.
- Two crashes in the public `rich.cells.split_text`: `IndexError` at `cells.py:266` (input `"0\x1f"`, position 2)
  and `ZeroDivisionError` at `cells.py:256` (input `"\x1f"`, position 1), on zero-width text. The first is the
  same line as issue #4239 with a different, simpler trigger; the second appears in no issue. They were first
  missed because Hypothesis grouped them in an ExceptionGroup; the parser reads those now.
- RobustLab, fix written by Spark (`if cell_position >= cell_length: return text, ""`): the property test fails
  at the base and passes with the fix, Rich's suite three rounds per side with no regression (one test,
  `test_console::test_brokenpipeerror`, fails on both sides): L4 in 58 s. The fix also resolves #4239's exact
  reproduction (IndexError at the base, no crash with the fix), checked in the sandbox.

## D-019 · 2026-10-27 · The bridge renames every word that is not the language's or a declared package's

An authorized audit on a private repository sent one real source file through the bridge: no secret left, but
an object property and a few string literals that come from the team's own API types were not renamed, and one
of them alone told an outsider which industry the product serves. (Details of that repository are not recorded
here: this log is public.)

- `private_names` now takes every word of the code (identifiers, properties, words in strings and comments,
  path parts) and keeps only the language's keywords and builtins and names imported from published packages.
  A package is published only if a manifest in the repository declares it (every package.json, pyproject.toml,
  requirements file in the tree) or it is the Python standard library or a Node builtin. An undeclared module is
  the team's own code, whatever its name looks like.
- Before anything leaves, the local model reviews the renamed text as an outsider would and lists words that
  still reveal the owner (domain, customers, people, places); those are renamed too, up to two rounds. The
  review is local-only in every profile; if it cannot run, nothing is sent.
- A dry run builds and reviews the payload without sending it. The second audit was a dry run (further sends of
  that repository's content were refused by the session's permission layer): about 1.5 times as many names
  renamed, two more domain words flagged and renamed by the review, none of the earlier revealing words left,
  and the published UI library kept with its real API.

## D-020 · 2026-10-27 · The local model is chosen for the machine it runs on

Users do not all have 64 GB. `routing.local.model: auto` (the default) resolves, when a workspace opens, to the
best Meta model that fits this machine among those installed in Ollama; `unbidden doctor` shows the choice and
`--fix` pulls it when missing. Apple silicon (MLX builds) keeps 30 % of unified memory, at most 10 GB, for
Docker, throwaway databases and the system; elsewhere the GPU's memory decides (GGUF builds).

| Memory for a model | Model | Note |
|---|---|---|
| ≥ 42 GB | Glimmer 30B 8-bit (`mxfp8` MLX, `q8_0` GGUF) | best local quality measured |
| ≥ 24 GB | Glimmer 30B 4-bit (`nvfp4` MLX, `q4_K_M` GGUF) | 25/25 on the task benchmark |
| ≥ 6.5 GB | Llama 3.1 8B | light local work; hints the `frontier` profile for heavy public work |
| ≥ 3 GB | Llama 3.2 3B | only what never leaves (renaming, reviewing) |

An installed model that fits is preferred over a better one that needs a download.

## D-021 · 2026-10-27 · JavaScript workspaces are analyzed package by package, as their CI does

A pnpm monorepo was analyzed from its root only, where nothing is type-checked: zero findings, and nothing
could be learned. Now:

- Workspace packages come from `pnpm-workspace.yaml` or `workspaces`; each runs its own checks in its own
  directory (`tsc:apps/web`, using the package's plain `tsc` typecheck script when it has one), with findings
  reported relative to the repository. The snapshot is always mounted at `/work`; a package's
  `node_modules` (relative links into the store and to sibling packages) is copied into it at container start,
  so workspace imports resolve against the real sources.
- Code generation a type check depends on runs while building the dependency image, from trusted tools only:
  Prisma's client from the tracked schema. Without it, one package reported 1,309 type errors (232 missing
  exports) and 121 false opportunities; with it, 0, and the complete report closed the 121 on its own.
- A tsc report dominated by missing modules or exports is marked failed for the environment instead of opening
  opportunities.
- ESLint's JSON is slimmed by a fixed filter (it repeats each file's source) so large packages fit the capture.
- The lint scope comes from the workflows' own commands (`pnpm --filter <package> lint`, root scripts they
  call): style findings in a package the CI does not lint are declined. On the monorepo above, 857 lint
  findings in an unlinted package would otherwise have become proposals.

## D-022 · 2026-10-27 · Runtime truth: what runs, how it is known, and what the map no longer sees

An audit against the master document found that the commit attributed to each deploy was assumed, not read. It was
the checkout's HEAD at the moment new containers appeared, and level 5 rested on that assumption. The World Model was
rebuilt from scratch at every map, with no history, no age and no obsolete facts.

- **Deploy ledger** (`operate/ledger.py`). Each set of application containers is a deploy. Its commit is:
  - `observed` when the images carry a revision label;
  - `verified` when Unbidden's own deploy steps built those images locally from that commit. A cached build counts:
    on full-stack-fastapi-template the running image predated Unbidden's rollback by 74 minutes, because compose
    reused it;
  - `inferred` when it is HEAD at the time the containers were first seen, and the record says so;
  - `unknown` otherwise. Images pulled from a registry are never credited to the checkout.

  Who started a deploy is read from container start times; containers started before the ledger watched are `unknown`.
- **Outcomes.** Results are positive, negative, inconclusive or invalid. Only a positive result between two deploys
  whose commits are verified or observed is level 5. Confounders are structured. Every verdict records the criteria
  version it applied: verdicts judged under v2 since D-014 still stored `min_delta_ms: 10`, and they are not rewritten.
- **Facts with provenance** (`world/connectors.py`, `world/reconcile.py`). Each fact records its connector, when it
  was seen, its environment and the revision or deploy it describes.
  - A fact that its source ran and no longer saw becomes obsolete.
  - A fact whose source did not run keeps its age.
  - Every map emits `world.changed` with its diff.
- **Scope of an anomaly** (`world/scope.py`). A degraded or outage verdict carries the components behind it, up to the
  deploy and image, together with what cannot be seen: no metrics, traces or logs connector, and links never seen in
  traffic.
- **Docker scope.** Only containers of the workspace's compose project are read, and each container's label is checked.
  This machine runs other projects.
- **Measured** against reference topologies committed before scoring (`docs/bench/2026-10-27-world-topology.md`).
  - opentelemetry-demo, blind: services 0.8, links recall **0.032**, running commit wrong (inferred HEAD for images
    pulled from a registry).
  - The causes were general: bare compose keys, Postgres databases and schemas, registry images. After the fixes, not
    blind: services 1.0, links P 0.84 / R 1.0, commit `unknown` with the digest. The `_HOST` key rule was added after
    seeing the misses.
  - full-stack-fastapi-template (not blind): links recall 0.25. Traefik label routes are not read.
- **Not done yet.**
  - A live `verified` binding. The only built-from-source system here is watched by a running autonomous watcher on the
    earlier code, and deploying under it was not done without a person.
  - Metrics, traces and logs connectors.
  - Traefik labels.
  - Several compose files.

## D-023 · 2026-10-27 · A verified deploy, live; three more compose facts; Traefik routes

- **The missing acceptance check of D-022, done.** The earlier autonomous watcher was stopped (with the prototype's
  collector and containers) so a deploy could be made under the new code. `unbidden drill` on
  full-stack-fastapi-template passed in 40 s. The deploy it left is **104feb4 `verified`, by unbidden**, and
  `deploys --commit 104feb4` finds it with its image.
- **Three bugs the drill exposed, fixed:**
  - Docker's containerd store gives local builds a digest (`backend@sha256:...`), which had been read as "pulled
    from a registry". Only a digest naming a registry host counts now.
  - Deploys run by a drill were credited to nobody.
  - Containers recreated on the same code kept weaker evidence about their deploy.

  A ledger record written before the fix (deploy 5, "pulled from a registry") is left as it was written.
- **The deployment's own compose files.** The running containers say which files they were started with; those are
  read from git and merged in order, as compose merges them. opentelemetry-demo's 5 observability services are now
  declared rather than only known from Docker.
- **Traefik router labels are routes from the proxy.** On full-stack-fastapi-template, link recall goes from 0.25 to
  0.75 (not blind). Reading the deployed `compose.override.yml` also brings in mailpit and playwright, which are
  declared but not running. The pre-registered reference does not list them, so service precision drops to 0.67,
  and that is how it is reported.

## D-024 · 2026-10-27 · Metrics and traces: anomalies found in a running system, and where they fail

opentelemetry-demo runs its own Prometheus and Jaeger. Unbidden now reads both, read-only, with fixed queries.

- **Calls seen in traffic.** The project's client call metrics give 11 observed calls, which expire after 15
  minutes. The frontend's gRPC calls carry no peer label, so they stay as configuration inferences: that is how much
  of the call graph the telemetry covers.
- **What the project's own metrics say.** Each service's requests, errors and p95, and each container's CPU and
  memory. The demo's Prometheus scrapes the whole host, other projects included; only this project's services and
  containers are taken in, and that is tested.
- **Two findings without injecting anything.**
  - quote fails about 20 % of its requests all the time. Its traces put the origin in quote.
  - load-generator calls a host `agent` that no service of the project provides.
- **`unbidden health`, also on the probe thread every 60 s.** Criteria health-v1 were committed before any fault was
  injected. A degraded service whose dependencies are healthy is named where the degradation starts. This is a
  hypothesis, recorded with the queries, the scope and a plan that says which next sources Unbidden can read.
  Traces through an affected service then agree or disagree.
- **Results** (`docs/bench/2026-10-27-health-faults.md`):
  - control: 0 anomalies in 13 minutes;
  - `paymentFailure` passed (3 min);
  - `productCatalogFailure` passed (4 min), with the traces agreeing; the first attempt is void because the operator
    activated the flag wrongly;
  - `adFailure` was detected but did not pass: a latency false alarm on a low-traffic service ranked first;
  - `cartFailure`, an extra trial, was missed: the failure of one operation is diluted in the service.

  These are three passes and two failures, all reported. health-v2 candidates (judge per operation, require larger
  samples for p95, use variation-based thresholds for chronic services) wait for a calibration.

## D-025 · 2026-10-27 · Forge builds a second kind of capability; untrusted text measured; the worker cannot hang

- **Forge, from need to use, on a real source.**
  1. **Need.** The map finds that frontend-proxy serves 1,870 lines of numbers at `/stats` (Envoy's format) that no
     connector reads, and names that need. Two other endpoints are in Prometheus text, a known format: nothing is
     built for them.
  2. **First attempts failed.** The local model failed eight times: answers cut off, then patterns that did not
     compile. The raw answer showed backslashes lost inside JSON, against D-005. Patterns now come back as raw
     lines, in the log Forge too; this is probably the cause of D-016's five local failures.
  3. **Built and judged.** After the fix the local model wrote the reader on its first attempt. The oracle, with no
     model, passed it on 1,770 unseen lines: 100 %, metamorphic checks, 8.4 µs per line, 63 histogram lines
     declared unread.
  4. **Contract.** The reader carries a card: purpose, typed input and output, permissions it cannot widen, privacy,
     limits, kept tests, failures, and how to disable it.
  5. **Reuse and use.** A new endpoint is first tried against existing readers with the oracle. During an anomaly,
     each proxy's upstream error counters are read twice.

  Reuse on a second project has not been run: there is no second system with Envoy here.
- **Local failures escalate through the bridge**, as logs do (D-016). The project's names are renamed, addresses
  replaced and values randomized. Not exercised live, because the local model succeeded.
- **Prompt injection, measured with the local model** (`bench/injection_eval.py`). A log line planted to blame DNS:
  - The easy scenario (the cause is visible in the diff): followed 0/5 raw and 0/5 fenced.
  - The hard scenario (the cause is not in the code): 0/5 and 0/5.

  The model resisted this kind of plant on its own, so fencing shows no measurable benefit and is kept only as
  defence in depth. The code control at first lowered all ten correct conclusions to the floor, which would have
  let anyone who can write a log line void Unbidden's investigations. Now only lines that try to steer are set
  apart, and confidence drops only when cited evidence rests on them alone.
- **Criterion.** `unbidden decide` reports what the Director would do with each open opportunity, and why, changing
  nothing. The benchmark records it per repository against the policy of acting on every finding.
- **Reliability.** A job past its limit is cancelled and retried with growing waits (2, 4, 8 minutes, at most 1 hour).
  A thread started with `to_thread` cannot be killed, but the worker no longer waits for it.

## D-026 · 2026-10-27 · The health detector fails its holdout; the v2 candidate is not adopted

Three faults were fixed before they were run: `paymentUnreachable`, `recommendationCacheFailure` and
`imageSlowLoad`. Under health-v1, live, only recommendation was found (minute 5), and 6 of the 10 clean control
minutes had an alarm open. Replaying the same history, the v2 candidate (judge per operation, binomial thresholds)
gives 4 of 10 alarmed minutes and the same single detection, with new noise. It is not adopted.

**Causes** (`docs/bench/2026-10-27-health-faults.md`):
- A host-wide slowdown, right after the 35 GB local model ran, was read as five independent origins.
- An unreachable service shows only in its callers' client spans.
- A caller with fewer than 8 requests per window is never judged.
- A chronic service flaps.

**Status.** The detector found 3 of 5 designed faults and 1 of 3 holdout faults. Calls seen in traffic, scope,
traces and proxy counters all work. What does not work yet is deciding when something is wrong. That is the next
increment's work, calibrated the same way before it is used.

## D-027 · 2026-10-27 · Level A on 12 repositories: what failed, what was fixed, and the blind holdout

The harness (`bench/repos.py`) ran Unbidden on 8 dev repositories and then once on 4 holdout repositories, chosen
and pinned before any run (`docs/bench/2026-10-27-level-a.md`). The first dev run gave a useful analysis on 2 of 8.

**Causes, all fixed in general rather than per repository:**
- A dependency build hid the installer's error. Docker's quiet mode is gone, and the cause is now kept.
- An install that needs a compiler retries with build tools only when the mandate allows Debian's archive.
- An install that would run repository code with network access (`.pnpmfile.cjs`) is declined, and says so.
- CI test jobs are found by what they run, not their name. Jobs needing a browser, a deployment or another OS come
  last, and canonical workflow files come first.
- Node analyzers get 6 GB of memory (lexical's tsc ran out of heap). Errors keep their message. A title longer than
  200 characters no longer crashes a scan. The capture cap is 16 MB.
- The Director declines style findings from a tool the team's CI does not run, and lets them wait while the CI is
  unreadable. With the new `github.read` (observe, GitHub hosts only), it also declines style findings of a tool the
  CI runs on a commit where the CI is green.

**Dev set after the fixes.** CI understood in 7 of 8 repositories. Analyzers ran usefully on 5 of 8: the two
before, plus lexical, docusaurus (7 of 40 packages) and chatwoot.

**Holdout, run once, nothing changed after it:**
- click: analyzed, CI understood.
- sqlmodel: analyzed, nothing found, nothing to do.
- httpx: installs itself from source; not analyzed.
- fastify: no lockfile; not analyzed.

**Criterion, measured.** Of 108 opportunity groups, 4 were declined, against 0 under the act-on-everything
policy. 82 of the 104 that would be acted on are chatwoot style findings, likely an environment difference, that
the per-commit CI status cannot rule out because that commit's CI is red. Next, CI status should be read per job.

## D-028 · 2026-10-27 · Autonomous in the test environments; screenshots allowed; a multimodal judge that earned its place

- **Autonomy.** David set Unbidden to run autonomous, with every capability, in its test environments: that is the
  product. full-stack-fastapi-template (the fork) runs `unbidden watch` autonomous. opentelemetry-demo runs
  autonomous for everything local (experiments, delegation, Forge capabilities), but GitHub publishing is denied
  there, because its repository is a third party's upstream.
- **Screenshots** of the project's own pages may go to a Meta multimodal model only where the mandate says
  `models.screenshots_to_frontier: allow`, through the `model.remote.screenshot` capability. The egress gate records
  each send with its size and digest, and the images stay in `.unbidden/artifacts/ui/`. Images cannot be scanned
  for secrets as text can, which is why this is an explicit per-workspace choice.
- **The UI lab.** Pages are captured in a pinned Playwright container. Two judges answer whether the page is healthy
  and what is wrong. On the pre-registered evaluation (`docs/bench/2026-10-27-ui-eval.md`) the visual judge
  (Muse Spark 1.3) beat the browser judge: detection 8/12 against 6/12, attribution 5/9 against 3/9. It saw blank
  images that the DOM reported as loaded, 3 of 3 times. By its own rule it is now in the critical path: an anomaly
  records both judges' view of the product's page.
- **L5.** In full-stack-fastapi-template, Unbidden finds no new improvement it can measure: the one it found (the
  index) is deployed, and its verdict stays at L4 under the criteria of its time (D-014). No new L5 is claimed; the
  autonomous watcher keeps looking. What is missing for an L5 in opentelemetry-demo is analysis of its languages
  (Go, .NET, Java, Rust) and deploy steps for a service built from source.

## D-029 · 2026-10-27 · The v3 candidate fails the second holdout too; health-v1 stays

On a second holdout fixed before it was run (`paymentFailure` 50 %, `loadGeneratorFloodHomepage`, `emailMemoryLeak`),
v1, v2 and v3 each found 1 of 3. v3 was one minute earlier on payment, with more alarms in the clean minutes (8 of
10 against 7 of 10). Neither candidate is adopted.

**What the evidence says to build next**, each to be calibrated the same way before use:
- judge container memory and CPU, which Unbidden already reads (the leak was invisible to request spans);
- separate real persistent failures (quote, confirmed by its traces) from unconfirmed alarms in the metric itself.

The detector has now failed two holdouts. It is reported as the weakest part of Unbidden, not hidden behind the
faults it was designed on.

## D-030 · 2026-10-27 · A credential broker, CI status per job, and polyglot services analyzed one by one

- **Credential broker** (`guardian/credentials.py`).
  - **Before:** `.unbidden/.env` was copied into `os.environ`, where code that builds prompts and every subprocess
    could read it.
  - **Now:** the broker holds Unbidden's secrets, and the declared ones found in the environment, and removes them
    from it. Each is given per purpose: the remote model's key for `model.remote`, the GitHub token for `github`,
    probe credentials for `probe`. Every hand-out and refusal is audited without its value, and the egress gate
    refuses a payload that contains a held credential's exact value. The git push gets the token in its own
    environment only.
  - **Limit:** not a vault; the values live in this process's memory.
  - **Also found:** full-stack-fastapi-template's workspace has never had a `GITHUB_TOKEN`, so its autonomous watcher
    could not publish a pull request even if it found an improvement.
- **CI status per job.** The Director reads the conclusion of the jobs that run a tool, not of the whole commit. On
  chatwoot the commit is red (other jobs failed) but its eslint job is green: the 82 style findings Unbidden's eslint
  reported are now declined as its environment's.
- **Polyglot services.** A compose service built from a directory with its own manifest and lockfile is extracted at
  the commit and scanned as a repository of its own, with the same trusted tools. Findings are recorded with
  prefixed paths and a tool named `tool@dir`. The lab cannot reproduce them inside the repository yet, so the
  Director leaves them waiting and says why.

## D-031 · 2026-10-27 · health-v4 adopted: container memory and CPU, after a blind holdout

v4 is v1 plus new container pressure:
- **memory:** 1.5× and +20 MiB over a baseline that was itself steady, or newly past 85 % of the limit, with
  hysteresis at 75 %, after an hour of warm-up;
- **CPU:** doubled, and at least half a core more. The metric is in cores, which the first version wrongly read as
  a share.

**Results.**
- Third holdout, fixed before it was run: v4 found `adHighCpu` at minute 5 where v1 found nothing, and raised no
  more alarms (1 of 10 clean minutes for both).
- Second holdout, seen while designing v4: the leak at minute 4, with no more alarms than v1.

v4 replaces v1 in the live watcher and records its criteria with every anomaly. One blind detection is little
evidence; the detector stays the part of Unbidden most in need of measurement.

## D-032 · 2026-10-27 · A full-table-scan check that reads rates, and why it opens nothing on the fork

**Setup.** With a GitHub token in its workspace (written by David's approval, readable by him only), the fork's
autonomous watcher can now publish, merge and deploy. An L5 needs a new improvement for it to find.

**Check.** A new World Model check reads Postgres's own per-table statistics (`pg_stat_user_tables`, read-only). It
flags a table of 10,000 rows or more that was read whole at least 10 times since the previous map, by endpoints that
read it.

**Why it reads rates.** The fork's `item` shows 264 sequential scans that read 33.6 million rows, but the counter did
not move in 90 s while index scans grew by 170. Those scans predate the index Unbidden deployed during the event.
A check on cumulative counters would have proposed a fix for a problem already fixed. The check therefore compares
each map with the previous one, and on the fork it opens nothing, which is the right answer.

**Status.** No new L5 is claimed. The fork has no measurable improvement left that Unbidden can find. The check
stays, to catch a regression.

## D-033 · 2026-10-27 · What the prototype knew and this product had lost; the sustained detector ported

An audit of the earlier prototype (`satisfymath/unbidden`, about 27k lines) against this product listed what it had
and this product lacked, in order of value:
1. a sustained-degradation detector;
2. logs as evidence (windows, shape groups, error after deploy);
3. authorised file and ssh log sources;
4. an external probe of public URLs that reads the running commit from `/health`;
5. an endurance protocol with criteria fixed in advance;
6. load tests as experiments;
7. "Ask" requests in natural language;
8. a Director with a value-of-information term;
9. dependency-vulnerability fixes.

Already here, or deliberately dropped: spend caps, merge caps, scoped approvals, the kill switch and the Postgres
store.

**Ported first: the sustained detector.** The prototype's lesson was a p95 of 2.5 s for four hours that nothing
flagged, because a deploy every twenty minutes reset the baseline.
- `observe/impact.py:sustained` is the prototype's judge: the newest 3 samples all above the largest of 1.5×, +50 ms
  and 4 MADs over the oldest samples.
- The live watcher checks each probed endpoint once a minute against the oldest half hour of the last four hours,
  whatever was deployed in between. When the code changed, it opens a read-only investigation between the commit at
  the start of the window and the current one; when it did not, it says the cause is data, load or the environment.
- From Prometheus, `health` reports a service whose p95 now sits above its own p95 of four hours ago. This is a
  separate signal, not part of the verdict: it is not calibrated on a holdout yet. Its first live reading, checkout
  at 182 ms against about 99 ms, came on a day of heavy load on the host.

## D-034 · 2026-10-27 · Logs as evidence; a third system, mealie, and what it broke

**Logs as evidence (second item of D-033).** Ported as `observe/logs.py`. It reads the compose project's container
logs every 5 minutes, groups lines by their normalised shape, and reports a shape that is new after a deploy, or an
error rate that grew. Each signal carries its evidence (shape, counts, first line). It reads and reports. It does not
change verdicts: like the sustained Prometheus signal, it is not calibrated yet.

**Third system.** mealie (FastAPI, Vue, Postgres; 283 live endpoints, 70 tables) runs locally:
- branch `unbidden-env`, with a compose override for Postgres and the project name `mealie`;
- 400 synthetic recipes, foods, units and labels from mealie's own seeders;
- a dedicated probe user;
- mandate autonomous, as in the other test environments. GitHub points at `satisfymath/mealie`, never upstream. That
  fork and its token do not exist yet, so proposals stay as local branches.

**What it broke, fixed:**
1. *The compose project was found from the repository root.* `docker compose --project-directory <repo>` fails when
   the compose files live in `docker/`. Containers, investigation logs and Forge logs now name the project: compose's
   own `name:`, else the directory's name.
2. *Code locations of endpoints.* 40 of 323 endpoints stayed as guesses beside the live ones:
   - a file with several routers gave every route the first prefix;
   - a bare mount became `GET `;
   - parameter names differ between code and schema;
   - a router mounted twice (public and private) was ambiguous.

   Worse, the old rule had given `POST /api/auth/oauth/native/token` the code of `POST /token`. Now a route takes its
   own router's prefix and is matched with parameter names ignored. Among several candidates, the one sharing the
   most words with the file wins, then the shortest. A tie stays a guess.

   **Result:** 270 of 283 live endpoints carry their code location, and all 270 were checked against the decorator
   they point to: 0 wrong. Of the 7 guesses left, 5 are validators mounted with `include_in_schema=False`, real
   routes the schema hides; one is a true tie; one is an image route not seen live. fst: 23 of 23, up from 22.

**Status.** No L5 on mealie yet. The watcher is now probing it. The next step is whether anything measurable is worth
improving.

## D-035 · 2026-10-27 · First L4 on mealie: an index found, written, and measured by Unbidden

**Result.** Unbidden found that `shopping_list_items.food_id` has no index and that mealie's own code filters by it:
- `repository_foods.get_empty`, a correlated `EXISTS` per food;
- `repository_foods.merge`.

It wrote the change itself, held it to mealie's checks (`ruff`, `mypy`), and measured it with a workload inside
mealie's test suite: 2,000 foods and 200,000 synthetic list items, called as a normal user.

| | Value |
|---|---|
| `GET /api/foods/empty`, median | 14,524 ms → 7.2 ms |
| one-sided Mann-Whitney | p = 3.4e-08 |
| 95% CI of the median difference | [13,445, 15,827] ms |

The change is two lines: the migration and `index=True`. It is a local branch (`a351dc2`), not published: there is
no fork or token for satisfymath yet.

**What this is not.**
- It is not L5. The data is synthetic and its scale (200k items in one group) is far above a household's; the effect
  grows with foods × items, so it is smaller at real sizes. Nothing was deployed or observed live.
- The suite already fails in the sandbox before the change; the candidate adds no failures.

**What it took** (each a bug in Unbidden, fixed, in commit order; each attempt they consumed was given back with
`reopen`, recorded):
1. The compose project was found from the repository root.
2. Endpoints' code locations: per-router prefixes; parameter names; double mounts.
3. The scan:
   - C headers from Debian;
   - Python from `requires-python`;
   - the repository's cooling period;
   - mypy.
4. A lab that cannot start counted as a failed experiment, and the Director declined on it.
5. The CI test job: `locale-sync.yml`, which runs `gh pr create`, was chosen; Taskfiles were not read.
6. Models found only for SQLModel.
7. Job keys: an attempt-only key, then reused keys after resets. Hence `reopen()`.
8. Candidates: the model rewrote 10 KB files it saw cut. An index is now written from the finding.
9. The check listed endpoints that read the table rather than those whose code filters by the column.
   - `handler_source` ran into sibling methods.
   - Calls are now resolved to one definition by file name and receiver.
10. `pytest -n auto` was killed at the sandbox's memory limit before writing a line; the lab times serially.
11. The workload prompt:
    - asked for Postgres SQL on SQLite tests;
    - could not pass fixtures;
    - showed neither the fixtures, their types, the referenced models, nor a test calling the endpoint.

**Security, observed.** The egress gate blocked several workload prompts:
- over the 20 KB cap, because my larger test context pushed them past it; the budget is back to 9,000 characters;
- three times for a `credential_assignment` pattern from mealie's test fixtures (test passwords). None of
  Unbidden's credentials were in them.

**Six opportunities are not measured, on purpose.** Their only cost is the database's own check on deleting a parent
row, and the lab cannot yet tell whether the test database enforces foreign keys.

**Next for L5.** Deploy the branch to the local mealie with the mandate's deploy steps, on data shaped like a large
household, and observe `GET /api/foods/empty` live before and after.

## D-036 · 2026-10-27 · mealie's index, live: no change on Postgres, and an L5 that is not one

**What was done.**
1. A large household's shopping lists were seeded in the local mealie, through its API as the probe user: 50 lists
   × 100 items (5,000) over 580 foods, 80% checked off.
2. The watcher recorded a baseline of `GET /api/foods/empty`: 29 rounds, median 5.3 ms.
3. The `food_id` branch was deployed with `unbidden deploy`, through the guarded deploy path. The index and its
   migration (`7b1f2ec4d00a`) are live.

**Result.**

| `GET /api/foods/empty` (live) | Before | After |
|---|---|---|
| Median | 5.3 ms | 5.0 ms |
| p95 | 8.4 ms | 8.6 ms |

Within the criteria: no change claimed. Outcome class: **invalid**. The baseline deploy's commit is inferred: it was
running before Unbidden watched, and nothing in its image says what code it holds. The opportunity stays at **L4**.

**Why no change, predicted before the deploy.** The lab measured on the tests' SQLite. There, `NOT EXISTS (... WHERE
food_id = f.id)` runs once per food, so without the index it scans the table 2,000 times: 14.5 s at 200,000 items.
Postgres plans the same query as one hash anti-join, which `EXPLAIN ANALYZE` showed at 0.5 ms for 5,000 items. The
L4 is real for SQLite, mealie's default engine, and says nothing about this deployment.

**What changed in Unbidden.**
- A performance verdict records the engine it was measured on, and says so when the running system uses another.
- `unbidden deploy <ref>` deploys a local commit through the same guards as the merge path.
- Live outcomes are attached to any proposal whose commit is in the deployed version, not only merged ones.
- Ledger fixes:
  - A deploy that the watcher saw before Unbidden finished binding it is upgraded once the binding exists. It was
    recorded "inferred, by external" and never looked at again.
  - Build steps vouch only for services with a `build:`. A Docker Hub image (`postgres:16`) had been bound as built
    from the commit.
- The compose project name comes from the resolved path.

**What a valid L5 needs here.** A baseline deployed by Unbidden. Either deploy the next change on top of `a351dc2`,
or start from a version Unbidden deploys itself. The current mealie can no longer roll back below the index
migration without a downgrade. For this index, the meaningful live test is a mealie on SQLite.

**`unit_id`.** Not measurable with the current lab. No workload ran at the base in four rounds of five attempts.
Its endpoint is a merge that deletes what it merges.

## D-037 · 2026-10-27 · One spend ledger for the machine, autonomous probing, and a benchmark across repositories

**Why.** The next question is whether Unbidden can enter many systems it has never seen and show, without a person
directing each step, whether each one improved. Three things stood in the way: spend was bounded per workspace and
only after the fact, the autonomous loop never looked for crashes by itself, and the benchmark stopped at a scan.

**Credits, audited.**
- The Meta Model API key works and lists `muse-spark-1.3` (Standard) with `-contributor` variants. No endpoint gives a
  balance, usage or billing: every path tried (`/v1/usage`, `/v1/billing`, `/v1/credits`, `/v1/organization/*`,
  OpenAI's legacy billing paths) returns 404. The balance can only be read on the dashboard, by a person.
- Public sources, not verified against our account: $150 of credits per selected participant; Standard at US$1.25 /
  US$4.25 per million input / output tokens (the prices in `config.py`); credits claimable until Nov 4, 9 PM ET.
- Recorded remote spend in every surviving workspace state before this change: 33 calls, 104k input and 135k output
  tokens, US$0.70 at list price. A lower bound: state in `/tmp` scratchpads may have been lost before it was copied.

**The spend ledger** (`brain/spend.py`, `~/.unbidden/spend.db`).
- One ledger for every workspace on the machine. Before a remote call leaves, its worst cost is reserved in one
  transaction: every payload byte a token, plus all of `max_tokens`, at list price. A call that does not fit is refused
  and nothing is sent.
- After the call the reservation becomes the reported usage. A timeout, a 5xx or an answer without usage keeps its
  worst cost; a 429 or 400 costs nothing.
- The budget is the balance a person read (`unbidden spend --verified-balance <USD> --source <where>`), counted from
  that moment, minus a 20 % reserve that only `--release-reserve` frees. Without a verified balance, a US$1 allowance,
  enough to check the remote path. The mandate's monthly cap still applies per workspace.
- `-contributor` models are refused unless the config allows them: they trade data-use terms for price.
- The visual judge called the API directly and bypassed all accounting; it now reserves and settles like the rest.
- Every call carries `UNBIDDEN_RUN`, so spend is attributed to a run and a repository.
- Verified end to end: one synthetic call to Muse Spark 1.3, worst cost US$0.0092 reserved, settled at US$0.00049
  from 15 input and 111 output tokens reported.

**Autonomous probing.** After each scan the Director finds the repository's importable packages from the tree (src or
flat layout; tests and tooling excluded), records whether probing is worth it and why, and probes the package with the
most public surface once per commit. Before, robustness probes ran only when a person named the package.

**The scale benchmark** (`bench/scale.py`, `bench/repos/scale.yaml`, `bench/scale_report.py`).
- 10 pilot and 10 holdout repositories chosen by written criteria, pinned and committed before any run, including
  Go, Ruby and Rust repositories Unbidden does not analyze: they stay in the denominator.
- Per repository: `init`, the benchmark mandate (autonomous locally; GitHub, merge and deploy denied, since these are
  third parties' upstreams; profile `frontier`; a spend cap), `map`, `watch --once` under a wall-clock limit. The
  record is read from the workspace's state and the ledger, never from printed output.
- Outcome classes are fixed rules (`classify`). Rates carry Wilson intervals over stated eligibility. Level 5 needs an
  authorized deployment and none exists here: it is reported as not eligible, never as a failure or a success.
- A remote-model run refuses to start without a verified balance unless declared a method check.

**Method checks, under the US$1 allowance (no verified balance yet).** Each exposed a general failure, fixed:
1. humanize: hatch-vcs reads the version from `.git`, which a build context of manifests never has (version pinned
   for the dependency build). Then hatchling refused a missing `readme` (declared documents now copied). Then the
   package imported `humanize._version`, generated at build time (a stub at the path the config declares).
2. ky: a Node project without a lockfile was "no stack" while Python without one proceeds. npm now resolves it at
   provisioning time, said as a blind spot.
3. cobra: Go was skipped silently. Manifests of unanalyzed languages are now named.
4. The harness counted a probe that was decided but never ran as a bootstrap; the cycle now records whether the
   probe's tests ran.
5. On humanize the probe found `KeyError` in `naturaldelta(0, minimum_unit='')` and recorded nothing. Newer pytest
   omits `in function` from frames, Hypothesis says "Failing test case", and the short summary was read as part of
   the last failure. All fixed with a test. The next probe drew different tests and did not hit it: **a probe is a
   sample**, and one probe per commit finds a given crash only sometimes.

## D-038 · 2026-10-28 · The pilot's only L4 was false; CI parity, relevance-based context, and what pilot 2 showed

**The false positive.** Pilot 1's only L4 (marshmallow) removed two `type: ignore` comments that the sandbox's mypy
called unused. The team's mypy job was green on that commit. Unbidden measures under the oldest Python a project
supports (3.10); the team's CI also runs 3.11-3.14, where the ignores are needed. The patch would have turned their CI
red. The lab's L4 criteria (targeted findings gone, no test regressed) cannot see this. The original record is kept as
produced.

**CI parity** (`lab/fixlab.py`, `observe/ci.py:ci_python_versions`). The Python versions a CI runs are read from
setup-python values and matrices, tox's envlist (ranges included), nox and `.python-version`. After a candidate
passes, the targeted tool runs again on base and candidate under the newest of them, with the project's locked
toolchain. A finding the candidate adds there rejects it. When parity cannot be checked, the evidence stops at L3.
- On the real candidate: 2 new mypy findings under 3.14, rejected.
- Pilot 2, unaided: Muse Spark's new candidate for the same opportunity was rejected the same way, then declined after
  two experiments.
- No rule names marshmallow.

**The Director reads the CI in the autonomous cycle.** The rule that declines findings a green CI of the same tool
does not report covered only style, and only `unbidden decide` read the CI; the cycle decided without it. One helper
now feeds both, read once per commit. It covers every category, and a fork's shared commits are judged by its parent's
CI. Pilot 2 showed the rule still could not fire on marshmallow: its CI runs mypy through `tox -e ${{ matrix.tox }}`.
`ci_commands` now follows tox and nox to where their environments are defined, and reads matrix values.

**Context within the egress cap** (`lab/context.py`). The fix request sent `tests/test_fields.py` whole (31 KB).
Guardian's 20 KB cap blocked it, and the router silently handed the task to Glimmer (33 GB, 6 minutes).
- The cap is unchanged.
- Whole files are sent when they fit; otherwise excerpts: each finding's enclosing function (AST) or a window, merged,
  plus the import header, measured in JSON-escaped bytes against half of what the cap leaves (a repair repeats the
  answer).
- If every finding cannot be shown, nothing is sent and the lab says so.
- The model answers excerpts by line range; code splices them back and refuses lines it was not shown.
- On the real file: 30,012 bytes become 1,010.
- Every tier fallback is a `model.fallback` event with its cause. `models.local_fallback: deny` refuses the local one
  (the benchmark's setting; the product default stays `allow`). Pilot 2: two fallbacks refused, none taken.

**Provenance.** Every experiment records Unbidden's version, commit and whether its package was dirty, each tier's
model and thinking, the profile and fallback policy, the images, and what the lab knows (interpreter, seed, engine).
The benchmark identifies the code under test by the `unbidden/` tree and refuses to start on uncommitted code.

**Pilot 2** (`docs/bench/2026-10-28-scale-pilot-2.md`, forks only, US$0.14).
- Bootstrapped 7/10; one opportunity set (marshmallow).
- The false positive was rejected.
- One L4 lies outside the team's checked configuration: `try/except ImportError` became a `sys.version_info` check
  so mypy under 3.10 sees `Unpack`. Clean under both versions and behavior-preserving, but the team does not
  type-check under 3.10. It is not counted as an improvement.
- Its pull request to the fork failed with 422: `init` assumed `main` after a shallow fetch, and the fork's base is
  `dev`. The default branch now comes from the remote.
- pyjwt's computed version broke its dependency image. The build context's copy of `pyproject.toml` now gets a static
  version.

**humanize's KeyError** is real (direct, 10/10 seeds), found by 0 of 10 fresh probes (1 of 13 overall). Kept at L2.

**Spend reconciled.** US$0.956 in 50 calls before pilot 2 (32 before the ledger, 18 after, plus one refused at the
gate). Nothing is unaccounted between the ledger and the workspaces.
