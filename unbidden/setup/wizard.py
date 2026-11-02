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
import threading
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
from unbidden.setup.discover import Found, discover
from unbidden.setup.effective import effective_permissions, render
from unbidden.setup.text import t
from unbidden.store import Store
from unbidden.workspace import Workspace

# The walk asks three things at most: the model key when none is found, how much Unbidden may do on its own, and
# whether to apply. Everything else is found or has a default shown in the summary; the advanced sections run only
# by name (`unbidden setup budget`, `/setup connections`) or with --all.
SECTIONS = ("found", "models", "autonomy")
ADVANCED = ("priorities", "credentials", "connections", "budget", "dashboard", "private_code", "language")
ALL = SECTIONS + ADVANCED
OLD_NAMES = {"project": "found"}  # a setup.json written by 0.10
ModelOption = Literal["local", "mixed", "api"]
Mode = Literal["supervised", "autopilot", "autonomous"]
DashboardChoice = Literal["now", "later", "never"]


class SetupError(RuntimeError):
    """A scripted setup lacks an answer, or an answer is not one of the choices."""


class SetupBlocked(SetupError):
    """The mode asked for cannot be switched on and no other mode was chosen explicitly: nothing is written."""

    def __init__(self, mode: str, blockers: list[str]) -> None:
        super().__init__(t("autonomy.blocked.result", mode=mode))
        self.mode = mode
        self.blockers = blockers


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
    mode_fallback: str | None = None  # the mode to take when `mode` cannot be switched on; never chosen for the person
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
    found: dict[str, Any] | None = None  # what the found block saw, as data
    github_source: str | None = None  # file, env, gh, browser, token; None when none
    defaulted: list[str] = []  # sections never asked in this walk: their defaults were kept


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


NO_TTY = "no terminal to answer from: run `unbidden setup --non-interactive --models ... --mode ... --yes` instead"


class Interactive:
    def __init__(self, console: Console) -> None:
        self.console = console

    def choice(self, key: str, prompt: str, choices: Sequence[str], default: str | None) -> str:
        try:
            if default is None:  # no default: an empty answer asks again, the person must choose
                return str(Prompt.ask(prompt, choices=list(choices), console=self.console))
            return str(
                Prompt.ask(prompt, choices=list(choices), default=default, console=self.console) or default or ""
            )
        except EOFError as exc:
            raise SetupError(NO_TTY) from exc

    def text(self, key: str, prompt: str, default: str | None) -> str:
        try:
            return Prompt.ask(prompt, default=default, console=self.console) or ""
        except EOFError as exc:
            raise SetupError(NO_TTY) from exc

    def secret(self, key: str, prompt: str) -> str:
        try:
            return Prompt.ask(prompt, password=True, console=self.console, default="", show_default=False) or ""
        except EOFError as exc:
            raise SetupError(NO_TTY) from exc

    def confirm(self, key: str, prompt: str, default: bool) -> bool:
        try:
            return Confirm.ask(prompt, default=default, console=self.console)
        except EOFError as exc:
            raise SetupError(NO_TTY) from exc


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
Pull = Callable[[str, Callable[[str], None]], bool]  # download a local model, narrating through `say`


def pull_model(tag: str, say: Callable[[str], None]) -> bool:
    """`ollama pull` in the terminal the assistant runs in; the app passes its own that streams into its log."""
    import subprocess

    say(f"ollama pull {tag} ...")
    return subprocess.run(["ollama", "pull", tag], check=False).returncode == 0


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
    pull: Pull = pull_model
    found: Found | None = None
    cancel: threading.Event = field(default_factory=threading.Event)  # set by Ctrl+C while a wait cannot ask

    @property
    def body(self) -> dict[str, Any]:
        return self.raw["mandate"]

    def facts(self) -> Found:
        if self.found is None:
            self.found = discover(self.ws)
        return self.found

    def say(self, text: str) -> None:
        self.out.print(text)

    def title(self, key: str) -> None:
        self.out.print(f"\n[bold]{t(key)}[/]")


