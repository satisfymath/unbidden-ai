"""One HTTP client per running event loop. A provider lives for the whole process while each chat turn, probe or
CLI command runs its own `asyncio.run(...)`: a connection pool opened on one loop fails on the next with "Event
loop is closed". Clients are keyed by the loop that uses them; `aclose()` closes the one of the current loop, and
every `asyncio.run` that borrows a long-lived Brain closes before it returns (`Brain.aclose`)."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Callable

import httpx


class ClientPerLoop:
    def __init__(self, make: Callable[[], httpx.AsyncClient]) -> None:
        self._make = make
        self._clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
            weakref.WeakKeyDictionary()
        )

    def current(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None:
            client = self._clients[loop] = self._make()
        return client

    async def aclose(self) -> None:
        client = self._clients.pop(asyncio.get_running_loop(), None)
        if client is not None:
            await client.aclose()
