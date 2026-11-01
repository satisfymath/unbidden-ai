# Map of real sources

What the engine already records, where, and how the web layer reads it. Everything here was verified in the code at
base `1a9093c` (`docs/frontend/BASE.md`).

## The workspace state (`.unbidden/state.db`, SQLite, WAL, schema `user_version` 2)

Owned by **one process** (`unbidden watch` or a CLI command). The web reader never opens it through `Store.__init__`
(which runs migrations and sets pragmas); it opens `file:...?mode=ro` with short read transactions and checks the
schema version is one it understands (`unbidden/web/reader.py`). WAL is honoured by SQLite itself on a read-only
connection: a copy of the file alone would miss the `-wal` content, so no copy is ever made.

| Table / collection | Contract | Used for |
|---|---|---|
| `events` (append-only, `seq` cursor, `correlation_id`) | `contracts/events.py` `Event`, 41 types | live stream, timelines, per-opportunity history |
| `docs.opportunities` | `contracts/opportunity.py` `Opportunity` (`details`: decision, verdict, experiment_id, rechecks, revocations, outcome, blocked) | findings, levels, decisions |
| `docs.experiments` | `contracts/experiment.py` `Experiment` (`samples_before_ms`, `samples_after_ms`, `sessions`, `control`, `confirmation`, tests) | latency charts, test summaries |
| `docs.experiment_specs` | `ExperimentSpec` | what an experiment measures, fixed beforehand |
| `docs.proposals` | `Proposal` | proposals and PR state |
| `docs.decisions` | `contracts/opportunity.py` `Decision` | candidate actions with utility |
| `docs.world` (id `world`) | `contracts/world.py` `WorldModel` (resources, relations with evidence) | system map, evidence-backed connections |
| `docs.deployments` | `Deployment` | deploy ledger |
| `docs.deploy_verdicts` | judged deploys | L5 outcomes |
| `docs.connections` | `contracts/connection.py` `Connection` | resources and what was checked |
| `docs.needs`, `docs.capabilities`, `docs.stats_capabilities`, `docs.integrations` | `CapabilityNeed`, Forge cards | capability needs, approvals |
| `docs.actions`, `docs.acceptances`, `docs.goal_runs`, `docs.blocks`, `docs.holds`, `docs.approvals` | `Action`, `Acceptance`, `GoalRun`, `Block`, `Hold`, `Approval` | actions, acceptance evidence, blocks |
| `docs.model_runs`, `docs.egress` | `ModelRun`, `EgressAttempt` | model calls, routes, what left the machine |
| `rounds` | probe rounds per target/version/deploy (statuses, latencies) | live latency per deploy |
| `kv` | `head`, `last_scan`, `baseline_checks`, `readiness_block`, `open_anomalies`, `deploy_sequence`, `repo_visibility`, `log_signal:*`, `log_windows:*` | project checks, scan summary, anomalies |
| `jobs` | queue | what is running or queued (read only) |

Other files of a workspace: `mandate.yaml` (autonomy, egress, models profile, connections, goals), `config.yaml`
(providers, routing), `KILL` (the kill switch, a file), `artifacts/` (screenshots, scans).

## Machine-wide

- `~/.unbidden/spend.db` + `budget.yaml` (`brain/spend.py`): remote spend across workspaces, envelopes. Read through
  `SpendLedger.rows()` and `.status()` (its own connections, multi-process safe).
- Ollama at `http://localhost:11434` (`/api/tags`) and the Meta API (`config.yaml` routing): where inference runs.
  The server is local; the model is not necessarily (`route` on the top bar says which).

## What the engine can already do (operations the web layer may expose)

| Operation | Engine path | Web exposure |
|---|---|---|
| activity report | `director.activity.build(store, workspace, spend_rows)` | reused as-is on the read-only store (`/api/summary`) |
| per-opportunity history | `store.events(correlation_id=...)` | `/api/opportunities/{id}` |
| kill switch | `guardian/killswitch.py` `KillSwitch` (a file) | `/api/actions/kill`, `/api/actions/resume` (file-based, safe across processes) |
| policy verdicts | `guardian/policy.py` `PolicyEngine.evaluate` | `/api/policy/evaluate` (read-only: what the mandate would say) |
| approve / reject a proposal | `cli.py` `_approve`/`_reject`: writes the store and enqueues a job | **not** done from the web (it needs the store's writer); the UI shows the exact CLI command |
| deploy, rollback, drills, forge approve | `cli.py` | same: command shown, never simulated |
| model call | `brain/router.py` `Brain.complete` (Guardian, egress, classification, spend, kill switch) | the chat planner, purpose `web.chat`, through the web's own store (`web-state.db`), never from the browser |

## Published records usable as history (`docs/bench/`)

Closed runs, sanitised, committed by the engine session. Read-only by this branch.

| Record | Content | Used as |
|---|---|---|
| `stage9-demo/DEMO-B-1/{record,activity}.json`, `cycles.log` | a proactive run on conduit: 6 opportunities, 2 proven L4 with session medians, proposals, connections, integrations, goals, spend | historical workspace "conduit (DEMO-B-1)" |
| `stage10-eval/aegra/{A-1,B-1}/` | goal runs, capability needs, project checks | historical workspace "aegra" |
| `stage10-revalidation/v4-*/{fst,mealie}-*.json` | experiments under perf-v4 with raw sessions, control and confirmation samples | latency datasets of an experiment |
| `mealie-l5/{deploy-verdict,rounds-foods-empty,outcome,revalidation}.json`, `deployments.jsonl` | probe rounds per deploy, a deploy verdict, an L5 outcome | live-probe datasets of a deploy |

Limits: the summaries (`activity.json`) cap lists at 8 (`director/activity.py` `TOP`); the record is a summary, not
the full state. Where a dataset is needed (samples), the revalidation and L5 files hold the raw values.

## Endpoints the engine lacked (added in `unbidden/web/`)

- paginated detail: opportunities, events (cursor), model runs, experiments, world, connections, deployments;
- datasets: experiment samples, probe rounds, spend by run, event counts over time, with provenance per row;
- presentation: widgets, edges, viewport, undo history, per workspace (own file);
- chat: messages, planner, typed tools;
- live: `/api/events/stream` (SSE, resumes from `Last-Event-ID` / `after=` cursor, heartbeat, staleness).