def step_found(ctx: Context) -> None:
    """Facts, no question: the repository and its remote, GitHub access, the scope, the connections the compose
    files declare, the machine and its models, the option those facts amount to."""
    ctx.title("found.title")
    found = ctx.facts()
    where = found.slug or found.name
    if found.head is None:
        ctx.say(t("found.repo.nocommit", repo=where, branch=found.branch))
    else:
        ctx.say(t("found.repo", repo=where, branch=found.branch, head=found.head[:12]))
    if found.slug is None:
        ctx.say(t("found.noremote"))
    for name, ok, note in found.scope:
        ctx.say(f"  {name:14} {t('found.scope.ok') if ok else t('found.scope.no')}: {note}")
    if found.compose_path:
        items = [f"{kind} {name} ({t('found.compose')})" for name, kind in found.services if kind]
        items += [f"{kind} {location} ({t('found.notgranted')})" for kind, location, _ in found.external]
        listed = ", ".join(items) or t("found.connections.none")
        ctx.say(t("found.connections", path=found.compose_path, items=listed))
    else:
        ctx.say(t("found.connections.nocompose"))
    ctx.say(t("models.hardware", described=found.machine.describe))
    rec = found.recommendation
    installed = "" if rec.installed else t("models.not_installed")
    ctx.say(t("models.local_model", tag=rec.model.tag, reason=rec.reason, installed=installed))
    state = t("found.key.present") if found.key_present else t("found.key.absent")
    ctx.say(t("found.key", name=found.key_env, state=state))
    _github_access(ctx, found)
    from unbidden import i18n

    ctx.say(t("found.language", name=i18n.name(), how=t(f"lang.how.{i18n.source()}")))
    ctx.answers.found = found.as_dict()


def _github_access(ctx: Context, found: Found) -> None:
    """Where the GitHub token comes from; when nowhere, one menu: sign in through the browser, paste, or skip."""
    from unbidden.setup import github_device

    source = found.github.source
    if source is not None:
        ctx.say(t("found.github", source=t(f"found.github.{source}")))
        ctx.answers.github_source = source
        return
    ctx.say(t("found.github", source=t("found.github.none")))
    if ctx.opts.non_interactive:
        return  # --github-token-stdin runs through the credentials section
    choices = (["browser"] if github_device.available() else []) + ["token", "skip"]
    pick = ctx.io.choice("github_access", t("github.ask"), choices, "browser" if choices[0] == "browser" else "skip")
    ctx.say(f"  {t('github.' + pick)}")
    env_path = machine.machine_env()
    if pick == "browser":
        token = github_device.sign_in(say=ctx.say, cancel=ctx.cancel)
        if token:
            machine.write_env(env_path, {"GITHUB_TOKEN": token})
            broker().hold("GITHUB_TOKEN", token)
            broker().grant("GITHUB_TOKEN", "github")
            ctx.say(t("credentials.saved", name="GITHUB_TOKEN"))
            ctx.answers.github_source = "browser"
            if "GITHUB_TOKEN" not in ctx.answers.credentials_saved:
                ctx.answers.credentials_saved.append("GITHUB_TOKEN")
    elif pick == "token" and _credential(ctx, "GITHUB_TOKEN", env_path, stdin_flag=False):
        ctx.answers.github_source = "token"
        if "GITHUB_TOKEN" not in ctx.answers.credentials_saved:
            ctx.answers.credentials_saved.append("GITHUB_TOKEN")


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
    """The option follows from what the machine has; the only question is the key, when none is found."""
    ctx.title("models.title")
    found = ctx.facts()
    env_path = machine.machine_env()
    key_present = found.key_present
    asks_key = not ctx.opts.non_interactive and not key_present and ctx.opts.models != "local"
    if ctx.opts.model_key_stdin or asks_key:
        if ctx.opts.non_interactive:
            value = ctx.io.secret(found.key_env, "")
        else:
            ctx.say(t("models.key.why"))
            value = ctx.io.secret(found.key_env, t("models.key.ask", name=found.key_env))
        if value:
            machine.write_env(env_path, {found.key_env: value})
            broker().hold(found.key_env, value)
            broker().grant(found.key_env, "model.remote")
            ctx.say(t("credentials.saved", name=found.key_env))
            key_present = True
            if found.key_env not in ctx.answers.credentials_saved:
                ctx.answers.credentials_saved.append(found.key_env)
            from unbidden.cli import meta_api_status

            ok, detail = meta_api_status(True)
            ctx.say(t("credentials.listing", detail=detail))
            if not ok and "refuses" in detail:
                ctx.say(t("credentials.listing.note"))
        else:
            ctx.say(t("models.key.skipped"))
    found.key_present = key_present
    if ctx.opts.models is not None:
        option, why = ctx.opts.models, "models.why.flag"
    else:
        option, why = found.option()
    ctx.say(t("models.chosen", option=option, why=t(why)))
    if option == "local" and not found.local_model and not found.ollama_present:
        ctx.say(t("models.none"))
        ctx.notes.append(t("models.none"))
    ctx.answers.models = option  # type: ignore[assignment]
    rec = found.recommendation
    if option != "api" and not rec.installed and rec.fits and found.ollama_present:
        pull = (
            ctx.opts.pull_model
            if ctx.opts.non_interactive
            else ctx.io.confirm("pull_model", t("models.pull.ask", tag=rec.model.tag, gb=rec.model.loaded_gb), True)
        )
        if pull:
            ctx.pull(rec.model.tag, ctx.say)
        else:
            ctx.say(t("models.pull.skip"))
    private = (
        ctx.opts.private_code
        or ctx.answers.private_code_to_frontier
        or str(ctx.body.get("models", {}).get("private_code_to_frontier", "deny"))
    )
    if option == "local":
        private = "deny"
    ctx.answers.private_code_to_frontier = private  # type: ignore[assignment]
    apply_model_option(ctx.raw, option)
    apply_models(ctx.raw, private_code_to_frontier=private)
    if ctx.opts.probe and key_present:
        _offer_probe(ctx)


