"""Reconnaissance: before the agent runs, every resource of the project is connected, explicitly skipped, or blocked
with a reason, and the person was asked for what only they can give.

In order: the stack (started when it is down, with the person's yes), the map of the running system, each database
(read inside its container; a network grant with a read-only role when a port is published and the person gives one),
GitHub (the access the found block verified becomes a `github` grant, so the connections table says `connected`),
external APIs the compose files name (a credential, or skipped), the deploy procedure found (adopted into
`operations.deploy_steps`) and the rollback drill. What was found and decided is kept in the store under `recon`,
with `complete` saying whether the agent can rely on it; `start` warns when it never ran and refuses an autonomous
start on an incomplete one."""

from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from unbidden.setup.text import t

if TYPE_CHECKING:
    from unbidden.setup.wizard import Context

KEY = "recon"
UP = ["docker", "compose", "up", "-d", "--wait"]


@dataclass
class Recon:
    rev: str | None
    at: str
    stack: str = "unknown"  # running | started | down | failed | absent | skipped
    resources: int = 0
    blind_spots: list[str] | None = None
    databases: dict[str, str] | None = None  # service -> container | granted | unread | skipped | grant_failed
    github: str = "none"  # connected | no_push | unverified | none
    apis: dict[str, str] | None = None  # location -> granted | skipped
    deploy_steps: str = "none"  # declared | adopted | skipped | none
    drill: str = "not_run"  # passed | failed | skipped | not_possible: <why>
    complete: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "rev": self.rev,
            "at": self.at,
            "stack": self.stack,
            "resources": self.resources,
            "blind_spots": self.blind_spots or [],
            "databases": self.databases or {},
            "github": self.github,
            "apis": self.apis or {},
            "deploy_steps": self.deploy_steps,
            "drill": self.drill,
            "complete": self.complete,
        }


def status(store: Any) -> dict[str, Any] | None:
    """What the last reconnaissance recorded, or None when it never ran."""
    value = store.get_value(KEY)
    return value if isinstance(value, dict) else None


def summary_line(record: dict[str, Any] | None) -> str:
    if record is None:
        return t("recon.status.never")
    if record.get("complete"):
        return t("recon.status.complete", at=str(record.get("at", ""))[:16], stack=record.get("stack", "?"))
    return t("recon.status.incomplete", stack=record.get("stack", "?"), why=incomplete_why(record))


def incomplete_why(record: dict[str, Any]) -> str:
    reasons: list[str] = []
    if record.get("stack") not in ("running", "started", "absent"):
        reasons.append(f"stack {record.get('stack')}")
    for name, state in (record.get("databases") or {}).items():
        if state not in ("container", "granted"):
            reasons.append(f"{name} {state}")
    if record.get("github") == "no_push":
        reasons.append("GitHub account cannot push")
    return ", ".join(reasons) or "see `unbidden setup recon`"


# --- the step -------------------------------------------------------------------------------------------------


def step_recon(ctx: Context) -> None:
    ctx.title("recon.title")
    ctx.say(t("recon.explain"))
    found = ctx.facts()
    repo = ctx.ws.repo
    record = Recon(rev=found.head, at=datetime.now(UTC).isoformat(timespec="minutes"), databases={}, apis={},
                   blind_spots=[])  # fmt: skip

    # 1. The stack.
    if found.compose_path is None:
        record.stack = "absent"
        ctx.say(t("recon.stack.none"))
    else:
        running = ctx.containers(repo)
        if running:
            record.stack = "running"
            ctx.say(t("recon.stack.running", n=len(running), project=found.compose_path))
        elif ctx.opts.non_interactive:
            record.stack = "down"
            ctx.say(t("recon.stack.down"))
        elif ctx.io.confirm("start_stack", t("recon.stack.ask", command=" ".join(UP)), True):
            ctx.say(t("recon.stack.starting"))
            if ctx.terminal(UP) == 0 and ctx.containers(repo):
                record.stack = "started"
                ctx.say(t("recon.stack.started"))
            else:
                record.stack = "failed"
                ctx.say(t("recon.stack.failed"))
        else:
            record.stack = "skipped"
            ctx.say(t("recon.stack.skipped"))

    # 2. The map, when something runs.
    world = None
    if record.stack in ("running", "started"):
        ctx.say(t("recon.map.mapping"))
        world = ctx.mapper(ctx.ws)
        if world is not None:
            record.resources = len(world.resources)
            record.blind_spots = [f"{b.what}: {b.why}" for b in world.blind_spots]
            ctx.say(t("recon.map.done", resources=len(world.resources), blind=len(world.blind_spots)))
            for spot in record.blind_spots:
                ctx.say(f"  - {spot}")

    # 3. Databases.
    _databases(ctx, record, world)

    # 4. GitHub.
    _github(ctx, record)

    # 5. External APIs.
    _apis(ctx, record)

    # 6. Deploy steps.
    _deploy_steps(ctx, record)

    # 7. The rollback drill.
    _drill(ctx, record, world)

    dbs = record.databases or {}
    record.complete = (
        record.stack in ("running", "started", "absent")
        and all(state in ("container", "granted") for state in dbs.values())
        and record.github != "no_push"
    )
    ctx.store.set_value(KEY, record.as_dict())
    ctx.answers.recon = record.as_dict()
    ctx.say(
        t("recon.done.complete" if record.complete else "recon.done.incomplete", why=incomplete_why(record.as_dict()))
    )


