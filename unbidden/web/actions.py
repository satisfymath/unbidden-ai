"""Operational actions from the web, each either done through the engine's own mechanism or honestly refused.

The kill switch is a file (`guardian/killswitch.py`), the same one `unbidden kill` writes: safe across processes.
Policy verdicts are read from the mandate with `PolicyEngine`, so the UI shows what the mandate would decide, not
a guess. Approving a proposal, rejecting an opportunity and approving writes through a connection go through
`operate/decisions.py` on a live workspace: the same short transaction and the same events the CLI writes, picked
up by the agent on its next cycle (or waiting in the store for `unbidden start`). Deploy and rollback are effects
run by the engine under its lock and policy: the response names the CLI command. Records and the demo are never
written to.
"""

from __future__ import annotations

import threading
from typing import Any

from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.guardian.policy import CAPABILITIES, PolicyEngine
from unbidden.web.contracts import ActionRequestWeb, ActionResponse
from unbidden.web.sources import Source

CLI = {
    "approve": "unbidden approve {subject}",
    "reject": "unbidden reject {subject} --reason '...'",
    "deploy": "unbidden deploy {subject}",
    "rollback": "unbidden deploy --rollback",
    "approve_writes": "unbidden approve-writes {subject}",
}


class Actions:
    def __init__(self) -> None:
        self._seen: dict[str, ActionResponse] = {}
        self._lock = threading.Lock()

    def run(self, source: Source, request: ActionRequestWeb) -> ActionResponse:
        key = f"{source.id}:{request.idempotency_key}"
        with self._lock:
            if key in self._seen:  # the same request twice has one effect and the same answer
                return self._seen[key].model_copy(update={"effect": "already"})
            response = self._run(source, request)
            self._seen[key] = response
            return response

    def _run(self, source: Source, request: ActionRequestWeb) -> ActionResponse:
        op = request.operation
        if op in ("kill", "resume"):
            switch = source.killswitch()
            if switch is None:
                return ActionResponse(
                    ok=False,
                    operation=op,
                    effect="not_supported_here",
                    detail="this source has no workspace directory, so no kill switch file",
                )
            if (
                request.expected_revision
                and source.head()
                and not str(source.head()).startswith(request.expected_revision)
            ):
                return ActionResponse(
                    ok=False,
                    operation=op,
                    effect="refused",
                    detail=f"the workspace is at {str(source.head())[:12]}, not {request.expected_revision}",
                )
            if op == "kill":
                if switch.engaged:
                    return ActionResponse(
                        ok=True, operation=op, effect="already", detail="the kill switch was already engaged"
                    )
                switch.engage(request.reason or "engaged from the web workspace")
                return ActionResponse(
                    ok=True,
                    operation=op,
                    effect="done",
                    cli="unbidden resume",
                    detail="kill switch engaged: no job starts and no model is called until it is released",
                )
            if not switch.engaged:
                return ActionResponse(ok=True, operation=op, effect="already", detail="the kill switch was not engaged")
            switch.release()
            return ActionResponse(ok=True, operation=op, effect="done", detail="kill switch released")
        if op == "evaluate":
            if source.mandate is None:
                return ActionResponse(
                    ok=False, operation=op, effect="not_supported_here", detail="no mandate in this source"
                )
            capability = request.capability or ""
            if capability not in CAPABILITIES:
                return ActionResponse(
                    ok=False,
                    operation=op,
                    effect="refused",
                    detail=f"unknown capability; known: {', '.join(sorted(CAPABILITIES))}",
                )
            verdict = PolicyEngine(source.mandate).evaluate(
                ActionRequest(capability=capability, purpose=request.reason or "asked from the web workspace")
            )
            return ActionResponse(
                ok=True,
                operation=op,
                effect="done",
                verdict=verdict.model_dump(mode="json"),
                detail=f"{verdict.decision.value} by {verdict.rule}",
            )
        cli = CLI.get(op, "unbidden --help").format(subject=request.subject or "<id>")
        if op in ("approve", "reject", "approve_writes") and source.mode == "live" and source.state_dir is not None:
            return self._decide(source, request, cli)
        if source.mode != "live":
            detail = f"this {source.mode} record is read-only: nothing is decided or run from it"
        else:
            detail = (
                "a deploy or rollback is an effect the engine runs under its lock, the mandate's steps and the "
                "kill switch: run it from the CLI"
            )
        return ActionResponse(ok=False, operation=op, effect="not_supported_here", cli=cli, detail=detail)

    def _decide(self, source: Source, request: ActionRequestWeb, cli: str) -> ActionResponse:
        """A person's decision written to the workspace's state by the shared module; the agent (running or started
        later) carries it out under the mandate. Nothing here runs a job or a model."""
        import getpass

        from unbidden.operate.decisions import DecisionError, approve_by_id, approve_writes, reject_by_id
        from unbidden.store import Store

        op = request.operation
        subject = request.subject or ""
        if not subject:
            return ActionResponse(ok=False, operation=op, effect="refused", cli=cli, detail="which one? no subject")
        if request.expected_revision and source.head() and not str(source.head()).startswith(request.expected_revision):
            detail = f"the workspace is at {str(source.head())[:12]}, not {request.expected_revision}"
            return ActionResponse(ok=False, operation=op, effect="refused", cli=cli, detail=detail)
        by = getpass.getuser()
        hours = 24.0
        if request.expires_at is not None:
            from datetime import UTC, datetime

            hours = max(0.1, (request.expires_at - datetime.now(UTC)).total_seconds() / 3600)
        assert source.state_dir is not None
        store = Store(source.state_dir / "state.db")
        try:
            if op == "approve":
                done = approve_by_id(store, subject, by=by, hours=hours)
                detail = (
                    f"approved by {by}: the pull request for {done['branch']} opens on the agent's next cycle "
                    f"({_agent_line(source)})"
                )
            elif op == "reject":
                done = reject_by_id(store, subject, by=by, reason=request.reason or "rejected from the dashboard")
                detail = f"rejected by {by}: {subject} will not be proposed again"
            else:
                if source.mandate is None:
                    return ActionResponse(ok=False, operation=op, effect="refused", cli=cli, detail="no mandate")
                done = approve_writes(store, source.mandate, subject, by=by, hours=hours)
                detail = f"writes to {subject} approved by {by} until {done['expires_at']:%Y-%m-%d %H:%M} UTC"
        except DecisionError as exc:
            return ActionResponse(ok=False, operation=op, effect="refused", cli=cli, detail=str(exc))
        finally:
            store.close()
        return ActionResponse(ok=True, operation=op, effect="done", cli=cli, detail=detail, verdict=_jsonable(done))


def _agent_line(source: Source) -> str:
    """Whether an agent is running on this workspace, from the engine lock (delivery C); unknown when absent."""
    import importlib

    try:
        owner = importlib.import_module("unbidden.daemon.owner")
    except ImportError:  # the lock module is not in this build
        return "agent state unknown"
    info = owner.holder(source.state_dir) if source.state_dir is not None else None
    return f"agent running, pid {info['pid']}" if info else "agent not running: `unbidden start`"


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in value.items()}


def mandate_view(mandate: Mandate | None) -> dict[str, Any]:
    """The mandate as a person reads it: autonomy, egress, models, connections, goals. Never credentials."""
    if mandate is None:
        return {}
    m = mandate.model_dump(mode="json")
    for grant in m.get("connections", []):
        grant.pop("credential_ref", None)
    m["egress"]["github"].pop("token_env", None)
    if m.get("operations", {}).get("probe_auth"):
        m["operations"]["probe_auth"] = "configured"
    return m