def step_language(ctx: Context) -> None:
    from unbidden import i18n

    ctx.title("language.title")
    code = ctx.io.choice("language", t("language.ask"), tuple(i18n.LANGUAGES), i18n.language())
    i18n.set_language(code)
    ctx.say(t("found.language", name=i18n.name(), how=t("lang.how.saved")))


def step_private_code(ctx: Context) -> None:
    ctx.title("private_code.title")
    current = ctx.answers.private_code_to_frontier or str(
        ctx.body.get("models", {}).get("private_code_to_frontier", "deny")
    )
    private = ctx.opts.private_code or ctx.io.choice(
        "private_code", t("models.private_code.ask"), ("deny", "allow"), current
    )
    ctx.answers.private_code_to_frontier = private  # type: ignore[assignment]
    apply_models(ctx.raw, private_code_to_frontier=private)


def step_credentials(ctx: Context) -> None:
    ctx.title("credentials.title")
    env_path = machine.machine_env()
    ctx.say(t("credentials.where", path=env_path))
    saved: list[str] = []
    needs_key = (ctx.answers.models or _option_of(ctx.body.get("models") or {})) in ("mixed", "api")
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

    async def once() -> Any:
        try:
            return await brain.complete(request)
        finally:
            await brain.aclose()

    try:
        response = asyncio.run(once())
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
    default = ctx.opts.mode or ctx.answers.mode or current_mode(ctx.body.get("autonomy") or {})
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
            # Nobody chooses the other mode for the person: scripted, --mode-fallback names it or the setup stops
            # with the previous configuration intact (--yes only confirms the write, never a mode); interactive,
            # the question has no default.
            if ctx.opts.non_interactive:
                if ctx.opts.mode_fallback is None:
                    raise SetupBlocked(mode, blockers)
                mode = ctx.io.choice("mode_fallback", t("autonomy.fallback"), ("supervised", "autopilot"), None)
            else:
                mode = ctx.io.choice("mode_fallback", t("autonomy.fallback"), ("supervised", "autopilot"), None)
            ctx.say(t("autonomy.fallback.chosen", mode=mode))
    ctx.answers.mode = mode  # type: ignore[assignment]
    apply_mode(ctx.raw, mode)
    current = str((ctx.body.get("autonomy") or {}).get("act_on_connections", "deny"))
    writes = ctx.opts.act_on_connections or ctx.answers.act_on_connections or current  # asked only by a grant
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
        found = ctx.facts()
        known = {f"{kind} {location}": (kind, location) for kind, location, _ in found.external}
        while True:
            choices = ["none", *known, "postgres", "http_api"]
            pick = ctx.io.choice("connection_kind", t("connections.ask"), choices, "none")
            if pick == "none":
                break
            kind, location = known.get(pick, (pick, None))
            if location is not None:
                ctx.say(t("connections.prefilled", kind=kind, location=location))
            host = (location or "").split("://")[-1].split(":")[0]
            default_env = "development" if host in ("127.0.0.1", "localhost") else "staging"
            default_id = (location or "").rsplit("/", 1)[-1].replace(":", "-") or None
            spec = Connection(
                id=ctx.io.text("connection_id", t("connections.id"), default_id) or default_id or kind,
                kind=kind,
                location=location or ctx.io.text("connection_location", t("connections.location"), None),
                environment=ctx.io.text("connection_environment", t("connections.environment"), default_env)
                or default_env,
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
        if any(p.startswith("write") for spec in specs for p in spec.permissions):
            current = str((ctx.body.get("autonomy") or {}).get("act_on_connections", "deny"))
            writes = ctx.io.choice(
                "act_on_connections", t("autonomy.connections.ask"), ("deny", "require_approval", "allow"),
                ctx.opts.act_on_connections or current,
            )  # fmt: skip
            ctx.answers.act_on_connections = writes  # type: ignore[assignment]
            apply_autonomy(ctx.raw, act_on_connections=writes)
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
    "found": step_found,
    "models": step_models,
    "autonomy": step_autonomy,
    "priorities": step_priorities,
    "credentials": step_credentials,
    "connections": step_connections,
    "budget": step_budget,
    "dashboard": step_dashboard,
    "private_code": step_private_code,
    "language": step_language,
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
        "priorities": list(ctx.body.get("priorities") or []),
        "github": ctx.answers.github_source,
        "found": ctx.answers.found,
        "defaulted": list(ctx.answers.defaulted),
    }


