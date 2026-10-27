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


Source = Literal["prompt", "repo", "runtime", "database", "synthetic"]


class ContentLabel(StrEnum):
    """What a message holds, from least to most restricted. A request carries its most restricted label."""

    INSTRUCTIONS = "instructions"  # unbidden's own prompts
    SYNTHETIC = "synthetic"  # produced by the privacy bridge: renamed and verified
    PUBLIC_CODE = "public_code"  # tracked files of a repository GitHub confirms is public
    PRIVATE_CODE = "private_code"  # tracked files of any other repository, and anything of unknown origin
    PRODUCTION_DATA = "production_data"  # logs, HTTP responses, database rows, personal data
    SECRET = "secret"  # credentials, keys, passwords, .env content

    @property
    def rank(self) -> int:
        return list(ContentLabel).index(self)


class Message(Contract):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    # Where the content came from, declared by whoever built it. None means unknown, and unknown is treated as
    # private code: a caller that forgets to say errs on the side that never leaves the machine.
    source: Source | None = None
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
    expect_files: bool = False  # the answer must hold `# file:` blocks
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
    route_reason: str | None = None  # why this model served the call
    created_at: datetime = Field(default_factory=utc_now)
