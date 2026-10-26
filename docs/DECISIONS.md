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
