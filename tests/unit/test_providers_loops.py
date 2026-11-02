"""A provider outlives the event loops that use it: the chat runs each turn under its own `asyncio.run` on a Brain
cached per source. One HTTP client per loop, closed before the loop ends, or the second turn fails with
"Event loop is closed"."""

from __future__ import annotations

import asyncio
import gc
import json
import warnings

import httpx
import pytest

from unbidden.brain.providers.clients import ClientPerLoop
from unbidden.brain.providers.ollama import OllamaProvider
from unbidden.brain.providers.openai_compat import OpenAICompatProvider
from unbidden.contracts.llm import LLMRequest, Message, Tier

pytestmark = pytest.mark.unit


def _req() -> LLMRequest:
    return LLMRequest(purpose="t", tier=Tier.LOCAL, messages=[Message(role="user", content="hi")])


def _ollama_answer(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "message": {"content": f"ok {body['model']}"},
            "done_reason": "stop",
            "prompt_eval_count": 3,
            "eval_count": 2,
        },
    )


def _openai_answer(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3}},
    )


def test_two_loops_in_a_row_both_answer_and_leave_no_open_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """The report from fedora: the second chat question raised RuntimeError("Event loop is closed")."""
    monkeypatch.setenv("TEST_KEY", "k-123456")
    ollama = OllamaProvider("http://127.0.0.1:11434", transport=httpx.MockTransport(_ollama_answer))
    remote = OpenAICompatProvider(
        "meta", "https://api.meta.ai/v1", "TEST_KEY", transport=httpx.MockTransport(_openai_answer)
    )

    async def turn() -> tuple[str, str]:
        try:
            a = await ollama.chat(_req(), model="llama3.2:3b", think=None)
            b = await remote.chat(_req(), model="muse", think=None)
            return a.content, b.content
        finally:
            await ollama.aclose()
            await remote.aclose()

    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        assert asyncio.run(turn()) == ("ok llama3.2:3b", "ok")
        assert asyncio.run(turn()) == ("ok llama3.2:3b", "ok")
        gc.collect()


def test_a_loop_gets_one_client_and_closing_drops_it() -> None:
    made: list[httpx.AsyncClient] = []

    def make() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
        made.append(client)
        return client

    clients = ClientPerLoop(make)

    async def use() -> None:
        assert clients.current() is clients.current()
        await clients.aclose()
        assert made[-1].is_closed
        assert clients.current() is not made[0]  # a new one after closing, on the same loop

    asyncio.run(use())
    asyncio.run(use())
    assert len(made) == 4


async def test_the_brain_closes_every_provider_of_the_current_loop() -> None:
    from unbidden.brain.providers.mock import MockProvider
    from unbidden.brain.router import Brain
    from unbidden.config import load_config
    from unbidden.contracts.guardian import Mandate
    from unbidden.store import Store

    ollama = OllamaProvider("http://127.0.0.1:11434", transport=httpx.MockTransport(_ollama_answer))
    brain = Brain(load_config(), {"ollama": ollama, "mock": MockProvider()}, Store(None), Mandate(workspace="t"))
    await ollama.chat(_req(), model="m", think=None)
    client = ollama._client()  # pyright: ignore[reportPrivateUsage]
    await brain.aclose()  # a provider without aclose (the mock) is skipped
    assert client.is_closed
