"""The setup assistant: a deterministic walk over the existing mechanisms. Every answer is kept in
`.unbidden/setup.json` so an interrupted setup resumes; nothing is written to the mandate until the summary is
confirmed, and the write validates first. The scripted form (`--non-interactive`) takes the same answers from flags.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.prompt import Confirm, Prompt

from unbidden.contracts.guardian import Mandate
from unbidden.guardian.credentials import broker
from unbidden.guardian.mandate_edit import (
    MODES,
    apply_autonomy,
    apply_mode,
    apply_model_option,
    apply_models,
    autonomous_blockers,
    current_mode,
    read_raw,
    validate,
    write_mandate,
)
from unbidden.setup import machine
from unbidden.setup.effective import effective_permissions, render
from unbidden.setup.text import t
from unbidden.store import Store
from unbidden.workspace import Workspace, head_sha

SECTIONS = ("project", "priorities", "models", "credentials", "autonomy", "connections", "budget", "dashboard")
ModelOption = Literal["local", "mixed", "api"]
Mode = Literal["supervised", "autopilot", "autonomous"]
DashboardChoice = Literal["now", "later", "never"]


class SetupError(RuntimeError):
    """A scripted setup lacks an answer, or an answer is not one of the choices."""


@dataclass
class Options:
    non_interactive: bool = False
    yes: bool = False
    section: str | None = None  # redo one section
    redo_all: bool = False
    show: bool = False
    models: str | None = None
    private_code: str | None = None
    mode: str | None = None
    act_on_connections: str | None = None
    priorities: list[str] | None = None
    budget: float | None = None
    dashboard: str | None = None
    model_key_stdin: bool = False
    github_token_stdin: bool = False
    credentials_stdin: list[str] = field(default_factory=list)  # names whose values follow on stdin, one per line
    connections: list[str] = field(default_factory=list)  # "id=..,kind=..,location=..[,credential_ref=..,...]"
    pull_model: bool = False
    probe: bool = False
    json: bool = False


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    location: str
    environment: str = "staging"
    credential_ref: str | None = None
    username: str | None = None
    docs: str | None = None
    permissions: list[str] = ["read"]


class Answers(BaseModel):
    """What a person chose; never a credential value."""

    model_config = ConfigDict(extra="forbid")
    version: int = 1
    priorities: list[str] | None = None
    models: ModelOption | None = None
    private_code_to_frontier: Literal["allow", "deny"] | None = None
    credentials_saved: list[str] = []
    probe: dict[str, Any] | None = None
    mode: Mode | None = None
    act_on_connections: Literal["allow", "require_approval", "deny"] | None = None
    connections: list[Connection] = []
    budget_usd: float | None = None
    dashboard: DashboardChoice | None = None
    completed: list[str] = []


def answers_path(ws: Workspace) -> Path:
    return ws.dir / "setup.json"


def load_answers(ws: Workspace) -> Answers:
    path = answers_path(ws)
    if path.exists():
        try:
            return Answers.model_validate_json(path.read_text())
        except ValueError:
            pass
    return Answers()


def save_answers(ws: Workspace, answers: Answers) -> None:
    path = answers_path(ws)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(answers.model_dump_json(indent=2))
    os.replace(tmp, path)


# --- how questions are asked -----------------------------------------------------------------------------------


class IO(Protocol):
    def choice(self, key: str, prompt: str, choices: Sequence[str], default: str | None) -> str: ...
    def text(self, key: str, prompt: str, default: str | None) -> str: ...
    def secret(self, key: str, prompt: str) -> str: ...
    def confirm(self, key: str, prompt: str, default: bool) -> bool: ...


class Interactive:
    def __init__(self, console: Console) -> None:
        self.console = console

    def choice(self, key: str, prompt: str, choices: Sequence[str], default: str | None) -> str:
        return str(Prompt.ask(prompt, choices=list(choices), default=default, console=self.console) or default or "")

    def text(self, key: str, prompt: str, default: str | None) -> str:
        return Prompt.ask(prompt, default=default, console=self.console) or ""

    def secret(self, key: str, prompt: str) -> str:
        return Prompt.ask(prompt, password=True, console=self.console, default="", show_default=False) or ""

    def confirm(self, key: str, prompt: str, default: bool) -> bool:
        return Confirm.ask(prompt, default=default, console=self.console)


class Scripted:
    """Answers from flags; a missing one is an error, never a silent default for what the person must choose."""

    def __init__(self, answers: dict[str, Any], secrets: dict[str, str]) -> None:
        self.answers = answers
        self.secrets = secrets

    def choice(self, key: str, prompt: str, choices: Sequence[str], default: str | None) -> str:
        value = self.answers.get(key, default)
        if value is None:
            raise SetupError(f"--{key.replace('_', '-')} is required in non-interactive mode ({', '.join(choices)})")
        if str(value) not in choices:
            raise SetupError(f"--{key.replace('_', '-')}: {value!r} is not one of {', '.join(choices)}")
        return str(value)

    def text(self, key: str, prompt: str, default: str | None) -> str:
        value = self.answers.get(key, default)
        return "" if value is None else str(value)

    def secret(self, key: str, prompt: str) -> str:
        return self.secrets.get(key, "")

    def confirm(self, key: str, prompt: str, default: bool) -> bool:
        return bool(self.answers.get(key, default))


def read_stdin_secrets(names: Sequence[str]) -> dict[str, str]:
    """One value per line, in the order the names were given; empty lines skip a name."""
    out: dict[str, str] = {}
    for name in names:
        line = sys.stdin.readline()
        value = line.rstrip("\n")
        if value:
            out[name] = value
    return out


# --- the walk ----------------------------------------------------------------------------------------------------

Probe = Callable[[Workspace], dict[str, Any]]


@dataclass
class Context:
    ws: Workspace
    store: Store
    raw: dict[str, Any]
    answers: Answers
    io: IO
    out: Console
    opts: Options
    probe: Probe
    notes: list[str] = field(default_factory=list)

    @property
    def body(self) -> dict[str, Any]:
        return self.raw["mandate"]

    def say(self, text: str) -> None:
        self.out.print(text)

    def title(self, key: str) -> None:
        self.out.print(f"\n[bold]{t(key)}[/]")


def step_project(ctx: Context) -> None:
    ctx.title("project.title")
    ws = ctx.ws
    branch = _branch(ws.repo)
    ctx.say(t("project.repo", repo=ws.repo, branch=branch, head=head_sha(ws.repo)[:12]))
    try:
        from unbidden.observe.scope import diagnose

        for name, ok, note in diagnose(ws.repo):
            ctx.say(f"  {name:14} {t('project.scope.ok') if ok else t('project.scope.no')}: {note}")
    except Exception as exc:  # the diagnosis is information; its failure is not a block
        ctx.say(f"  scope: not diagnosed ({type(exc).__name__})")
    if not ctx.opts.non_interactive and not ctx.io.confirm("project", t("project.confirm"), True):
        raise SetupError("setup cancelled")


def step_priorities(ctx: Context) -> None:
    ctx.title("priorities.title")
    current = ctx.answers.priorities or list(ctx.body.get("priorities") or [])
    if ctx.opts.priorities is not None:
        chosen = ctx.opts.priorities
    else:
        text = ctx.io.text("priorities", t("priorities.ask"), ", ".join(current))
        chosen = [p.strip() for p in text.split(",") if p.strip()] or current
    ctx.answers.priorities = chosen
    ctx.body["priorities"] = chosen


def step_models(ctx: Context) -> None:
    from unbidden.brain.hardware import detect, recommend
    from unbidden.runtime import installed_models

    ctx.title("models.title")
    ctx.say(t("models.explain"))
    for option in ("local", "mixed", "api"):
        ctx.say(f"  {t('models.' + option)}")
    machine_ = detect()
    config = ctx.ws.config() if ctx.ws.initialized else None
    ollama_url = config.providers["ollama"].base_url if config and "ollama" in config.providers else None
    installed = installed_models(ollama_url) if ollama_url else set()
    rec = recommend(machine_, installed)
    ctx.say(t("models.hardware", chip=machine_.chip, total=machine_.total_gb, budget=machine_.model_budget_gb))
    ctx.say(
        t(
            "models.local_model",
            tag=rec.model.tag,
            reason=rec.reason,
            installed="" if rec.installed else t("models.not_installed"),
        )
    )
    key_present = broker().has("MODEL_API_KEY") or "MODEL_API_KEY" in machine.read_env(machine.machine_env())
    if key_present and installed:
        ctx.say(t("models.recommend", option="mixed", why="a key and a local model are both available"))
    elif key_present:
        ctx.say(t("models.recommend", option="api", why="a key is available and no local model is installed"))
    elif installed:
        ctx.say(t("models.recommend", option="local", why="a local model is installed and no key is saved"))
    default = ctx.answers.models
    option = ctx.io.choice("models", t("models.ask"), ("local", "mixed", "api"), default)
    ctx.answers.models = option  # type: ignore[assignment]
    if option != "api" and not rec.installed and rec.fits:
        pull = (
            ctx.opts.pull_model
            if ctx.opts.non_interactive
            else ctx.io.confirm("pull_model", t("models.pull.ask", tag=rec.model.tag, gb=rec.model.loaded_gb), False)
        )
        if pull:
            import subprocess

            ctx.say(f"ollama pull {rec.model.tag} ...")
            subprocess.run(["ollama", "pull", rec.model.tag], check=False)
        else:
            ctx.say(t("models.pull.skip"))
    private_default = ctx.answers.private_code_to_frontier or str(
        ctx.body.get("models", {}).get("private_code_to_frontier", "deny")
    )
    private = "deny"
    if option != "local":
        private = ctx.io.choice("private_code", t("models.private_code.ask"), ("deny", "allow"), private_default)
    ctx.answers.private_code_to_frontier = private  # type: ignore[assignment]
    apply_model_option(ctx.raw, option)
    apply_models(ctx.raw, private_code_to_frontier=private)


def step_credentials(ctx: Context) -> None:
    ctx.title("credentials.title")
    env_path = machine.machine_env()
    ctx.say(t("credentials.where", path=env_path))
    saved: list[str] = []
    needs_key = ctx.answers.models in ("mixed", "api")
    if needs_key:
        if _credential(ctx, "MODEL_API_KEY", env_path, stdin_flag=ctx.opts.model_key_stdin):
            saved.append("MODEL_API_KEY")
        if broker().has("MODEL_API_KEY"):
            broker().grant("MODEL_API_KEY", "model.remote")
            from unbidden.cli import meta_api_status

            ok, detail = meta_api_status(True)
            ctx.say(t("credentials.listing", detail=detail))
            if not ok and "refuses" in detail:
                ctx.say(t("credentials.listing.note"))
            _offer_probe(ctx)
        elif ctx.answers.models == "api":
            ctx.say(t("credentials.skipped", name="MODEL_API_KEY"))
    wants_github = ctx.opts.github_token_stdin or (
        not ctx.opts.non_interactive
        and ctx.io.confirm("github", t("credentials.github.ask"), broker().has("GITHUB_TOKEN"))
    )
    if wants_github and _credential(ctx, "GITHUB_TOKEN", env_path, stdin_flag=ctx.opts.github_token_stdin):
        saved.append("GITHUB_TOKEN")
    for name in saved:
        if name not in ctx.answers.credentials_saved:
            ctx.answers.credentials_saved.append(name)


def _credential(ctx: Context, name: str, env_path: Path, *, stdin_flag: bool) -> bool:
    """Ask for one credential and save it by name. Returns True when a value was saved now."""
    present = name in machine.read_env(env_path) or broker().has(name)
    if ctx.opts.non_interactive:
        value = ctx.io.secret(name, "") if stdin_flag else ""
    else:
        if present and ctx.io.confirm(f"keep_{name}", t("credentials.have", name=name), True):
            return False
        value = ctx.io.secret(name, t("credentials.ask", name=name))
    if not value:
        return False
    machine.write_env(env_path, {name: value})
    broker().hold(name, value)
    ctx.say(t("credentials.saved", name=name))
    return True


def _offer_probe(ctx: Context) -> None:
    from unbidden.brain.spend import worst_cost
    from unbidden.contracts.llm import Tier

    config = ctx.ws.config()
    route = config.routing.get(Tier.CODE)
    price = config.prices.models.get(route.model) if route else None
    cost = worst_cost(400, 16, price.input_per_mtok, price.output_per_mtok) if price else 0.01
    wanted = (
        ctx.opts.probe
        if ctx.opts.non_interactive
        else ctx.io.confirm("probe", t("credentials.probe.ask", cost=cost), False)
    )
    if not wanted:
        ctx.say(t("credentials.probe.skip"))
        return
    result = ctx.probe(ctx.ws)
    ctx.answers.probe = result
    if result.get("ok"):
        ctx.say(t("credentials.probe.ok", model=result.get("model"), usd=result.get("usd", 0.0)))
    else:
        ctx.say(t("credentials.probe.fail", why=result.get("why")))


def probe_remote(ws: Workspace) -> dict[str, Any]:
    """One short call through the Brain where heavy work would go: the same policy, egress gate and ledger as any
    other call. Never run unless a person asked for it."""
    from unbidden.brain.router import Brain, BrainError
    from unbidden.contracts.llm import LLMRequest, Message, Tier
    from unbidden.runtime import _grant_model_keys, build_providers

    ws.load_env()
    config = ws.config()
    store = ws.store()
    _grant_model_keys(config, store)
    brain = Brain(config, build_providers(config), store, ws.mandate(), killswitch=ws.killswitch())
    request = LLMRequest(
        purpose="setup.probe",
        tier=Tier.CODE,
        messages=[
            Message(role="system", content="You are a connectivity check.", source="prompt"),
            Message(role="user", content="Reply with the single word OK.", source="prompt"),
        ],
        max_tokens=16,
    )
    try:
        response = asyncio.run(brain.complete(request))
    except BrainError as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # a provider error is reported, never raised at the person
        return {"ok": False, "why": f"{type(exc).__name__}: {str(exc)[:200]}"}
    run = brain.served_by.get("setup.probe")
    return {
        "ok": True,
        "model": run.model if run else None,
        "usd": round(run.cost.usd_remote, 6) if run else 0.0,
        "answer": (response.content or "")[:40],
    }


def step_autonomy(ctx: Context) -> None:
    ctx.title("autonomy.title")
    ctx.say(t("autonomy.explain"))
    for mode in ("supervised", "autopilot", "autonomous"):
        ctx.say(f"  {t('autonomy.' + mode)}")
    default = ctx.answers.mode or current_mode(ctx.body.get("autonomy") or {})
    if default not in MODES:
        default = "supervised"
    mode = ctx.io.choice("mode", t("autonomy.ask"), ("supervised", "autopilot", "autonomous"), default)
    if mode == "autonomous":
        blockers = autonomous_blockers(ctx.raw, ctx.store)
        if blockers:
            ctx.say(t("autonomy.blocked"))
            for why in blockers:
                ctx.say(f"  - {why}")
            ctx.notes.extend(blockers)
            fallback = (
                "autopilot"
                if ctx.opts.non_interactive
                else ctx.io.choice("mode_fallback", t("autonomy.fallback"), ("supervised", "autopilot"), "autopilot")
            )
            mode = fallback
    ctx.answers.mode = mode  # type: ignore[assignment]
    apply_mode(ctx.raw, mode)
    current = str((ctx.body.get("autonomy") or {}).get("act_on_connections", "deny"))
    writes = ctx.io.choice(
        "act_on_connections", t("autonomy.connections.ask"), ("deny", "require_approval", "allow"),
        ctx.answers.act_on_connections or current,
    )  # fmt: skip
    ctx.answers.act_on_connections = writes  # type: ignore[assignment]
    apply_autonomy(ctx.raw, act_on_connections=writes)
    ctx.say(t("autonomy.effective"))
    for line in render(effective_permissions(validate(ctx.raw))):
        ctx.say(line)


def step_connections(ctx: Context) -> None:
    ctx.title("connections.title")
    specs: list[Connection] = []
    if ctx.opts.non_interactive:
        for spec in ctx.opts.connections:
            fields = dict(part.split("=", 1) for part in spec.split(",") if "=" in part)
            if "permissions" in fields:
                fields["permissions"] = fields["permissions"].split("+")  # type: ignore[assignment]
            specs.append(Connection.model_validate(fields))
    else:
        while True:
            kind = ctx.io.choice("connection_kind", t("connections.ask"), ("none", "postgres", "http_api"), "none")
            if kind == "none":
                break
            spec = Connection(
                id=ctx.io.text("connection_id", t("connections.id"), None),
                kind=kind,
                location=ctx.io.text("connection_location", t("connections.location"), None),
                environment=ctx.io.text("connection_environment", t("connections.environment"), "staging") or "staging",
            )
            if kind == "postgres":
                spec.username = ctx.io.text("connection_username", t("connections.username"), None) or None
            else:
                spec.docs = ctx.io.text("connection_docs", t("connections.docs"), None) or None
            ref = ctx.io.text("connection_credential", t("connections.credential"), None) or None
            spec.credential_ref = ref
            if ref:
                value = ctx.io.secret(ref, t("credentials.ask", name=ref))
                if value:
                    machine.write_env(ctx.ws.dir / ".env", {ref: value})
                    broker().hold(ref, value)
                    ctx.say(t("credentials.saved", name=ref))
            specs.append(spec)
    for name in ctx.opts.credentials_stdin:
        value = ctx.io.secret(name, "")
        if value:
            machine.write_env(ctx.ws.dir / ".env", {name: value})
            broker().hold(name, value)
            ctx.say(t("credentials.saved", name=name))
    if specs:
        existing: list[dict[str, Any]] = list(ctx.body.get("connections") or [])
        by_id = {c.get("id"): c for c in existing}
        for spec in specs:
            by_id[spec.id] = spec.model_dump(exclude_none=True)
        ctx.body["connections"] = list(by_id.values())
        ctx.answers.connections = specs
    validate(ctx.raw)


def step_budget(ctx: Context) -> None:
    from unbidden.brain.spend import SpendLedger

    ctx.title("budget.title")
    ledger = SpendLedger()
    status = ledger.status()
    ctx.say(
        t(
            "budget.ledger",
            reason=status.reason,
            permitted=status.permitted_usd,
            spent=status.spent_usd,
            available=status.available_usd,
        )
    )
    envelopes = ledger.budget().envelopes
    if envelopes:
        ctx.say(t("budget.envelopes", envelopes=", ".join(f"{k} {v:.2f}" for k, v in envelopes.items())))
    ctx.say(t("budget.explain"))
    constraints: dict[str, Any] = ctx.body.setdefault("business_constraints", {})
    current = (
        ctx.answers.budget_usd
        if ctx.answers.budget_usd is not None
        else constraints.get("maximum_monthly_spend_usd", 10)
    )
    if ctx.opts.budget is not None:
        value = float(ctx.opts.budget)
    else:
        text = ctx.io.text("budget", t("budget.ask"), str(current))
        try:
            value = float(text) if text else float(current)
        except ValueError as exc:
            raise SetupError(f"budget must be a number, got {text!r}") from exc
    if value < 0:
        raise SetupError("the monthly cap cannot be negative")
    ctx.answers.budget_usd = value
    constraints["maximum_monthly_spend_usd"] = value


def step_dashboard(ctx: Context) -> None:
    ctx.title("dashboard.title")
    ctx.say(t("dashboard.explain"))
    choice = ctx.io.choice("dashboard", t("dashboard.ask"), ("now", "later", "never"), ctx.answers.dashboard or "later")
    ctx.answers.dashboard = choice  # type: ignore[assignment]
    prefs = machine.load_prefs()
    prefs.dashboard = {"now": "always", "later": "ask", "never": "never"}[choice]  # type: ignore[assignment]
    machine.save_prefs(prefs)


STEPS: dict[str, Callable[[Context], None]] = {
    "project": step_project,
    "priorities": step_priorities,
    "models": step_models,
    "credentials": step_credentials,
    "autonomy": step_autonomy,
    "connections": step_connections,
    "budget": step_budget,
    "dashboard": step_dashboard,
}


def mandate_diff(before: str, after: str, path: Path) -> list[str]:
    return list(difflib.unified_diff(before.splitlines(), after.splitlines(), str(path), str(path), lineterm="", n=2))


def summary(ctx: Context, mandate: Mandate) -> dict[str, Any]:
    models = ctx.body.get("models") or {}
    option = ctx.answers.models or _option_of(models)
    dashboard = (
        ctx.answers.dashboard or {"always": "now", "ask": "later", "never": "never"}[machine.load_prefs().dashboard]
    )
    return {
        "models": option,
        "profile": models.get("profile"),
        "private_code_to_frontier": models.get("private_code_to_frontier", "deny"),
        "mode": current_mode(ctx.body.get("autonomy") or {}),
        "act_on_connections": (ctx.body.get("autonomy") or {}).get("act_on_connections", "deny"),
        "budget_usd": (ctx.body.get("business_constraints") or {}).get("maximum_monthly_spend_usd"),
        "credentials_saved": list(ctx.answers.credentials_saved),
        "credential_names_present": machine.env_names(machine.machine_env()),
        "dashboard": dashboard,
        "effective": effective_permissions(mandate),
        "notes": list(ctx.notes),
        "probe": ctx.answers.probe,
    }


def _option_of(models: dict[str, Any]) -> str:
    """The option a models policy amounts to (for a mandate written by hand or an earlier version)."""
    profile = models.get("profile", "local-first")
    if profile == "frontier" and models.get("local_inference") == "deny":
        return "api"
    return {"local": "local", "local-first": "mixed"}.get(profile, "custom")


def show_summary(ctx: Context, data: dict[str, Any]) -> None:
    ctx.title("summary.title")
    ctx.say(
        t("summary.models", option=data["models"], profile=data["profile"], private=data["private_code_to_frontier"])
    )
    ctx.say(t("summary.mode", mode=data["mode"], connections=data["act_on_connections"]))
    ctx.say(t("summary.budget", budget=float(data["budget_usd"] or 0)))
    ctx.say(t("summary.credentials", names=", ".join(data["credential_names_present"]) or "none"))
    ctx.say(t("summary.dashboard", choice=data["dashboard"]))
    ctx.say(t("autonomy.effective"))
    for line in render(data["effective"]):
        ctx.say(line)
    for note in data["notes"]:
        ctx.say(f"  note: {note}")


def run(ws: Workspace, opts: Options, out: Console, *, probe: Probe = probe_remote, io: IO | None = None) -> int:
    """Walk the sections (or one), show the summary and the diff, write once. Exit 0 written, 3 nothing written."""
    created = ws.init()
    store = ws.store()
    raw = read_raw(ws.mandate_path)
    before_text = ws.mandate_path.read_text()
    answers = load_answers(ws)
    if opts.show:
        data = summary(Context(ws, store, raw, answers, io or Interactive(out), out, opts, probe), validate(raw))
        if opts.json:
            print(json.dumps(data, indent=2, default=str))
        else:
            show_summary(Context(ws, store, raw, answers, io or Interactive(out), out, opts, probe), data)
        return 0
    if io is None:
        if opts.non_interactive:
            scripted = {
                "models": opts.models, "private_code": opts.private_code, "mode": opts.mode,
                "act_on_connections": opts.act_on_connections, "dashboard": opts.dashboard,
            }  # fmt: skip
            names = (
                (["MODEL_API_KEY"] if opts.model_key_stdin else [])
                + (["GITHUB_TOKEN"] if opts.github_token_stdin else [])
                + list(opts.credentials_stdin)
            )
            io = Scripted({k: v for k, v in scripted.items() if v is not None}, read_stdin_secrets(names))
        else:
            io = Interactive(out)
    ctx = Context(ws, store, raw, answers, io, out, opts, probe)
    if created:
        ctx.say(t("welcome"))
    elif answers.completed and not opts.section and not opts.redo_all:
        ctx.say(t("resume", done=", ".join(answers.completed)))
    if opts.non_interactive:
        opts.redo_all = True  # the flags are the whole specification; resuming is for the interactive walk
    sections = [opts.section] if opts.section else list(SECTIONS)
    if opts.section and opts.section not in STEPS:
        raise SetupError(f"unknown section {opts.section!r}; one of {', '.join(SECTIONS)}")
    try:
        for name in sections:
            if not opts.section and not opts.redo_all and name in answers.completed:
                continue
            STEPS[name](ctx)
            if name not in answers.completed:
                answers.completed.append(name)
            save_answers(ws, answers)
    except SetupError as exc:
        save_answers(ws, answers)
        out.print(f"[yellow]{exc}[/]")
        out.print(t("summary.cancelled", path=answers_path(ws)))
        return 2
    mandate = validate(raw)
    data = summary(ctx, mandate)
    after_text = yaml.safe_dump(raw, sort_keys=False)
    diff = mandate_diff(before_text, after_text, ws.mandate_path)
    if not opts.json:
        show_summary(ctx, data)
        if diff:
            ctx.say(t("summary.diff", path=ws.mandate_path))
            for line in diff:
                color = "green" if line.startswith("+") else "red" if line.startswith("-") else "dim"
                ctx.out.print(f"[{color}]{line}[/]", soft_wrap=True, highlight=False, markup=True)
        else:
            ctx.say(t("summary.nodiff"))
    apply = opts.yes if opts.non_interactive or opts.yes else io.confirm("apply", t("summary.apply"), True)
    if not apply:
        if opts.json:
            print(json.dumps({**data, "diff": diff, "applied": False}, indent=2, default=str))
        else:
            ctx.say(t("summary.dry") if opts.non_interactive else t("summary.cancelled", path=answers_path(ws)))
        return 3
    payload = {
        "setup": {
            "sections": sections,
            "models": data["models"],
            "mode": data["mode"],
            "act_on_connections": data["act_on_connections"],
            "budget_usd": data["budget_usd"],
            "credentials": data["credentials_saved"],  # names only
        }
    }
    write_mandate(ws.mandate_path, raw, store, payload)
    answers_path(ws).unlink(missing_ok=True)
    if opts.json:
        print(
            json.dumps({**data, "diff": diff, "applied": True, "mandate": str(ws.mandate_path)}, indent=2, default=str)
        )
        return 0
    ctx.say(t("summary.written"))
    ctx.title("next.title")
    for key in ("next.scan", "next.doctor", "next.home"):
        ctx.say(f"  {t(key)}")
    if data["dashboard"] == "now":
        ctx.say(f"  {t('next.ui')}")
    return 0


def _branch(repo: Path) -> str:
    import subprocess

    out = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip() or "(detached)"