def _databases(ctx: Context, record: Recon, world: Any) -> None:
    from unbidden.observe.compose import load_compose

    found = ctx.facts()
    compose = load_compose(ctx.ws.repo, "HEAD") if found.head else None
    assert record.databases is not None
    for name, kind in found.services:
        if kind != "postgres":
            continue
        service = compose.services.get(name) if compose else None
        read = _tables_read(world, name)
        if read:
            record.databases[name] = "container"
            ctx.say(t("recon.db.container", service=name, count=read))
        elif world is None:
            record.databases[name] = "unread"
            ctx.say(t("recon.db.nostack", service=name))
        else:
            record.databases[name] = "unread"
            why = next((b.why for b in world.blind_spots if b.what.startswith(f"tables of {name}")), "")
            ctx.say(t("recon.db.unread", service=name, why=why or "no tables were read"))
        port = _published_port(service.ports if service else (), 5432)
        if port is None or ctx.opts.non_interactive:
            continue
        if not ctx.io.confirm("db_grant", t("recon.db.grant.ask", service=name, port=port), read == 0):
            ctx.say(t("recon.db.grant.skipped"))
            continue
        database = (service.environment.get("POSTGRES_DB") if service else None) or "postgres"
        username = ctx.io.text("db_username", t("recon.db.grant.username"), "unbidden_ro") or "unbidden_ro"
        ref = re.sub(r"\W", "_", f"{name}_RO_PASSWORD").upper()
        password = ctx.io.secret(ref, t("recon.db.grant.password", username=username))
        if not password:
            ctx.say(t("recon.db.grant.skipped"))
            continue
        from unbidden.guardian.credentials import broker
        from unbidden.setup import machine

        machine.write_env(ctx.ws.dir / ".env", {ref: password})
        broker().hold(ref, password)
        grant = {"id": f"{name}-ro", "kind": "postgres", "location": f"127.0.0.1:{port}/{database}",
                 "environment": "development", "username": username, "credential_ref": ref,
                 "permissions": ["read"]}  # fmt: skip
        state, detail = ctx.checker(grant)
        if state == "connected":
            connections = [c for c in ctx.body.get("connections", []) if c.get("id") != grant["id"]]
            ctx.body["connections"] = [*connections, grant]
            record.databases[name] = "granted"
            ctx.say(t("recon.db.grant.ok", id=grant["id"], detail=detail))
        else:
            record.databases[name] = "grant_failed" if read == 0 else "container"
            ctx.say(t("recon.db.grant.failed", state=state, detail=detail))


def _tables_read(world: Any, service: str) -> int:
    if world is None:
        return 0
    return sum(
        1
        for r in world.current_relations()
        if r.src == f"service:{service}"
        and r.predicate == "defines"
        and (r.source or "").startswith("postgres-readonly")
    )


def _published_port(ports: tuple[str, ...], container_port: int) -> int | None:
    for spec in ports:
        parts = str(spec).split(":")
        if len(parts) >= 2 and parts[-1].split("/")[0] == str(container_port):
            try:
                return int(parts[-2].split("/")[0])
            except ValueError:
                continue
    return None


def _github(ctx: Context, record: Recon) -> None:
    found = ctx.facts()
    check = found.github_check
    if found.slug is None or found.github.source is None:
        record.github = "none"
        ctx.say(t("recon.github.none"))
        return
    if check is None or check.can_push is None:
        record.github = "unverified"
        ctx.say(t("recon.github.unverified", detail=check.detail if check else "not checked"))
        return
    if not check.can_push:
        record.github = "no_push"
        ctx.say(t("recon.github.nopush", login=check.login or "?", slug=found.slug))
        return
    grant = {"id": "github", "kind": "github", "location": found.slug, "credential_ref": "GITHUB_TOKEN",
             "environment": "production", "permissions": ["read"]}  # fmt: skip
    connections = [c for c in ctx.body.get("connections", []) if c.get("kind") != "github"]
    ctx.body["connections"] = [*connections, grant]
    record.github = "connected"
    ctx.say(t("recon.github.ok", login=check.login or "?", slug=found.slug))


