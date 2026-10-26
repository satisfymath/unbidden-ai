from __future__ import annotations

import json

import httpx
import pytest

from unbidden.brain.providers import ProviderThrottled
from unbidden.brain.providers.openai_compat import OpenAICompatProvider
from unbidden.contracts.llm import LLMRequest, Message, Tier

pytestmark = pytest.mark.unit

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


def provider(handler: httpx.MockTransport, monkeypatch: pytest.MonkeyPatch) -> OpenAICompatProvider:
    monkeypatch.setenv("TEST_KEY", "k-123456")
    p = OpenAICompatProvider("meta", "https://api.meta.ai/v1", "TEST_KEY")
    p._client = httpx.AsyncClient(base_url=p.base_url, transport=handler)  # pyright: ignore[reportPrivateUsage]
    return p


def req() -> LLMRequest:
    return LLMRequest(
        purpose="t", tier=Tier.FRONTIER, messages=[Message(role="user", content="hi")], response_schema=SCHEMA
    )


async def test_strict_schema_then_fallback_on_400(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        assert request.headers["authorization"] == "Bearer k-123456"
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "unsupported schema"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    p = provider(httpx.MockTransport(handle), monkeypatch)
    response = await p.chat(req(), model="muse-spark-1.3", think="low")
    assert response.content == '{"a": 1}'
    assert response.usage.prompt_tokens == 7
    assert [b["response_format"]["type"] for b in bodies] == ["json_schema", "json_object"]  # type: ignore[index]
    assert bodies[0]["reasoning_effort"] == "low"


async def test_429_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    p = provider(httpx.MockTransport(lambda _: httpx.Response(429)), monkeypatch)
    with pytest.raises(ProviderThrottled):
        await p.chat(req(), model="m", think=None)


def test_host() -> None:
    assert OpenAICompatProvider("meta", "https://api.meta.ai/v1", "X").host == "api.meta.ai"


def test_required_tool_choice_becomes_an_instruction_when_unsupported() -> None:
    from unbidden.contracts.llm import ToolSpec

    p = OpenAICompatProvider("meta", "https://api.meta.ai/v1", "X", required_tool_choice=False)
    tool = ToolSpec(name="finish", description="d", parameters={"type": "object"})
    request = LLMRequest(
        purpose="t",
        tier=Tier.FRONTIER,
        messages=[Message(role="user", content="hi")],
        tools=[tool],
        tool_choice="required",
    )
    body = p.body(request, model="m", think=None)
    assert body["tool_choice"] == "auto"
    assert "exactly one of the tools" in body["messages"][-1]["content"]
