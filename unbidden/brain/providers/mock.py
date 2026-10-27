"""Deterministic provider for tests and offline runs: answers each purpose from a registered script."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from unbidden.contracts.llm import LLMRequest, LLMResponse, ToolCall, Usage

Answer = LLMResponse | dict[str, Any] | str | ToolCall
Script = Callable[[LLMRequest], Answer] | Answer


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self._scripts: dict[str, deque[Script]] = defaultdict(deque)
        self._fallback: dict[str, Script] = {}
        self.requests: list[LLMRequest] = []

    def script(self, purpose: str, *answers: Script, repeat: bool = False) -> None:
        """Queue answers for a purpose; with repeat=True the last one keeps answering."""
        self._scripts[purpose].extend(answers)
        if repeat and answers:
            self._fallback[purpose] = answers[-1]

    async def chat(self, request: LLMRequest, *, model: str, think: str | None) -> LLMResponse:
        self.requests.append(request)
        queue = self._scripts.get(request.purpose)
        if queue:
            answer = queue.popleft()
        elif request.purpose in self._fallback:
            answer = self._fallback[request.purpose]
        else:
            raise LookupError(f"mock has no answer scripted for {request.purpose!r}")
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, LLMResponse):
            return answer
        if isinstance(answer, ToolCall):
            return LLMResponse(tool_calls=[answer], done_reason="stop", usage=Usage(completion_tokens=10))
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return LLMResponse(content=content, done_reason="stop", usage=Usage(prompt_tokens=100, completion_tokens=20))
