from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from unbidden.contracts.common import Contract, Cost, new_id, utc_now


class Tier(StrEnum):
    """Where a call may run. Only LOCAL ever sees private context."""

    LOCAL = "local"
    FRONTIER = "frontier"
    CODE = "code"

    @property
    def remote(self) -> bool:
        return self is not Tier.LOCAL


class ToolCall(Contract):
    id: str = Field(default_factory=lambda: new_id("call"))
    name: str
    arguments: dict[str, Any]


class Message(Contract):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    tool_call_id: str | None = None


class ToolSpec(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    parameters: dict[str, Any]

    @classmethod
    def from_model(cls, name: str, description: str, model: type[BaseModel]) -> ToolSpec:
        """Tool schemas are generated from the pydantic model that will validate the arguments."""
        schema = model.model_json_schema()
        schema.pop("title", None)
        return cls(name=name, description=description, parameters=schema)


class LLMRequest(Contract):
    purpose: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    tier: Tier
    messages: list[Message] = Field(min_length=1)
    tools: list[ToolSpec] = Field(default_factory=list[ToolSpec])
    tool_choice: Literal["auto", "required"] = "auto"
    response_schema: dict[str, Any] | None = None
    max_tokens: int = Field(default=1024, gt=0)
    temperature: float = 0.0
    prompt_sha256: str | None = None
    correlation_id: str | None = None

    @property
    def schema_only(self) -> bool:
        return self.response_schema is not None and not self.tools


class Usage(Contract):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_s: float = 0.0


class LLMResponse(Contract):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    thinking: str | None = None
    done_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    lenient: bool = False

    @property
    def truncated(self) -> bool:
        return self.done_reason == "length"


class ModelRun(Contract):
    id: str = Field(default_factory=lambda: new_id("run"))
    purpose: str
    tier: Tier
    provider: str
    model: str
    attempt: int
    ok: bool
    problem: str | None = None
    prompt_sha256: str | None = None
    egress_attempt_id: str | None = None
    usage: Usage
    cost: Cost
    correlation_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
