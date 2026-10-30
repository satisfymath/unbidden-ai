# Diagnostic run r1 on Spoolman: invalid as evidence

Started at product c816737 (`frozen.json`) with `--project ~/unbidden-ai-pr1`, the tree being edited: later cycles
loaded files changed during the run (`forge/api_client.py`, `connect/pages.py`, `lab/seed.py`, `lab/served.py`). It
is kept only for what it showed, and was stopped after its two performance experiments were blocked. US$0.55 from
`s10-dev`. From then on every run uses a separate frozen worktree.

What it showed (artifacts/, each request attempt and why it was not valid):
- `filament.vendor_id` via `PUT /api/v1/spool/{id}/measure`: 5 requests, every call 404: the seeder filled only the
  measured table and what it requires; the endpoint acts on `spool`, left empty. No request could have been valid.
- `spool.filament_id` via a delete: 5 requests, every call 307: `vendor` (an optional reference) was not seeded, the
  values query returned nothing, and `/vendor/{value}` became `/vendor/`, which redirects.
Both are the seeder's (fixed: the tables the endpoints' paths name are seeded with their references; a values query
that returns fewer rows than calls is refused before sending, with the data counts). Readiness recorded correctly:
environment ready, checks reproduced (278), workload not valid, each with its reason.
