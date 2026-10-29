"""Pursuing a mandate's goal with the project's connected systems: one investigation pattern, a reconciliation.

The local model plans; Unbidden executes, computes and bounds. The plan names a bounded SQL query on a database
connection, a read operation of an API connection, the key both share, the shortfall as an arithmetic expression
over their fields, and, when the goal calls for a change, the write operation and its key and amount fields. Then:
the reads run through the connection gate (`postgres.query`, the integration's executor), the rows are joined on
the key, the expression is evaluated by a small arithmetic evaluator (names, numbers, + - * and parentheses only),
the rows above zero are ranked, cut to the goal's bounds, and each becomes a typed action (`operate/actions.py`)
with its preconditions; nothing is written unless the mandate, the grant and an observed write ability allow it.
A source the plan needs that is not usable is recorded as a capability need that resumes this pursuit when filled.
"""

from __future__ import annotations

import ast
import json
import math
from datetime import datetime
from typing import Any

from pydantic import Field

from unbidden.brain.prompts import load_prompt
from unbidden.connect.base import Unavailable
from unbidden.connect.postgres import QueryRefused, catalog, query
from unbidden.connect.registry import COLLECTION as CONNECTIONS
from unbidden.contracts.action import Action, ActionStatus
from unbidden.contracts.common import Contract, new_id, utc_now
from unbidden.contracts.connection import USABLE, Connection, ConnectionState
from unbidden.contracts.guardian import Goal, Mandate
from unbidden.contracts.llm import LLMRequest, Message, Source, Tier
from unbidden.forge.api_client import COLLECTION as INTEGRATIONS
from unbidden.forge.api_client import ApiIntegration, CallFailed, DeviationBlocked  # pyright: ignore[reportPrivateUsage]
from unbidden.operate.actions import idempotency_key, run_api_action
from unbidden.store import Store

COLLECTION = "goal_runs"
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["needs"],
    "properties": {
        "needs": {"type": "array", "items": {"type": "string"}},
        "sql": {
            "type": "object",
            "required": ["connection", "query"],
            "properties": {"connection": {"type": "string"}, "query": {"type": "string"}},
        },
        "api": {
            "type": "object",
            "required": ["connection", "operation"],
            "properties": {"connection": {"type": "string"}, "operation": {"type": "string"}},
        },
        "key": {"type": "string"},
        "shortfall": {"type": "string"},
        "page": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
        "act": {
            "type": "object",
            "required": ["operation", "key_field", "amount_field"],
            "properties": {
                "operation": {"type": "string"},
                "key_field": {"type": "string"},
                "amount_field": {"type": "string"},
            },
        },
    },
}


class Incomplete(RuntimeError):
    """A source could not be read whole; decisions that need the whole set are not taken."""


class GoalRun(Contract):
    id: str = Field(default_factory=lambda: new_id("goal"))
    goal: str
    status: str = "planning"  # planning | waiting_capability | blocked | investigated | acted | failed
    plan: dict[str, Any] = Field(default_factory=dict[str, Any])
    reads: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    findings: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    actions: list[str] = Field(default_factory=list[str])
    notes: list[str] = Field(default_factory=list[str])
    model: dict[str, Any] = Field(default_factory=dict[str, Any])
    evidence: dict[str, Any] = Field(default_factory=dict[str, Any])  # a page goal: scans, changes, verification
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


_ALLOWED = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.USub,
    ast.Name,
    ast.Load,
    ast.Constant,
)