def _option_of(models: dict[str, Any]) -> str:
    """The option a models policy amounts to (for a mandate written by hand or an earlier version)."""
    from unbidden.setup.requirements import option_of

    return option_of(models)


def show_summary(ctx: Context, data: dict[str, Any]) -> None:
    ctx.title("summary.title")
    ctx.say(
        t("summary.models", option=data["models"], profile=data["profile"], private=data["private_code_to_frontier"])
    )
    ctx.say(t("summary.mode", mode=data["mode"], connections=data["act_on_connections"]))
    ctx.say(t("summary.budget", budget=float(data["budget_usd"] or 0)))
    ctx.say(t("summary.credentials", names=", ".join(data["credential_names_present"]) or "none"))
    github = t(f"found.github.{data['github']}") if data.get("github") else t("found.github.none")
    ctx.say(t("summary.github", source=github))
    ctx.say(t("summary.priorities", names=", ".join(data["priorities"]) or "none"))
    ctx.say(t("summary.dashboard", choice=data["dashboard"]))
    if data.get("defaulted"):
        ctx.say(t("summary.defaults", names=", ".join(data["defaulted"])))
    ctx.say(t("autonomy.effective"))
    for line in render(data["effective"]):
        ctx.say(line)
    for note in data["notes"]:
        ctx.say(f"  note: {note}")


def _flagged(opts: Options, section: str) -> bool:
    """An advanced section joins a scripted or default walk when its flags were given."""
    return {
        "priorities": opts.priorities is not None,
        "credentials": opts.github_token_stdin,
        "connections": bool(opts.connections or opts.credentials_stdin),
        "budget": opts.budget is not None,
        "dashboard": opts.dashboard is not None,
        "private_code": opts.private_code is not None,
        "language": False,
    }[section]


def run(
    ws: Workspace,
    opts: Options,
    out: Console,
    *,
    probe: Probe = probe_remote,
    io: IO | None = None,
    pull: Pull = pull_model,
    cancel: threading.Event | None = None,
) -> int:
    """Walk the sections (or one), show the summary and the diff, write once. Exit 0 written, 3 nothing written,
    2 cancelled or an answer missing, 4 the mode asked for is blocked and no other mode was named."""
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
                "mode_fallback": opts.mode_fallback, "act_on_connections": opts.act_on_connections,
                "dashboard": opts.dashboard,
            }  # fmt: skip
            names = (
                (["MODEL_API_KEY"] if opts.model_key_stdin else [])
                + (["GITHUB_TOKEN"] if opts.github_token_stdin else [])
                + list(opts.credentials_stdin)
            )
            io = Scripted({k: v for k, v in scripted.items() if v is not None}, read_stdin_secrets(names))
        else:
            io = Interactive(out)
    ctx = Context(ws, store, raw, answers, io, out, opts, probe, pull=pull, cancel=cancel or threading.Event())
    answers.completed = [OLD_NAMES.get(name, name) for name in answers.completed]
    if created:
        ctx.say(t("welcome"))
    elif answers.completed and not opts.section and not opts.redo_all and not opts.non_interactive:
        ctx.say(t("resume", done=", ".join(answers.completed)))
    if opts.section:
        sections = [opts.section]
    elif opts.redo_all:
        sections = list(ALL)
    else:  # the flags are the whole specification of a scripted walk; the interactive one resumes
        sections = list(SECTIONS) + [name for name in ADVANCED if _flagged(opts, name)]
    if opts.section and opts.section not in STEPS:
        raise SetupError(f"unknown section {opts.section!r}; one of {', '.join(ALL)}")
    answers.defaulted = [name for name in ADVANCED if name not in sections and name not in answers.completed]
    try:
        for name in sections:
            if not opts.section and not opts.redo_all and not opts.non_interactive and name in answers.completed:
                continue
            STEPS[name](ctx)
            if name not in answers.completed:
                answers.completed.append(name)
            save_answers(ws, answers)
    except SetupBlocked as exc:
        save_answers(ws, answers)
        if opts.json:
            print(json.dumps({"applied": False, "blocked": exc.mode, "blockers": exc.blockers,
                              "mandate": str(ws.mandate_path)}, indent=2))  # fmt: skip
        else:
            out.print(f"[yellow]{exc}[/]")
            for why in exc.blockers:
                out.print(f"  - {why}")
            out.print(t("autonomy.blocked.keep", path=ws.mandate_path))
        return 4
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
