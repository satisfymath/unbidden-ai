"""Every sentence the setup assistant and the home screen say, in one place (English first; a translation adds a
table here, not code elsewhere)."""

from __future__ import annotations

T: dict[str, str] = {
    "welcome": "Unbidden is not set up in this repository yet. This takes a few minutes and calls no model.",
    "resume": "Picking up where setup stopped ({done}); answered sections are kept; `setup --all` redoes them.",
    "found.title": "Found",
    "found.repo": "repository {repo} · branch {branch} · head {head}",
    "found.repo.nocommit": "repository {repo} · branch {branch} · no commit yet (the compose files are read at HEAD)",
    "found.noremote": "  no GitHub remote named origin: proposals stay local branches until one exists",
    "found.scope.ok": "in scope",
    "found.scope.no": "outside what this version supports",
    "found.compose": "compose service, read on its own",
    "found.notgranted": "found in compose env, not granted",
    "found.connections": "connections, as committed at HEAD in {path}: {items}",
    "found.connections.none": "none declared",
    "found.connections.nocompose": "connections: no compose file at HEAD; `unbidden setup connections` adds one",
    "found.key": "model key {name}: {state}",
    "found.key.present": "saved on this machine",
    "found.key.absent": "none yet",
    "found.github": "GitHub access: {source}",
    "found.github.file": "a token saved for Unbidden",
    "found.github.env": "a token from the environment",
    "found.github.gh": "the gh CLI's sign-in (held while Unbidden runs, never copied)",
    "found.github.token": "a token you pasted",
    "found.github.none": "none: proposals stay local branches",
    "found.github.ok": "  signed in as {login}; it can push to {slug}",
    "found.github.nopush": (
        "  signed in as {login}, but that account cannot write to {slug}: ask for access, or sign in with the "
        "account that has it"
    ),
    "found.github.unverified": "  not confirmed with GitHub ({detail})",
    "found.language": "Language: {name} ({how}); /language or `unbidden setup language` changes it",
    "github.ask": "GitHub access for pull requests?",
    "github.gh": "gh: sign in to GitHub with the gh CLI (installed first if missing); the browser opens with a code",
    "gh.install.ask": "gh is not installed. Install it now in your terminal with `{command}`?",
    "gh.install.none": "gh is not installed and no package manager was found here: {site}, then `unbidden setup`.",
    "gh.install.skipped": "Not installed. Later: {site}, then `unbidden setup credentials`.",
    "gh.install.failed": "gh did not install; {site} explains the ways. Proposals stay local branches for now.",
    "gh.login": (
        "Signing in with gh: it shows a code and opens the browser; Unbidden reads the session when it returns."
    ),
    "gh.failed": "gh did not sign in; proposals stay local branches. Later: `gh auth login`, then `unbidden setup`.",
    "github.token": "token: paste a token (fine-grained, this repository, contents and pull requests)",
    "github.skip": "skip: proposals stay local branches; `unbidden setup credentials` later",
    "priorities.title": "Priorities",
    "priorities.ask": "What should it look for first? (comma-separated; e.g. correctness, performance, consistency)",
    "models.title": "Model access",
    "models.key.why": (
        "A Meta API key lets heavy work go to Meta's API (secrets and production data never leave; private code "
        "only renamed by the privacy bridge). Without one, only the local model works."
    ),
    "models.key.ask": "{name} (hidden; Enter to skip and use the local model only)",
    "models.key.skipped": "No key. Later: `unbidden key set`.",
    "models.key.shape.command": "That looks like a command, not a key. Paste the key itself (it has no spaces).",
    "models.key.shape.spaces": "A key has no spaces. Paste the key itself.",
    "models.key.shape.short": "A key is longer than that. Paste the key itself.",
    "models.key.proving": "Proving the key with one short call to Meta's API (less than a cent, in the ledger).",
    "models.key.verified": "Key accepted: {model} answered (US${usd:.4f}).",
    "models.key.rejected": "Meta refused this key ({why}). Nothing works with it.",
    "models.key.unproven": "The key could not be proven now ({why}); it is saved, and `unbidden key` proves it later.",
    "models.key.next": "What now?",
    "models.key.next.key": "key: paste another key",
    "models.key.next.local": "local: use a model on this machine instead (Ollama)",
    "models.key.next.none": "none: continue without a model (the agent will not start)",
    "models.key.none": (
        "No working model. `unbidden key set` or `unbidden setup models` later; `start` refuses until then."
    ),
    "models.key.gaveup": "No key accepted after {n} tries. Later: `unbidden key set`.",
    "models.ollama.ask": (
        "Ollama is not installed. Install it now in your terminal with `{command}`? (it may ask your password)"
    ),
    "models.ollama.manual": (
        "Ollama is not installed and this machine has no installer to run: {site}, then `unbidden setup models`."
    ),
    "models.ollama.skipped": "Not installed. Later: {site}, then `unbidden setup models`.",
    "models.ollama.failed": "Ollama did not install; {site} explains the ways.",
    "models.ollama.down": (
        "Ollama is installed but does not answer at {url}: run `ollama serve`, then `unbidden setup models`."
    ),
    "models.local.verified": "The local model answers: {tag}.",
    "models.local.failed": "The local model did not answer ({why}). `unbidden doctor --fix` tries again.",
    "models.local.small": (
        "{tag} is small: it serves what never leaves the machine (renaming, reviewing). Heavy work needs a "
        "Meta API key."
    ),
    "models.local.nofit": "No local model fits this machine ({reason}); a Meta API key is the way.",
    "key.title": "Model key",
    "key.ask": "{name} (hidden)",
    "key.none": "no {name} saved on this machine; `unbidden key set` saves and proves one",
    "key.proven": "{name} saved and proven {at}: {model} answered",
    "key.rejected": "{name} saved but Meta refused it {at}; `unbidden key set` replaces it",
    "key.unproven": "{name} saved, not proven yet ({why})",
    "key.removed": "{name} removed from {path}.",
    "models.chosen": "model option: {option} ({why}); `unbidden setup models` changes it",
    "models.why.flag": "chosen by --models",
    "models.why.mixed": "a key and a local model are both here",
    "models.why.api": "a key is here and no local model is installed",
    "models.why.local": "a local model is installed and no key is saved",
    "models.why.none": "no key and no local model yet",
    "models.none": (
        "No model yet: install Ollama (ollama.com) and run `unbidden setup models`, or add a key; `unbidden start` "
        "refuses until one exists."
    ),
    "models.hardware": "machine: {described}",
    "models.local_model": "local model for this machine: {tag} ({reason}){installed}",
    "models.not_installed": " · not installed",
    "models.pull.ask": "Download {tag} now? About {gb:.0f} GB on disk and in memory while it runs.",
    "models.pull.skip": "Not downloaded. Later: `unbidden doctor --fix`.",
    "models.private_code.ask": "May private code reach Meta's API un-renamed? (deny keeps it behind the bridge)",
    "private_code.title": "Private code",
    "credentials.title": "Credentials",
    "credentials.where": "Saved to {path} (mode 600), referenced by name; never written to the repository or logs.",
    "credentials.have": "{name} is already saved. Keep it?",
    "credentials.ask": "{name} (hidden; leave empty to skip)",
    "credentials.saved": "{name} saved.",
    "credentials.skipped": "{name} not set: remote calls are refused until you add it (`unbidden key set`).",
    "credentials.github.ask": "Should Unbidden be able to publish pull requests? (needs GITHUB_TOKEN)",
    "recon.title": "Reconnaissance",
    "recon.explain": (
        "Before the agent runs, each resource is connected, skipped on purpose, or blocked with a reason: the "
        "stack, the database, GitHub, external APIs, the deploy procedure."
    ),
    "recon.stack.none": "No compose file: nothing to start; the map reads the repository only.",
    "recon.stack.running": "The stack runs: {n} container(s) of {project}.",
    "recon.stack.down": "The stack is down; a map of the running system waits for `docker compose up`.",
    "recon.stack.ask": "The stack is down. Start it now in your terminal with `{command}`?",
    "recon.stack.starting": "Starting the stack; the terminal shows compose's own lines.",
    "recon.stack.started": "The stack is up.",
    "recon.stack.failed": "The stack did not come up; `docker compose up` in your terminal says why.",
    "recon.stack.skipped": "Not started. The agent maps the repository only until it runs.",
    "recon.map.mapping": "Mapping the running system (containers, databases, endpoints; no model call).",
    "recon.map.done": "Mapped: {resources} resources, {blind} blind spot(s).",
    "recon.db.container": "{service}: {count} table(s) read inside its container; nothing leaves it.",
    "recon.db.nostack": "{service}: not read; the stack is down.",
    "recon.db.unread": "{service}: not read ({why}).",
    "recon.db.grant.ask": (
        "{service} publishes port {port}. Grant Unbidden a read-only role over the network too (for the labs and "
        "the dashboard's queries)?"
    ),
    "recon.db.grant.username": "read-only role name",
    "recon.db.grant.password": "password of {username} (hidden; kept in .unbidden/.env)",
    "recon.db.grant.skipped": "No network grant; the in-container read stays.",
    "recon.db.grant.ok": "Grant {id} connected: {detail}",
    "recon.db.grant.failed": "The grant did not connect ({state}: {detail}); nothing was written to the mandate.",
    "recon.github.none": "GitHub: no access; proposals stay local branches (`unbidden setup credentials`).",
    "recon.github.unverified": "GitHub: access found but not confirmed ({detail}); no grant written.",
    "recon.github.nopush": (
        "GitHub: {login} cannot write to {slug}; pull requests will fail until an account that can signs in."
    ),
    "recon.github.ok": "GitHub: {login} can push to {slug}; written as the `github` connection.",
    "recon.api.found": "External API {location} ({evidence}).",
    "recon.api.ask": "Access to it?",
    "recon.api.key": "key for {location} (hidden; kept in .unbidden/.env)",
    "recon.api.saved": "Saved as {ref}; the connection is granted for reads.",
    "recon.deploy.declared": "Deploy steps declared: {steps}",
    "recon.deploy.none": (
        "No deploy procedure found in the repository; declare one in operations.deploy_steps when there is one."
    ),
    "recon.deploy.found": "Deploy procedure found, not adopted (scripted run): {command}",
    "recon.deploy.ask": "Deploy with `{command}` (found in the repository)? It becomes operations.deploy_steps.",
    "recon.deploy.adopted": "Adopted: {command}",
    "recon.deploy.skipped": "Not adopted; deploys stay a person's.",
    "recon.drill.nohealth": "Rollback drill: not possible yet, no live health endpoint on the map.",
    "recon.drill.nocommit": "Rollback drill: not possible yet, fewer than two commits.",
    "recon.drill.ask": (
        "Run the rollback drill now? It deploys {previous} with your steps, checks health, and deploys back (minutes)."
    ),
    "recon.drill.skipped": "Drill skipped; `unbidden drill` runs it later (autonomous mode needs it).",
    "recon.drill.running": "Drill running; watching {url}.",
    "recon.drill.passed": "Rollback drill passed (back {back}, forth {forth}).",
    "recon.drill.failed": "Rollback drill failed (back {back}, forth {forth}); autonomous mode stays off.",
    "recon.done.complete": "Reconnaissance complete.",
    "recon.done.incomplete": "Reconnaissance incomplete: {why}. `unbidden setup recon` runs it again.",
    "recon.status.never": "never ran: `unbidden setup recon`",
    "recon.status.complete": "complete ({at}); stack {stack}",
    "recon.status.incomplete": "incomplete: stack {stack}; {why}",
    "autonomy.title": "Autonomy and scope",
    "autonomy.explain": (
        "A mode sets what reaches GitHub and production. The other permissions are granted on their own and never "
        "inherited from another project. A credential's own powers never widen the mandate."
    ),
    "autonomy.supervised": "supervised: prepares everything, asks before a pull request; never merges or deploys",
    "autonomy.autopilot": "autopilot: opens pull requests on its own for proven work; people merge",
    "autonomy.autonomous": "autonomous: also merges L4 work, deploys with the team's steps and rolls back",
    "autonomy.ask": "How much may Unbidden do on its own?",
    "autonomy.blocked": "autonomous is not available yet:",
    "autonomy.fallback": "Which mode until then? (no default; nothing is chosen for you)",
    "autonomy.fallback.chosen": "Until then: {mode}.",
    "autonomy.blocked.result": "blocked: {mode} cannot be switched on yet and no other mode was named",
    "autonomy.blocked.keep": (
        "Nothing written; {path} keeps its previous configuration. Name the mode to use until then with "
        "--mode-fallback supervised|autopilot, or complete the requirements above."
    ),
    "autonomy.connections.ask": "May it write through connections (typed, limited, undoable actions)?",
    "autonomy.effective": "Effective permissions",
    "connections.title": "Connections (optional)",
    "connections.ask": "Grant a connection? (one found in compose, or a new postgres or http_api; none to finish)",
    "connections.prefilled": "  {kind} {location}, from the compose files; Enter keeps each suggested value",
    "connections.id": "connection id (e.g. shop-db)",
    "connections.location": "location (postgres: host:port/db · http_api: http://host:port)",
    "connections.docs": "OpenAPI document URL (optional)",
    "connections.username": "database username (read-only role)",
    "connections.environment": "environment (staging, development, production; production is never written)",
    "connections.credential": "credential name, e.g. SHOP_READER_PW (the value is asked next and kept in the project)",
    "budget.title": "Budget",
    "budget.ledger": (
        "Machine ledger: {reason}; permitted US${permitted:.2f} · spent US${spent:.4f} · available US${available:.4f}"
    ),
    "budget.envelopes": "envelopes: {envelopes}",
    "budget.explain": (
        "Provider credits and authorized spend are different things: the cap a person entered with "
        "`unbidden spend --verified-balance` is what this machine may spend; it is never raised or reset here."
    ),
    "budget.ask": "Monthly cap for this project (US$)",
    "dashboard.title": "Dashboard",
    "dashboard.explain": (
        "Opening the dashboard, restoring its layout and showing records calls no model; chatting or asking for "
        "analysis can."
    ),
    "dashboard.ask": "Dashboard: open it after setup (now), later from the CLI (later), or not at all (never)?",
    "language.title": "Language",
    "lang.how.env": "from UNBIDDEN_LANG",
    "lang.how.saved": "saved on this machine",
    "lang.how.locale": "from the terminal's locale",
    "lang.how.default": "the default",
    "language.ask": "Which language should Unbidden speak to you?",
    "summary.title": "Summary",
    "summary.models": "models: {option} (profile {profile}, private code to frontier: {private})",
    "summary.mode": "mode: {mode} · writes through connections: {connections}",
    "summary.budget": "monthly cap: US${budget:.2f}",
    "summary.credentials": "credentials saved: {names}",
    "summary.github": "GitHub access: {source}",
    "summary.priorities": "priorities: {names}",
    "summary.dashboard": "dashboard: {choice}",
    "summary.defaults": "not asked, defaults kept: {names} (`unbidden setup <section>` changes one)",
    "summary.diff": "Changes to {path}:",
    "summary.nodiff": "No change to the mandate.",
    "summary.apply": "Apply these changes?",
    "summary.dry": "Nothing written. Rerun with --yes to apply.",
    "summary.written": "Mandate written and recorded (MANDATE_CHANGED).",
    "summary.cancelled": "Nothing written; your answers are kept in {path} for `unbidden setup`.",
    "next.title": "Next",
    "next.scan": "unbidden scan        one cycle in the foreground: map, the project's checks, decisions",
    "next.doctor": "unbidden doctor      what works here and what is optional for the option you chose",
    "next.home": "unbidden             the project's state, blocks and the next action",
    "next.ui": "unbidden ui          the dashboard (arrives with delivery D)",
    "home.title": "{repo} · head {head} · mode {mode} · models {profile}",
    "home.kill": "kill switch engaged: nothing runs until `unbidden resume`",
    "home.opps": "opportunities: {counts}",
    "home.scan.none": "no scan yet",
    "home.scan": "last scan: {when}",
    "home.spend": "spend: US${spent:.4f} spent on this machine · US${available:.4f} available under the cap",
    "home.next": "next: {action}",
    "home.agent.running": "agent: running pid {pid} since {since}, log {log}",
    "home.agent.stopped": "agent: not running",
    "home.agent.stale": (
        "agent: not running; the last run (pid {pid}) ended without 'unbidden stop'; {jobs} job(s) resume on start"
    ),
    "home.commands": (
        "commands: setup · doctor · scan · start · stop · status · inbox · activity · mode · models · spend · "
        "kill/resume · --json on each"
    ),
    "home.unset": "No workspace here yet: run `unbidden setup` (or `unbidden init` for the defaults).",
    "home.nogit": "`unbidden` works inside a git repository: cd into your project first.",
}


def t(key: str, **kwargs: object) -> str:
    from unbidden.i18n import lookup
    from unbidden.setup import text_es

    return lookup(T, {"es": text_es.T}, key, **kwargs)