def evaluate(expression: str, row: dict[str, Any]) -> float:
    """Arithmetic over a row's fields: names, numbers, + - * and parentheses. Anything else is refused."""
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED) or (
            isinstance(node, ast.Constant) and not isinstance(node.value, int | float)
        ):
            raise ValueError(f"not allowed in a shortfall: {ast.dump(node)[:60]}")

    def value(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return value(node.body)
        if isinstance(node, ast.Constant):
            assert isinstance(node.value, int | float)  # checked above
            return float(node.value)
        if isinstance(node, ast.Name):
            found = row.get(node.id)
            if found is None:
                raise KeyError(node.id)
            return float(found)
        if isinstance(node, ast.UnaryOp):
            return -value(node.operand)
        assert isinstance(node, ast.BinOp)
        left, right = value(node.left), value(node.right)
        return (
            left + right
            if isinstance(node.op, ast.Add)
            else left - right
            if isinstance(node.op, ast.Sub)
            else left * right
        )

    return value(tree)


def _sources(
    store: Store, mandate: Mandate
) -> tuple[list[str], list[str], dict[str, Connection], dict[str, ApiIntegration]]:
    usable, blocked, conns, integrations = [], [], {}, {}
    for conn in store.list(CONNECTIONS, Connection):
        if not conn.grant:
            continue
        conns[conn.grant] = conn
        if conn.kind == "postgres" and conn.state in USABLE and conn.can("read"):
            try:
                tables = catalog(conn, mandate)
            except (Unavailable, QueryRefused, Exception) as exc:  # a failed read is a blocked source, said so
                blocked.append(f"- {conn.grant} ({conn.kind}): read failed: {str(exc)[:120]}")
                continue
            listing = "; ".join(
                f"{t['table']}({', '.join(c['column'] + ' ' + c['type'] for c in t['columns'])}) ~{t['rows']} rows"
                for t in tables
            )
            usable.append(f"- {conn.grant} (postgres, {conn.environment.value}): {listing}")
        elif conn.kind == "http_api" and conn.state in USABLE and conn.capability_id:
            integration = store.get(INTEGRATIONS, conn.capability_id, ApiIntegration)
            if integration is None:
                continue
            integrations[conn.grant] = integration
            ops = []
            for op in integration.operations:
                if not conn.can(op.effect, op.id):
                    continue
                fields = _fields(op.responses.get("200") or op.responses.get("201") or {})
                body = ", ".join((op.body_schema or {}).get("properties", {}))
                ops.append(
                    f"{op.id} ({op.effect}{'; record fields: ' + ', '.join(fields) if fields else ''}"
                    f"{'; body: ' + body if body else ''})"
                )
            usable_ops = {o.id for o in integration.operations if conn.can(o.effect, o.id)}
            more = [
                f"{d['id']} ({d['effect']}: {d['method']} {d['path']}, {d['summary']})"
                for d in integration.documented
                if d["id"] not in usable_ops
            ]
            extra = f"; documented, not usable yet (to integrate or validate): {'; '.join(more)}" if more else ""
            usable.append(
                f"- {conn.grant} (api {integration.title}, {conn.environment.value}): {'; '.join(ops)}{extra}"
            )
        else:
            blocked.append(
                f"- {conn.grant} ({conn.kind}): {conn.state.value}: {conn.blocked or conn.check_detail}"[:200]
            )
    return usable, blocked, conns, integrations


def _fields(schema: dict[str, Any]) -> list[str]:
    if schema.get("type") == "array":
        return list((schema.get("items") or {}).get("properties", {}))
    for value in (schema.get("properties") or {}).values():
        if isinstance(value, dict) and value.get("type") == "array":
            return list((value.get("items") or {}).get("properties", {}))
    return list(schema.get("properties", {}))


def _pages(store: Store) -> list[str]:
    """Web pages the project publishes on this machine, as the world model found them."""
    from unbidden.contracts.world import WorldModel

    world = store.get("world", "world", WorldModel)
    if world is None:
        return []
    return sorted(
        f"- {r.attributes.get('service') or r.id}: {r.attributes['web_page']}"
        for r in world.resources.values()
        if r.attributes.get("web_page")
    )


async def pursue(
    brain: Any,
    store: Store,
    mandate: Mandate,
    goal: Goal,
    *,
    window: str,
    workspace: Any = None,
    resume: dict[str, Any] | None = None,
    read_only: bool = False,
) -> GoalRun:
    """A goal's run. `read_only` (Unbidden's own consistency questions, stage 9): no action and no page; any
    difference either way is a finding (`run.findings`), not only a shortfall. `resume` is the job a capability
    built for it wakes (by default this goal's own pursuit)."""
    run = GoalRun(goal=goal.id)
    usable, blocked, conns, integrations = _sources(store, mandate)
    source: Source = (
        "synthetic" if mandate.connections and all(g.content_may_leave for g in mandate.connections) else "runtime"
    )
    prompt = load_prompt("goal_plan")
    request = LLMRequest(
        purpose="director.goal_plan",
        tier=Tier.LOCAL,
        response_schema=PLAN_SCHEMA,
        max_tokens=1500,
        prompt_sha256=prompt.sha256,
        messages=[
            Message(
                role="user",
                # Schemas, records and documentation of the connections: remote only if every granted one lets
                # its content leave (laboratory data a person declared); otherwise the plan stays local.
                source=source,
                content=prompt.render(
                    goal=goal.statement,
                    bounds=json.dumps(goal.bounds),
                    sources="\n".join(usable) or "- nothing",
                    blocked="\n".join(blocked) or "- nothing",
                    pages="\n".join(_pages(store)) or "- none found",
                    schema=json.dumps(PLAN_SCHEMA),
                ),
            )
        ],
    )
    started = utc_now()
    response = await brain.complete(request)
    run.model = {"model": getattr(response, "model", None), "seconds": (utc_now() - started).total_seconds()}
    try:
        plan = json.loads(response.content)
    except json.JSONDecodeError:
        return _finish(store, run, "failed", "the plan was not JSON")
    run.plan = plan
    missing = [n for n in plan.get("needs") or [] if n in conns and conns[n].state not in USABLE]
    unbuilt = [n for n in missing if conns[n].state is ConnectionState.NEEDS_CAPABILITY]
    if unbuilt:
        from unbidden.forge import needs

        given_up: list[str] = []
        for name in unbuilt:
            need, _ = needs.record(
                store,
                "api_client",
                conns[name].id,
                f"goal {goal.id} needs {name}",
                resume=[resume or {"type": "goal.pursue", "key": goal.id, "payload": {"goal": goal.id}}],
            )
            if need.status.value == "abandoned":
                why = next((n for n in reversed(need.notes) if not n.startswith(("attempt", "no capability"))), "")
                given_up.append(f"{name}: no integration could be validated ({why})")
        if given_up:
            return _finish(store, run, "blocked", "; ".join(given_up))
        return _finish(store, run, "waiting_capability", f"needs an integration for {', '.join(unbuilt)}")
    if missing:
        return _finish(store, run, "blocked", "; ".join(f"{n}: {conns[n].state.value}" for n in missing))
    try:
        rows, partial = _read(store, mandate, plan, conns, integrations, run)
    except Incomplete as exc:
        return _finish(store, run, "blocked_incomplete", f"read incomplete, nothing decided: {exc}")
    except DeviationBlocked as exc:
        return _finish(store, run, "blocked", f"conclusion blocked by a documented-vs-observed deviation: {exc}")
    except CallFailed as exc:
        return _finish(store, run, "failed", f"reads: {exc}")
    except (Unavailable, QueryRefused, KeyError, ValueError) as exc:
        return _finish(store, run, "failed", f"reads: {exc}")
    key, expression = str(plan.get("key")), str(plan.get("shortfall"))
    short, values = [], {}
    for row in rows:
        try:
            amount = evaluate(expression, row)
        except (KeyError, ValueError, ZeroDivisionError) as exc:
            run.notes.append(f"{row.get(key)}: {exc}")
            continue
        values[str(row[key])] = amount
        if amount > 0 or (read_only and amount != 0):
            short.append({key: row[key], "shortfall": amount, "row": row})
    short.sort(key=lambda r: -r["shortfall"])
    run.findings = short
    page = plan.get("page") or {}
    if read_only:
        if partial and not short:
            return _finish(store, run, "inconclusive", f"no difference among the {len(rows)} keys read, but the "
                           f"set's completeness is unknown ({partial}): 'none' is not concluded")  # fmt: skip
        whole = "" if not partial else f" (over a read whose completeness is unknown: {partial})"
        return _finish(store, run, "investigated", f"{len(short)} of {len(rows)} keys differ{whole}")
    if partial and page.get("url"):
        # A page is judged on every row: rows not read would be judged wrong for being absent.
        return _finish(store, run, "blocked_incomplete", f"a page is judged on the whole set, and {partial}")
    if partial and not short:
        return _finish(store, run, "inconclusive", f"no discrepancy among the {len(rows)} keys read, but the set's "
                       f"completeness is unknown ({partial}): 'none' is not concluded")  # fmt: skip
    if partial:
        run.notes.append(f"over a read whose completeness is unknown ({partial}): keys not read were not judged")
    if page.get("url"):
        return await _pursue_page(brain, store, mandate, goal, run, rows, key, values, str(page["url"]),
                                  window=window, workspace=workspace, source=source)  # fmt: skip
    act = plan.get("act")
    if not act or not short:
        return _finish(store, run, "investigated", f"{len(short)} of {len(rows)} keys short; nothing to change")
    _act(store, mandate, goal, run, short, act, conns, integrations, plan, window)
    if run.status in ("waiting_extension", "blocked"):
        return _finish(store, run, run.status, run.notes[-1])
    done = [f for f in short if (f.get("action") or {}).get("status") in ("executed", "verified", "unverified")]
    status = "acted" if done else "investigated"
    return _finish(
        store,
        run,
        status,
        f"{len(short)} of {len(rows)} keys short; {len(done)} action(s) taken, {len(run.actions) - len(done)} refused",
    )


async def _pursue_page(
    brain: Any, store: Store, mandate: Mandate, goal: Goal, run: GoalRun, rows: list[dict[str, Any]], key: str,
    values: dict[str, float], url: str, *, window: str, workspace: Any, source: Source,
) -> GoalRun:  # fmt: skip
    from unbidden.config import load_config
    from unbidden.director.presentation import expected, pursue_page
    from unbidden.lab.ui import LOCAL_PAGE

    if workspace is None:
        return _finish(store, run, "blocked", "a page goal needs the workspace (its repository and artifacts)")
    if LOCAL_PAGE.match(url) is None or url.split("/")[2] not in {
        p.split(": ", 1)[1].split("/")[2] for p in _pages(store)
    }:
        return _finish(store, run, "blocked", f"{url} is not a page this project publishes on this machine")
    want = expected(rows, key, values)
    perception = load_config(workspace.config_path).ui.perception
    try:
        await pursue_page(brain, store, mandate, goal, run, want, url, repo=workspace.repo,
                          artifacts=workspace.dir / "artifacts", perception=perception, window=window,
                          source=source)  # fmt: skip
    except RuntimeError as exc:  # the confined browser could not load the page
        return _finish(store, run, "failed", f"page: {exc}")
    return _finish(store, run, run.status, run.notes[-1] if run.notes else run.status)


def _read(
    store: Store,
    mandate: Mandate,
    plan: dict[str, Any],
    conns: dict[str, Connection],
    integrations: dict[str, ApiIntegration],
    run: GoalRun,
) -> tuple[list[dict[str, Any]], str | None]:
    """The joined rows, and why the API's set may be partial (None when it was read whole). A read known to be
    incomplete blocks everything; one whose completeness is unknown allows only the conclusions it can carry."""
    sql, api, key = plan.get("sql") or {}, plan.get("api") or {}, str(plan.get("key"))
    db = conns.get(str(sql.get("connection")))
    integration = integrations.get(str(api.get("connection")))
    if db is None or integration is None:
        raise KeyError("the plan names a connection that cannot be read")
    left = query(db, mandate, str(sql.get("query")), limit=1000)
    run.reads.append({"connection": db.id, "query": sql.get("query"), "rows": len(left)})
    op = integration.op(str(api.get("operation")))
    conn = conns[str(api.get("connection"))]
    from unbidden.forge.api_client import Degraded, read_collection

    # What this conclusion depends on: the key, and every field of the comparison. A deviation there blocks it.
    compared = {
        n.id for n in ast.walk(ast.parse(str(plan.get("shortfall") or "0"), mode="eval")) if isinstance(n, ast.Name)
    }
    degraded = Degraded(critical={key, *compared})
    read = read_collection(integration, conn, mandate, op.id, degraded=degraded)
    right = read.records
    run.reads.append({"connection": conn.id, "operation": op.id, **read.summary(), "deviations": degraded.log[:20]})
    db_whole = len(left) < 1000
    run.reads[0]["completeness"] = "complete" if db_whole else "incomplete"
    if read.completeness.value == "incomplete" or not db_whole:
        # A decision over a known-partial set would be about the part read as if it were the whole: not taken.
        raise Incomplete(read.why if read.completeness.value != "complete" else "the query reached its row limit")
    # Unknown completeness (stage 9): every record read is real, so a discrepancy found in it is real; what it cannot
    # carry is a claim about the whole set ("none", "every"). The caller limits its conclusions to that.
    partial = None if read.completeness.value == "complete" else read.why
    by_key = {r.get(key): r for r in right}
    if not left or key not in left[0]:
        raise KeyError(f"the query's rows have no field {key!r}")
    joined = []
    for row in left:
        other = by_key.get(row[key])
        if other is not None:
            joined.append({**other, **{k: (float(v) if hasattr(v, "as_integer_ratio") else v) for k, v in row.items()}})
    # Keys with records in the API but no row in the query: nothing was ordered; their demand is zero.
    for k, other in by_key.items():
        if k not in {r[key] for r in left}:
            joined.append({**other, **{c: 0 for c in left[0] if c != key}, key: k})
    run.reads.append({"joined": len(joined), "key": key, "partial": partial})
    return joined, partial


def _act(
    store: Store,
    mandate: Mandate,
    goal: Goal,
    run: GoalRun,
    short: list[dict[str, Any]],
    act: dict[str, Any],
    conns: dict[str, Connection],
    integrations: dict[str, ApiIntegration],
    plan: dict[str, Any],
    window: str,
) -> None:
    name = str((plan.get("api") or {}).get("connection"))
    conn, integration = conns[name], integrations[name]
    operation = str(act.get("operation"))
    if operation not in {o.id for o in integration.operations} or not conn.can("write", operation):
        if operation not in {d["id"] for d in integration.documented}:
            run.notes.append(f"the plan's write {operation!r} is not in {conn.id}'s documentation: blocked")
            run.status = "blocked"
            return
        # A documented operation the integration lacks: a specific need, resolved by extending the integration,
        # after which this goal resumes. One need per connection and operation; its attempts are bounded.
        from unbidden.connect.effects import WRITE
        from unbidden.forge import needs
        from unbidden.guardian.approvals import find_valid

        granted = next((g for g in mandate.connections if g.id == conn.grant), None)
        approval = find_valid(store, WRITE, conn.id)
        need, buildable = needs.record(
            store,
            "api_extension",
            f"{conn.id}#{operation}",
            f"goal {goal.id} needs {operation} on {conn.grant}",
            resume=[{"type": "goal.pursue", "key": goal.id, "payload": {"goal": goal.id}}],
            condition=f"{sorted(granted.permissions) if granted else []}; approval {approval.id if approval else None}",
        )
        if operation not in need.operations:
            need.operations = [*need.operations, operation]
            store.put(needs.COLLECTION, need)
        waits = ""
        if need.status.value == "blocked":
            waits = ": " + next((n for n in reversed(need.notes) if not n.startswith(("blocked", "attempt"))), "")
        run.notes.append(
            f"needs {operation} added to the integration "
            f"({need.status.value}{'' if buildable or need.status.value == 'blocked' else ', not retried'}{waits})"
        )
        run.status = "waiting_extension"
        return
    limit = int(goal.bounds.get("max_actions", 0) or 0)
    cap = int(goal.bounds.get("max_amount_per_action", 0) or 0)
    environment = str(goal.bounds.get("environment", ""))
    # The bounds hold for the goal over its window, across every run: a second pursuit the same day (resumed by a
    # second capability, say) sees what the first did, and acts again on no key it already acted on.
    acted = [
        a
        for a in store.list("actions", Action)
        if a.goal == goal.id
        and a.kind == "api_call"
        and f"{a.created_at:%Y-%m-%d}" == window
        and a.status in (ActionStatus.EXECUTED, ActionStatus.VERIFIED, ActionStatus.UNVERIFIED)
    ]
    keys_done = {str((a.body or {}).get(str(act["key_field"]))) for a in acted}
    if acted:
        run.notes.append(f"{len(acted)} action(s) already taken for this goal in {window}")
    for finding in short:
        if len(acted) + len(run.actions) >= limit:
            break
        if str(finding[str(plan["key"])]) in keys_done:
            finding["action"] = {"status": "skipped", "why": f"already acted on in {window}"}
            continue
        units = min(math.ceil(finding["shortfall"]), cap) if cap else math.ceil(finding["shortfall"])
        body = {str(act["key_field"]): finding[str(plan["key"])], str(act["amount_field"]): units}
        action = Action(
            kind="api_call",
            goal=goal.id,
            connection=conn.id,
            environment=conn.environment.value,
            operation=operation,
            body=body,
            requires="connection.write",
            idempotency_key=idempotency_key(goal.id, conn.id, operation, body, window),
        )
        conditions = [
            (f"environment is {environment}", conn.environment.value == environment, conn.environment.value),
            ("not production", conn.environment.value != "production", conn.environment.value),
            (f"amount within {cap}", not cap or units <= cap, str(units)),
            (
                f"at most {limit} actions for this goal in {window}",
                len(acted) + len(run.actions) < limit,
                str(len(acted) + len(run.actions)),
            ),
        ]
        done = run_api_action(store, mandate, action, integration, conn, conditions)
        run.actions.append(done.id)
        finding["action"] = {"id": done.id, "status": done.status.value, "units": units}
        if done.status is ActionStatus.REFUSED:
            run.notes.append(f"{body}: refused: {done.reason}"[:200])


def _finish(store: Store, run: GoalRun, status: str, note: str) -> GoalRun:
    run.status, run.finished_at = status, utc_now()
    run.notes.append(note)
    store.put(COLLECTION, run)
    return run
