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
