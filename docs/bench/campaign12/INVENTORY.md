# Campaign 12: inventory of resources created (everything here is this campaign's; nothing else is touched)

| Kind | Name / path | Created | Purpose | Cleanup |
|---|---|---|---|---|
| directory | `~/unbidden-lab/c12/` | 2026-11-01 | every campaign resource: the installed tool's HOME (`home/`), the wheel served (`dist/`), repository clones (`repos/<name>`), archived workspaces (`archive/`) | remove the directory after the report; never touches `~/unbidden-lab/<other>` |
| uv tool | `~/unbidden-lab/c12/home/tools/unbidden-ai` | 2026-11-01 | the frozen wheel installed (`install.sh` from `127.0.0.1:8790`) | `sh install.sh --uninstall --yes` with that HOME |
| ledger envelopes | `s12-pilot`, `s12-eval`, `s12-dev`, `s12-confirm` | 2026-11-01 | the campaign's spend, in the machine's one ledger | kept (the ledger is never reset) |
| git worktree | `~/unbidden-ai-campaign` (`feat/64-campaign`) | 2026-11-01 | the candidate, the harness, the records | `git worktree remove` after the branch is pushed |

Forks (`satisfymath/c12-*`), campaign branches on existing forks (`c12/*`), labs (`unbidden.lab.id=c12-<name>`,
compose projects `c12-<name>`), Docker volumes and the campaign HOME's credentials file are appended below as they are
created, one line each, with the date.
| fork | `satisfymath/c12-spoolman` (of `Donkie/Spoolman`, default `master`) | 2026-11-01 | Level B pull requests and merges for spoolman | keep (campaign evidence) or delete after the report, David's call |
| fork branch | `satisfymath/rich:c12-base` (existing fork; new branch at `9d8f9a37`) | 2026-11-01 | Level B base for rich; earlier `unbidden/*` branches untouched | delete the branch after the report |
| clones | `~/unbidden-lab/c12/repos/c12-<name>` (Level A), `~/unbidden-lab/c12/<name>` (Level B) | 2026-11-01 | checkouts at the pins; `.unbidden/` archived to `~/unbidden-lab/c12/archive/` | remove with the directory |
| scenario HOMEs | `/tmp/c12-scn-*` (throwaway ledgers for the credential and budget scenarios) | 2026-11-01 | seeded scenarios | removed by the script |
| compose projects | `c12-fst`, `c12-spoolman` (labels `unbidden.lab.id=c12-fst|c12-spoolman`, volumes `c12-*-data`) | when Level B runs | labs | `labs.down(app)` (volumes included) |
| diagnostic | fst fork: PR #5 `c12-ci-probe` (opened and closed, branch deleted); one `workflow_dispatch` run of `playwright.yml` on `c12-base` (run 41345639014) | 2026-11-01 | does the fork start workflows? (no for pull_request; yes for dispatch) | done; nothing left |
| fork branch | `satisfymath/full-stack-fastapi-template:c12-base` and `satisfymath/marshmallow:c12-base` (existing forks; new branches at the pins) | 2026-11-01 | Level B bases | delete after the report |
| pull requests | fork `rich` #2, #3, #4 (ruff fixes, autopilot, rich B1); fork `full-stack-fastapi-template` #4 (index on `item.owner_id`, L4, fst B1) | 2026-11-01 | the agent's own effects, evidence | keep open until the report; merge is a person's step (counted) |
