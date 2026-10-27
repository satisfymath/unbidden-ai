from __future__ import annotations

from typing import Protocol, runtime_checkable

from unbidden.contracts.llm import LLMRequest, LLMResponse


class ProviderError(RuntimeError):
    """The provider answered with something unusable or failed outright."""


class ProviderThrottled(ProviderError):
    """HTTP 429. A throttled call says nothing about the model; it is retried later, never judged."""


class ProviderRejected(ProviderError):
    """HTTP 400: the request shape was refused (often a schema the provider's grammar cannot express)."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def chat(self, request: LLMRequest, *, model: str, think: str | None) -> LLMResponse: ...
