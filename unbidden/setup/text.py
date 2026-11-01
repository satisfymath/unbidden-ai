"""Every sentence the setup assistant and the home screen say, in one place (English first; a translation adds a
table here, not code elsewhere)."""

from __future__ import annotations

T: dict[str, str] = {
    "welcome": "Unbidden is not set up in this repository yet. This takes a few minutes and calls no model.",
    "resume": "Picking up where setup stopped ({done}); answered sections are kept; `setup --all` redoes them.",
    "project.title": "Project",
    "project.repo": "repository {repo} · branch {branch} · head {head}",
    "project.scope.ok": "in scope",
    "project.scope.no": "outside what this version supports",
    "project.confirm": "Set up Unbidden here?",
    "priorities.title": "Priorities",
    "priorities.ask": "What should it look for first? (comma-separated; e.g. correctness, performance, consistency)",
    "models.title": "Models",
    "models.explain": (
        "Where model calls may go. In every option secrets and production data stay on this machine, private code "
        "leaves only renamed by the privacy bridge or when you allow it, and the egress gate re-checks every payload."
    ),
    "models.local": "local: only a model on this machine (Ollama). Nothing leaves. Heavy work is slower and smaller.",
    "models.mixed": (
        "mixed: local first; heavy tasks whose content may leave go to Meta's API first and fall back to the "
        "local model when the remote call fails."
    ),
    "models.api": (
        "api: Meta's API only. No local model is needed or used (local inference and local fallback denied). A call "
        "that may not leave the machine is refused and says why."
    ),
    "models.ask": "Which option?",
    "models.recommend": "Recommended here: {option} ({why}). Nothing is chosen for you.",
    "models.hardware": "machine: {chip}, {total:.0f} GB, {budget:.0f} GB usable for a model",
    "models.local_model": "local model for this machine: {tag} ({reason}){installed}",
    "models.not_installed": " · not installed",
    "models.pull.ask": "Download {tag} now? About {gb:.0f} GB on disk and in memory while it runs.",
    "models.pull.skip": "Not downloaded. Later: `unbidden doctor --fix`.",
    "models.private_code.ask": "May private code reach Meta's API un-renamed? (deny keeps it behind the bridge)",
    "credentials.title": "Credentials",
    "credentials.where": "Saved to {path} (mode 600), referenced by name; never written to the repository or logs.",
    "credentials.have": "{name} is already saved. Keep it?",
    "credentials.ask": "{name} (hidden; leave empty to skip)",
    "credentials.saved": "{name} saved.",
    "credentials.skipped": "{name} not set: remote calls are refused until you add it (`unbidden setup credentials`).",
    "credentials.listing": "Meta API: {detail}",
    "credentials.listing.note": (
        "A refused model listing does not mean inference fails (seen 2026-10-29: /models answered 401 while calls "
        "worked). The optional paid test below tells them apart."
    ),
    "credentials.probe.ask": "Run one paid inference call to confirm the key? At most US${cost:.4f} at list price.",
    "credentials.probe.ok": "Inference works: {model} answered; cost US${usd:.4f} recorded in the ledger.",
    "credentials.probe.fail": "Inference did not work: {why}",
    "credentials.probe.skip": "Skipped. The configuration is saved either way.",
    "credentials.github.ask": "Should Unbidden be able to publish pull requests? (needs GITHUB_TOKEN)",
    "autonomy.title": "Autonomy and scope",
    "autonomy.explain": (
        "A mode sets what reaches GitHub and production. The other permissions are granted on their own and never "
        "inherited from another project. A credential's own powers never widen the mandate."
    ),
    "autonomy.supervised": "supervised: prepares everything, asks before a pull request; never merges or deploys",
    "autonomy.autopilot": "autopilot: opens pull requests on its own for proven work; people merge",
    "autonomy.autonomous": "autonomous: also merges L4 work, deploys with the team's steps and rolls back",
    "autonomy.ask": "Which mode?",
    "autonomy.blocked": "autonomous is not available yet:",
    "autonomy.fallback": "Which mode until then?",
    "autonomy.connections.ask": "May it write through connections (typed, limited, undoable actions)?",
    "autonomy.effective": "Effective permissions",
    "connections.title": "Connections (optional)",
    "connections.ask": "Add a connection? (postgres, http_api, none)",
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
    "summary.title": "Summary",
    "summary.models": "models: {option} (profile {profile}, private code to frontier: {private})",
    "summary.mode": "mode: {mode} · writes through connections: {connections}",
    "summary.budget": "monthly cap: US${budget:.2f}",
    "summary.credentials": "credentials saved: {names}",
    "summary.dashboard": "dashboard: {choice}",
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
    "home.commands": (
        "commands: setup · doctor · scan · inbox · activity · mode · models · spend · kill/resume · --json on each"
    ),
    "home.unset": "No workspace here yet: run `unbidden setup` (or `unbidden init` for the defaults).",
    "home.nogit": "`unbidden` works inside a git repository: cd into your project first.",
}


def t(key: str, **kwargs: object) -> str:
    return T[key].format(**kwargs) if kwargs else T[key]
