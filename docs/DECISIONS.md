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
