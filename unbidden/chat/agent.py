"""The chat's agent: a free question about the project answered by a model with read-only tools over the agent's
own records, the map, the repository at HEAD and the embedded docs. Used where no rule matches and a model may be
called; nothing here changes the canvas, the record or the system.

Every tool result carries the source label the router classifies: records and the map are `record`, the repository
is `repo` (both leave only when GitHub confirmed the repository public, or renamed by the bridge), the docs are
`prompt`. Production data (`runtime`) is never read here, so nothing that never leaves is put in front of a remote
model. The router's gate decides; a refusal becomes the answer, with the hint that would allow it."""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from unbidden.chat import docs
from unbidden.contracts.llm import LLMRequest, Message, Tier, ToolSpec
from unbidden.i18n import name as language_name
from unbidden.web.contracts import ChatMessage, ChatToolCall, ToolError, ToolResult

Emit = Callable[[str, dict[str, Any]], None]
MAX_OUTPUT = 5000
ROUNDS = 4
PURPOSE = "chat.agent"

SYSTEM = """You are Unbidden, the engineering agent working on {workspace}. You answer in {language}, briefly and
plainly, as a colleague would: what you found, what you are doing, why, what comes next. You know the project only
through the tools: read before you answer and never invent a number, a file or a finding; when the records lack it,
say so. You cannot act from here: approving, merging, deploying and changing the mandate happen through /ask,
/approve, the dashboard's buttons or the CLI; say which. Keep answers under 150 words unless asked for detail."""


class RecordsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Literal["status", "opportunities", "questions", "notes", "proposals", "spend", "connections"]


class WorldArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["summary", "services", "tables", "endpoints", "blind_spots"]


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=300)
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=120, ge=1)


class GrepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=2, max_length=80)


class GitLogArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(default=10, ge=1, le=40)


class DocsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Literal["what", "cycle", "commands", "modes", "levels", "keys", "spend"]


TOOLS: dict[str, tuple[type[BaseModel], str, str]] = {
    "records_query": (
        RecordsArgs,
        "Read the agent's own records: status (counts, the agent, what waits for a person), opportunities (with "
        "their stage and evidence level), questions (open asks), notes (what the agent said lately), proposals "
        "(branches and pull requests), spend (model calls and cost), connections (what is connected).",
        "record",
    ),
    "world_query": (
        WorldArgs,
        "Read the map of the running system: summary (resources by kind), services, tables (rows, indexes), "
        "endpoints, blind_spots (what could not be observed and why).",
        "record",
    ),
    "read_file": (ReadFileArgs, "Read a file of the repository at HEAD, by line range (at most 200 lines).", "repo"),
    "grep": (GrepArgs, "Search the repository at HEAD for a literal text (file:line matches).", "repo"),
    "git_log": (GitLogArgs, "The last commits of the repository (one line each).", "repo"),
    "docs": (
        DocsArgs,
        "What Unbidden is and how it is driven: what, cycle, commands, modes, levels, keys, spend. Read it before "
        "explaining Unbidden itself.",
        "prompt",
    ),
}

_GREETING = re.compile(
    r"^(hola|holi|hello|hi|hey|buenas|buenos dias|buenas tardes|buenas noches|que tal|como estas|como vas|how are you)"
    r"\b[\s!?.,]*(unbidden|agente|agent|bot)?[\s!?.,]*$"
)


def is_greeting(normalized: str) -> bool:
    return _GREETING.match(normalized) is not None


def tool_specs() -> list[ToolSpec]:
    return [ToolSpec.from_model(name, description, model) for name, (model, description, _) in TOOLS.items()]


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    return text if len(text) <= limit else text[:limit] + "\n… (cut)"


