"""An investigation is a bounded loop: one tool call per step, every call checked and recorded, a hypothesis at the end.

Tools only read: git history and diffs, files at a version, a search, and the service's recent errors (through a
log capability Forge built, when one is usable). The hypothesis's confidence is capped by its evidence level.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.common import CONFIDENCE_FLOOR, Contract, EvidenceLevel, capped_confidence, new_id, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.contracts.llm import LLMRequest, Message, Tier, ToolCall, ToolSpec
from unbidden.guardian import injection
from unbidden.guardian.policy import PolicyEngine
from unbidden.store import Store

MAX_STEPS = 10
MAX_OUTPUT = 6000
Mechanism = Literal[
    "code_change_raises",
    "dependency_change",
    "configuration_change",
    "schema_or_migration",
    "resource_exhaustion",
    "external_dependency",
    "unknown",
]


class GitLog(BaseModel):
    """Commits between the last healthy version and the failed one."""


class GitDiff(BaseModel):
    """The code changes between the two versions, optionally for one path."""

    path: str | None = Field(default=None, description="limit the diff to this file or directory")


class ReadFile(BaseModel):
    """A file as it is in the failed version."""

    path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=200, ge=1)


class Grep(BaseModel):
    """Search the failed version's code for a literal text."""

    text: str = Field(min_length=2, max_length=80)


class ServiceErrors(BaseModel):
    """The most recent error lines and tracebacks the service wrote."""

    service: str = Field(default="backend")


class Finish(BaseModel):
    """The hypothesis that ends the investigation."""

    statement: str = Field(max_length=600)
    mechanism: Mechanism
    evidence: list[str] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)


TOOLS: dict[str, tuple[type[BaseModel], str]] = {
    "git_log": (GitLog, "List the commits between the last healthy version and the failed one."),
    "git_diff": (GitDiff, "Show what changed between the two versions."),
    "read_file": (ReadFile, "Read a file of the failed version, by line range."),
    "grep": (Grep, "Search the failed version for a literal text."),
    "service_errors": (ServiceErrors, "Read the service's most recent errors and tracebacks."),
    "finish": (Finish, "End with one hypothesis and its evidence."),
}


class Hypothesis(Contract):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    subject: str  # what was investigated, e.g. "deploy 3 (32ef175)"
    statement: str
    mechanism: str
    evidence: list[str]
    confidence_claimed: float
    confidence: float  # capped by the evidence level
    evidence_level: EvidenceLevel = EvidenceLevel.REASONABLE_SUSPICION
    steps: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    # Set by code, not by the model: text that tried to instruct the model was read, or cited evidence was never read.
    injection: list[dict[str, str]] = Field(default_factory=list)
    unsupported_evidence: list[str] = Field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    return (out.stdout or out.stderr)[:MAX_OUTPUT]