def _apis(ctx: Context, record: Recon) -> None:
    found = ctx.facts()
    assert record.apis is not None
    for kind, location, evidence in found.external:
        if kind != "http_api":
            continue
        if ctx.opts.non_interactive:
            record.apis[location] = "skipped"
            continue
        ctx.say(t("recon.api.found", location=location, evidence=evidence))
        pick = ctx.io.choice("api_access", t("recon.api.ask"), ("skip", "key"), "skip")
        if pick != "key":
            record.apis[location] = "skipped"
            continue
        ref = re.sub(r"\W", "_", re.sub(r"^https?://", "", location)).upper() + "_KEY"
        value = ctx.io.secret(ref, t("recon.api.key", location=location))
        if not value:
            record.apis[location] = "skipped"
            continue
        from unbidden.guardian.credentials import broker
        from unbidden.setup import machine

        machine.write_env(ctx.ws.dir / ".env", {ref: value})
        broker().hold(ref, value)
        grant = {
            "id": re.sub(r"\W", "-", re.sub(r"^https?://", "", location)).strip("-"),
            "kind": "http_api",
            "location": location,
            "credential_ref": ref,
            "environment": "staging",
            "permissions": ["read"],
        }
        connections = [c for c in ctx.body.get("connections", []) if c.get("id") != grant["id"]]
        ctx.body["connections"] = [*connections, grant]
        record.apis[location] = "granted"
        ctx.say(t("recon.api.saved", ref=ref))


def _deploy_steps(ctx: Context, record: Recon) -> None:
    from unbidden.operate.actions import propose_procedure

    operations = ctx.body.setdefault("operations", {})
    if operations.get("deploy_steps"):
        record.deploy_steps = "declared"
        ctx.say(t("recon.deploy.declared", steps=" && ".join(" ".join(s) for s in operations["deploy_steps"])))
        return
    commands: list[str] = []
    for action in propose_procedure(ctx.store, ctx.ws.repo):
        if action.operation not in commands:
            commands.append(action.operation)
    if not commands:
        record.deploy_steps = "none"
        ctx.say(t("recon.deploy.none"))
        return
    if ctx.opts.non_interactive:
        record.deploy_steps = "skipped"
        ctx.say(t("recon.deploy.found", command=commands[0]))
        return
    for command in commands[:3]:
        if ctx.io.confirm("adopt_deploy", t("recon.deploy.ask", command=command), command == commands[0]):
            import shlex

            operations["deploy_steps"] = [shlex.split(command)]
            record.deploy_steps = "adopted"
            ctx.say(t("recon.deploy.adopted", command=command))
            return
    record.deploy_steps = "skipped"
    ctx.say(t("recon.deploy.skipped"))


def _drill(ctx: Context, record: Recon, world: Any) -> None:
    operations = ctx.body.get("operations") or {}
    if not operations.get("deploy_steps"):
        record.drill = "not_possible: no deploy steps"
        return
    health = next(
        (
            e
            for e in (world.of_kind("endpoint") if world is not None else [])
            if e.name.startswith("GET ") and "health" in e.name and e.attributes.get("port")
        ),
        None,
    )
    if health is None:
        record.drill = "not_possible: no live health endpoint on the map"
        ctx.say(t("recon.drill.nohealth"))
        return
    previous = subprocess.run(["git", "-C", str(ctx.ws.repo), "rev-parse", "HEAD~1"], capture_output=True, text=True,
                              check=False).stdout.strip()  # fmt: skip
    if not previous:
        record.drill = "not_possible: fewer than two commits"
        ctx.say(t("recon.drill.nocommit"))
        return
    if ctx.opts.non_interactive or not ctx.io.confirm("run_drill", t("recon.drill.ask", previous=previous[:12]), False):
        record.drill = "skipped"
        ctx.say(t("recon.drill.skipped"))
        return
    url = f"http://127.0.0.1:{health.attributes['port']}{health.name.split(' ', 1)[1]}"
    ctx.say(t("recon.drill.running", url=url))
    from unbidden.guardian.mandate_edit import validate

    result = ctx.driller(ctx.ws, validate(ctx.raw), previous, url)
    record.drill = "passed" if result.get("passed") else "failed"
    ctx.say(t("recon.drill.passed" if result.get("passed") else "recon.drill.failed", back=result.get("back"),
              forth=result.get("forth")))  # fmt: skip


# --- the defaults the wizard injects (tests pass their own) ----------------------------------------------------------


def containers(repo: Path) -> list[dict[str, Any]]:
    from unbidden.world.runtime import running_containers

    try:
        return running_containers(repo)
    except Exception:
        return []


def mapper(ws: Any) -> Any:
    """The map of the running system, as `unbidden map` makes it (no model call)."""
    from unbidden.workspace import head_sha
    from unbidden.world.discover import discover

    store = ws.store()
    try:
        return asyncio.run(discover(ws.repo, head_sha(ws.repo), store, ws.mandate(), None))
    except Exception:
        return None


def checker(grant: dict[str, Any]) -> tuple[str, str]:
    """A postgres grant checked now: (state, detail)."""
    from unbidden.connect.base import purpose
    from unbidden.connect.postgres import PostgresConnector
    from unbidden.contracts.guardian import ConnectionGrant
    from unbidden.guardian.credentials import broker

    try:
        parsed = ConnectionGrant.model_validate(grant)
        broker().grant(parsed.credential_ref or "", purpose(parsed.id))
        result = PostgresConnector().check(parsed)
    except Exception as exc:
        return "degraded", f"{type(exc).__name__}: {str(exc)[:160]}"
    return result.state.value, result.detail[:160]


def driller(ws: Any, mandate: Any, previous: str, url: str) -> dict[str, Any]:
    from unbidden.operate.deploy import drill

    store = ws.store()
    return drill(ws.repo, store, mandate, previous, url)
