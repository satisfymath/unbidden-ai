"""Local models through Ollama's native API, which exposes the `think` control the OpenAI shim does not."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from unbidden.brain.providers import ProviderError, ProviderThrottled
from unbidden.contracts.llm import LLMRequest, LLMResponse, Message, ToolCall, Usage

# With thinking off, some builds leave end-of-turn tokens in the content.
_TRAILING_SPECIAL = re.compile(r"(?:\s*<\|[a-z_]+\|>)+\s*$")


def _message(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}} for c in m.tool_calls]
    return out


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str, *, num_ctx: int = 32768, keep_alive: str = "30m", timeout_s: float = 1800) -> None:
        self._client = httpx.AsyncClient(base_url=host.rstrip("/"), timeout=timeout_s)
        self._num_ctx = num_ctx
        self._keep_alive = keep_alive

    async def show(self, model: str) -> dict[str, Any]:
        response = await self._client.post("/api/show", json={"model": model})
        response.raise_for_status()
        return response.json()

    async def chat(self, request: LLMRequest, *, model: str, think: str | None) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": [_message(m) for m in request.messages],
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
                "num_ctx": self._num_ctx,
            },
        }
        if think is not None:
            body["think"] = False if think == "off" else think
        if request.tools:
            body["tools"] = [
                {"type": "function", "function": t.model_dump(include={"name", "description", "parameters"})}
                for t in request.tools
            ]
        if request.response_schema is not None:
            body["format"] = request.response_schema
        started = time.monotonic()
        try:
            response = await self._client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama unreachable: {exc}") from exc
        if response.status_code == 429:
            raise ProviderThrottled("ollama is busy (429)")
        if response.status_code >= 400:
            raise ProviderError(f"ollama {response.status_code}: {response.text[:500]}")
        data = response.json()
        message = data.get("message", {})
        content = message.get("content") or ""
        cleaned = _TRAILING_SPECIAL.sub("", content)
        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"tool {fn.get('name')} arguments are not JSON") from exc
            calls.append(ToolCall(name=fn.get("name", ""), arguments=args))
        return LLMResponse(
            content=cleaned,
            tool_calls=calls,
            thinking=message.get("thinking"),
            done_reason=data.get("done_reason"),
            lenient=cleaned != content,
            usage=Usage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                duration_s=time.monotonic() - started,
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