@dataclass
class Investigation:
    repo: Path
    brain: Brain
    store: Store
    mandate: Mandate
    good: str
    bad: str
    incident: str
    subject: str
    log: Callable[[str], None] = print
    steps: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    read: list[str] = field(default_factory=list[str])
    hits: list[dict[str, str]] = field(default_factory=list[dict[str, str]])

    def _services(self) -> list[str]:
        from unbidden.observe.compose import load_compose

        compose = load_compose(self.repo, self.bad)
        return sorted(compose.services) if compose else []

    def _service_errors(self, service: str) -> str:
        out = subprocess.run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(self.repo),
                "logs",
                "--no-log-prefix",
                "--tail",
                "400",
                service,
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
        keep: list[str] = []
        for i, line in enumerate(out):
            if re.search(r"Traceback|Error|Exception| 5\d\d ", line):
                keep.extend(out[max(0, i - 1) : i + 3])
        return "\n".join(dict.fromkeys(keep))[-MAX_OUTPUT:] or "no error lines in the last 400"

    def run_tool(self, call: ToolCall) -> str:
        model, _ = TOOLS[call.name]
        args = model.model_validate(call.arguments)
        capability = "runtime.read" if call.name == "service_errors" else "repo.read"
        verdict = PolicyEngine(self.mandate).evaluate(ActionRequest(capability=capability, purpose=call.name))
        if not verdict.allowed:
            return f"refused by policy: {'; '.join(verdict.reasons)}"
        match args:
            case GitLog():
                return _git(self.repo, "log", "--format=%h %s (%an)", f"{self.good}..{self.bad}") or "no commits"
            case GitDiff(path=path):
                return _git(self.repo, "diff", f"{self.good}..{self.bad}", *(["--", path] if path else []))
            case ReadFile(path=path, start_line=start, end_line=end):
                lines = _git(self.repo, "show", f"{self.bad}:{path}").splitlines()[start - 1 : end]
                return "\n".join(f"{start + i}: {ln}" for i, ln in enumerate(lines)) or "empty or missing"
            case Grep(text=text):
                return _git(self.repo, "grep", "-n", "-F", text, self.bad) or "no match"
            case ServiceErrors(service=service):
                return self._service_errors(service)
            case _:
                return "unknown tool"

    async def run(self) -> Hypothesis | None:
        prompt = load_prompt("research_system")
        tools = [ToolSpec.from_model(name, desc, model) for name, (model, desc) in TOOLS.items()]
        messages = [
            Message(
                role="system",
                source="prompt",
                content=prompt.render(
                    incident=self.incident,
                    good=self.good[:12],
                    bad=self.bad[:12],
                    services=", ".join(self._services()) or "unknown",
                ),
            ),
            Message(role="user", content="Begin the investigation.", source="prompt"),
        ]
        for step in range(MAX_STEPS):
            try:
                response = await self.brain.complete(
                    LLMRequest(
                        purpose="research.step",
                        tier=Tier.LOCAL,
                        messages=messages,
                        tools=tools,
                        tool_choice="required",
                        max_tokens=1500,
                        prompt_sha256=prompt.sha256,
                    )
                )
            except (BrainError, ProviderError) as exc:
                self.log(f"investigation stopped: {exc}")
                return None
            call = response.tool_calls[0]
            if call.name == "finish":
                return self._conclude(Finish.model_validate(call.arguments))
            output = self.run_tool(call)
            self.read.append(output[:MAX_OUTPUT])
            for hit in injection.scan(output[:MAX_OUTPUT]):
                self.hits.append({"tool": call.name, "kind": hit.kind, "excerpt": hit.excerpt})
            self.steps.append(
                {"step": step + 1, "tool": call.name, "arguments": call.arguments, "output_chars": len(output)}
            )
            self.log(f"investigating: {call.name}({json.dumps(call.arguments)[:80]})")
            messages += [
                Message(role="assistant", content=response.content or "", tool_calls=[call], source="repo"),
                Message(
                    role="tool",
                    content=injection.fence(call.name, output[:MAX_OUTPUT]),
                    tool_call_id=call.id,
                    source="runtime" if call.name == "service_errors" else "repo",
                ),
            ]
        self.log(f"investigation ended after {MAX_STEPS} steps without a hypothesis")
        return None

    def _conclude(self, finish: Finish) -> Hypothesis:
        level = EvidenceLevel.REASONABLE_SUSPICION
        missing = injection.unsupported(finish.evidence, self.read)
        confidence = capped_confidence(finish.confidence, level)
        if self.hits or missing:
            # A conclusion that read an attempt to steer it, or cites what it never read, is not trusted by code.
            confidence = CONFIDENCE_FLOOR
        hypothesis = Hypothesis(
            subject=self.subject,
            statement=finish.statement,
            mechanism=finish.mechanism,
            evidence=finish.evidence,
            confidence_claimed=finish.confidence,
            confidence=confidence,
            evidence_level=level,
            steps=self.steps,
            injection=self.hits,
            unsupported_evidence=missing,
        )
        if self.hits:
            self.store.append_event(
                Event(
                    type=EventType.POLICY_DENIED,
                    actor="guardian",
                    entity_id=hypothesis.id,
                    payload={"control": "untrusted content tried to instruct the model", "hits": self.hits[:10]},
                )
            )
        self.store.put("hypotheses", hypothesis)
        self.store.append_event(
            Event(
                type=EventType.HYPOTHESIS_RECORDED,
                actor="research",
                entity_id=hypothesis.id,
                payload={
                    "subject": self.subject,
                    "statement": finish.statement,
                    "mechanism": finish.mechanism,
                    "confidence": hypothesis.confidence,
                    "steps": len(self.steps),
                },
            )
        )
        return hypothesis
