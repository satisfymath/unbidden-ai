"""Any OpenAI-compatible chat endpoint: Meta's Model API (Muse Spark, Muse Code) and hosting partners.

The API key is read from the environment at send time, after the router's egress gate allowed the payload,
so a key never travels with a request object, an event or a log line.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from unbidden.brain.providers import ProviderError, ProviderRejected, ProviderThrottled
from unbidden.contracts.llm import LLMRequest, LLMResponse, Message, ToolCall, Usage
from unbidden.guardian.credentials import broker


def _message(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in m.tool_calls
        ]
    if m.tool_call_id is not None:
        out["tool_call_id"] = m.tool_call_id
    return out


REQUIRED_TOOL_RULE = "You must answer by calling exactly one of the tools. Do not answer in plain text."


class OpenAICompatProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        key_env: str,
        *,
        required_tool_choice: bool = True,
        timeout_s: float = 300,
    ) -> None:
        self.name = name
        # Meta's API accepts only tool_choice="auto"; "required" then becomes an instruction, and the router
        # still rejects an answer without a tool call.
        self.required_tool_choice = required_tool_choice
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s)

    @property
    def host(self) -> str:
        return httpx.URL(self.base_url).host

    def has_key(self) -> bool:
        return broker().has(self.key_env)

    def _headers(self) -> dict[str, str]:
        key = broker().get(self.key_env, "model.remote")
        if not key:
            raise ProviderError(f"{self.key_env} is not set")
        return {"Authorization": f"Bearer {key}"}

    def body(self, request: LLMRequest, *, model: str, think: str | None, strict: bool = True) -> dict[str, Any]:
        messages = [_message(m) for m in request.messages]
        tool_choice = request.tool_choice
        if request.tools and tool_choice == "required" and not self.required_tool_choice:
            tool_choice = "auto"
            messages.append({"role": "system", "content": REQUIRED_TOOL_RULE})
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if think is not None and think != "off":
            body["reasoning_effort"] = think
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                        **({"strict": True} if strict else {}),
                    },
                }
                for t in request.tools
            ]
            body["tool_choice"] = tool_choice
            body["parallel_tool_calls"] = False
        if request.response_schema is not None:
            body["response_format"] = (
                {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": request.response_schema, "strict": True},
                }
                if strict
                else {"type": "json_object"}
            )
        return body

    async def list_models(self) -> list[str]:
        response = await self._client.get("/models", headers=self._headers())
        response.raise_for_status()
        return sorted(m["id"] for m in response.json().get("data", []))

    async def chat(self, request: LLMRequest, *, model: str, think: str | None) -> LLMResponse:
        try:
            return await self._send(self.body(request, model=model, think=think))
        except ProviderRejected:
            # A grammar that cannot express the schema rejects the strict form; the router still validates
            # the answer against the full schema, so a non-strict request loses nothing but a guarantee.
            return await self._send(self.body(request, model=model, think=think, strict=False))

    async def _send(self, body: dict[str, Any]) -> LLMResponse:
        started = time.monotonic()
        try:
            response = await self._client.post("/chat/completions", json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} unreachable: {exc}") from exc
        if response.status_code == 429:
            raise ProviderThrottled(f"{self.name} throttled the call (429)")
        if response.status_code == 400:
            raise ProviderRejected(f"{self.name} 400: {response.text[:500]}")
        if response.status_code >= 400:
            raise ProviderError(f"{self.name} {response.status_code}: {response.text[:500]}")
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderError(f"tool {fn.get('name')} arguments are not JSON") from exc
            calls.append(ToolCall(id=raw.get("id") or fn.get("name", "call"), name=fn.get("name", ""), arguments=args))
        usage = data.get("usage") or {}
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            thinking=message.get("reasoning_content") or message.get("reasoning"),
            done_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                duration_s=time.monotonic() - started,
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