class AgentTools:
    """Read-only tools over one source; `call` returns the result and the source label of its content."""

    def __init__(self, source: Any) -> None:
        self.source = source

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[ToolResult, str]:
        spec = TOOLS.get(name)
        if spec is None:
            err = ToolError(code="unsupported", detail=f"no tool named {name!r}")
            return ToolResult(ok=False, tool=name, summary="no such tool", error=err), "prompt"
        model, _, label = spec
        try:
            args = model.model_validate(arguments)
        except ValidationError as exc:
            err = ToolError(code="invalid", detail=exc.errors()[0].get("msg", str(exc))[:300])
            return ToolResult(ok=False, tool=name, summary="invalid arguments", error=err), "prompt"
        try:
            text = self._run(name, args)
        except Exception as exc:  # a tool's failure is an answer, never the turn's end
            err = ToolError(code="no_data", detail=f"{type(exc).__name__}: {str(exc)[:200]}")
            return ToolResult(ok=False, tool=name, summary="could not read", error=err), "prompt"
        summary = text.splitlines()[0][:160] if text else "nothing"
        return ToolResult(ok=True, tool=name, summary=summary, data={"text": _clip(text)}), label

    # --- the records ------------------------------------------------------------------------------------------------

    def _run(self, name: str, args: Any) -> str:
        if name == "records_query":
            return self._records(args.topic)
        if name == "world_query":
            return self._world(args.kind)
        if name == "docs":
            return docs.read(args.topic)
        repo = getattr(self.source, "repo", None)
        if repo is None:
            return "no repository for this source"
        if not self._may_read_repo():
            return "refused by the mandate's policy: repo.read is not allowed"
        if name == "read_file":
            return self._read_file(Path(repo), args.path, args.start_line, args.end_line)
        if name == "grep":
            return _git(Path(repo), "grep", "-n", "-F", "-I", "--", args.text, "HEAD") or "no match"
        if name == "git_log":
            return _git(Path(repo), "log", f"-n{args.count}", "--date=short", "--format=%h %ad %s")
        return "no such tool"

    def _may_read_repo(self) -> bool:
        mandate = getattr(self.source, "mandate", None)
        if mandate is None:
            return True
        from unbidden.contracts.guardian import ActionRequest
        from unbidden.guardian.policy import PolicyEngine

        return PolicyEngine(mandate).evaluate(ActionRequest(capability="repo.read", purpose="chat")).allowed

    def _records(self, topic: str) -> str:
        store = self.source.store
        if topic == "status":
            summary = self.source.summary()
            counts = summary.get("counts", {})
            activity = summary.get("activity", {})
            lines = [
                f"workspace {self.source.name} ({self.source.mode}), head {summary.get('workspace', {}).get('head')}"
            ]
            lines.append("counts: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            discovered = activity.get("discovered") or {}
            if discovered:
                lines.append(f"opportunities by status: {discovered.get('by_status')}")
            agent = (summary.get("connection") or {}).get("agent")
            if agent:
                lines.append(f"agent: {agent}")
            waits = activity.get("needs_a_person") or []
            if waits:
                lines.append("waits for a person: " + "; ".join(str(w.get("what", w))[:120] for w in waits[:6]))
            checks = activity.get("project_checks")
            if checks:
                lines.append(f"project checks: {checks}")
            return "\n".join(lines)
        if topic == "opportunities":
            from unbidden.contracts.opportunity import Opportunity
            from unbidden.director.pipeline import describe

            opps = store.list("opportunities", Opportunity)
            opps.sort(key=lambda o: (-int(o.evidence_level), o.created_at))
            if not opps:
                return "no opportunities yet"
            return "\n".join(
                f"{o.id} L{int(o.evidence_level)} {o.status.value} {describe(store, o)['text']}: {o.title}"
                for o in opps[:30]
            )
        if topic == "questions":
            from unbidden.director.asks import open_asks

            asks = open_asks(store)
            if not asks:
                return "no open question"
            return "\n".join(
                f"{a.id} [{a.kind}] {a.title} options: {', '.join(o.key for o in a.options)}" for a in asks
            )
        if topic == "notes":
            from unbidden.contracts.events import EventType

            last = int(store.last_seq() or 0) if hasattr(store, "last_seq") else 0
            events = store.events(after=max(0, last - 400), limit=400)
            kept = [
                e
                for e in events
                if e.type in (EventType.NOTE, EventType.PROPOSAL_PUBLISHED, EventType.MERGED, EventType.DEPLOYED,
                              EventType.ASK_OPENED, EventType.ASK_ANSWERED, EventType.OPPORTUNITY_OPENED)
            ]  # fmt: skip
            if not kept:
                return "nothing said yet"
            return "\n".join(f"{e.ts:%Y-%m-%d %H:%M} {e.type.value}: {_said(e.payload)}"[:200] for e in kept[-25:])
        if topic == "proposals":
            from unbidden.contracts.experiment import Proposal

            proposals = store.list("proposals", Proposal)
            if not proposals:
                return "no proposals yet"
            return "\n".join(
                f"{p.opportunity_id} {p.status.value} branch {p.branch}" + (f" pr {p.pr.url}" if p.pr else "")
                for p in proposals[-20:]
            )
        if topic == "spend":
            from unbidden.brain.spend import summarize

            rows = self.source.spend_rows()
            if not rows:
                return "no remote model calls recorded"
            by_purpose = summarize(rows, "purpose")
            total = sum(float(v.get("usd", 0.0)) for v in by_purpose.values())
            lines = [f"total US${total:.4f} over {len(rows)} calls"]
            lines += [
                f"{k}: {int(v.get('calls', 0))} calls, US${float(v.get('usd', 0.0)):.4f}" for k, v in by_purpose.items()
            ]
            return "\n".join(lines)
        if topic == "connections":
            from unbidden.connect.registry import COLLECTION
            from unbidden.contracts.connection import Connection

            connections = store.list(COLLECTION, Connection)
            if not connections:
                return "no connections recorded yet"
            return "\n".join(
                f"{c.id} {c.state.value}: {c.next_step or c.check_detail or ''}"[:200] for c in connections
            )
        return "no such topic"

    def _world(self, kind: str) -> str:
        from unbidden.contracts.world import WorldModel

        world = self.source.store.get("world", "world", WorldModel)
        if world is None:
            return "no map yet (unbidden map, or the agent's first cycle)"
        if kind == "summary":
            counts: dict[str, int] = {}
            for r in world.resources.values():
                counts[r.kind] = counts.get(r.kind, 0) + 1
            return f"map of {world.rev[:12]}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        if kind == "services":
            return "\n".join(
                f"{r.name} ({r.kind}): image {r.attributes.get('image')}, ports {r.attributes.get('ports')}"
                for r in world.resources.values() if r.kind in ("service", "database")
            ) or "no services"  # fmt: skip
        if kind == "tables":
            return (
                "\n".join(
                    f"{r.name}: ~{r.attributes.get('rows_estimate', '?')} rows, "
                    f"{len(r.attributes.get('indexes') or [])} indexes"
                    for r in world.of_kind("table")
                )
                or "no tables"
            )
        if kind == "endpoints":
            names = sorted(r.name for r in world.of_kind("endpoint"))
            return (
                "\n".join(names[:80]) + (f"\n… {len(names) - 80} more" if len(names) > 80 else "")
                if names
                else "no endpoints"
            )
        if kind == "blind_spots":
            return "\n".join(f"{b.what}: {b.why}" for b in world.blind_spots) or "no blind spots"
        return "no such kind"

    def _read_file(self, repo: Path, path: str, start: int, end: int) -> str:
        if path.startswith(("/", "~")) or ".." in path.split("/"):
            return "paths are relative to the repository"
        end = min(end, start + 199)
        text = _git(repo, "show", f"HEAD:{path}")
        if not text:
            return f"no file {path} at HEAD"
        lines = text.splitlines()[start - 1 : end]
        return "\n".join(f"{start + i}: {line}" for i, line in enumerate(lines)) or "empty range"


def _said(payload: dict[str, Any]) -> str:
    return str(payload.get("text") or payload.get("title") or payload.get("url") or "")


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    return (out.stdout or "")[:MAX_OUTPUT]


class AgentPlanner:
    """The tool loop: the model reads with the tools, then answers. Nothing it does reaches the canvas."""

    name = "agent"

    def __init__(self, brain: Any) -> None:
        self.brain = brain

    async def run(
        self,
        text: str,
        tools: AgentTools,
        history: list[ChatMessage],
        emit: Emit,
        cancelled: threading.Event,
        correlation: str,
        *,
        cancelled_text: str,
        rounds_text: str,
        empty_text: str,
    ) -> tuple[str, list[ChatToolCall], list[ToolResult]]:
        workspace = f"{tools.source.name} ({tools.source.mode})"
        system = SYSTEM.format(workspace=workspace, language=language_name())
        messages = [Message(role="system", content=system, source="prompt")]
        for m in history[-6:]:
            if m.role in ("user", "assistant") and m.content:
                messages.append(Message(role=m.role, content=m.content[:2000], source="prompt"))
        messages.append(Message(role="user", content=text, source="prompt"))
        calls: list[ChatToolCall] = []
        results: list[ToolResult] = []
        for round_no in range(ROUNDS + 1):
            if cancelled.is_set():
                return cancelled_text, calls, results
            emit("state", {"state": "thinking"})
            last = round_no == ROUNDS
            if last:
                messages.append(
                    Message(
                        role="user",
                        content=f"No more tool calls: answer now, in {language_name()}, from what the tools "
                        "returned, and say what you did not get to read.",
                        source="prompt",
                    )
                )
            response = await self.brain.complete(
                LLMRequest(
                    purpose=PURPOSE,
                    tier=Tier.CODE,
                    messages=messages,
                    tools=[] if last else tool_specs(),
                    tool_choice="auto",
                    max_tokens=900,
                    correlation_id=correlation,
                )
            )
            if not response.tool_calls:
                return response.content.strip() or empty_text, calls, results
            messages.append(
                Message(
                    role="assistant", content=response.content or "", source="prompt", tool_calls=response.tool_calls
                )
            )
            for call in response.tool_calls:
                emit("state", {"state": "reading", "detail": call.name})
                emit("tool_call", {"id": call.id, "name": call.name, "arguments": call.arguments})
                result, label = tools.call(call.name, call.arguments)
                calls.append(ChatToolCall(id=call.id, name=call.name, arguments=call.arguments))
                results.append(result)
                emit("tool_result", result.model_dump(mode="json"))
                content = (
                    (result.data or {}).get("text") if result.ok else (result.error.detail if result.error else "")
                )
                messages.append(Message(role="tool", content=str(content)[:4000], source=label, tool_call_id=call.id))  # type: ignore[arg-type]
        return rounds_text, calls, results
