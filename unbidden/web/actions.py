"""Operational actions from the web, each either done through the engine's own mechanism or honestly refused.

The kill switch is a file (`guardian/killswitch.py`), the same one `unbidden kill` writes: safe across processes.
Policy verdicts are read from the mandate with `PolicyEngine`, so the UI shows what the mandate would decide, not
a guess. Everything that needs the engine's store written (approve, reject, deploy, rollback, writes) is not done
here: the store has one writer, the daemon; the response says so and names the CLI command.
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
        return ActionResponse(
            ok=False,
            operation=op,
            effect="not_supported_here",
            cli=cli,
            detail="this needs the workspace's state written and a job queued; the engine's store has one writer "
            "(the daemon), so it is done from the CLI, which the daemon's next cycle picks up",
        )


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
