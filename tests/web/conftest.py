from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from unbidden.web.actions import Actions
from unbidden.web.chat import ChatService
from unbidden.web.presentation import PresentationStore
from unbidden.web.server import App, WebServer
from unbidden.web.sources import Source, demo

pytestmark = pytest.mark.unit

TOKEN = "test-token-0123456789"


class Client:
    """httpx against the running server, with the session token and the right Host."""

    def __init__(self, server: WebServer, sid: str) -> None:
        self.base = f"http://127.0.0.1:{server.port}"
        self.sid = sid
        self.http = httpx.Client(base_url=self.base, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)

    def ws(self, path: str) -> str:
        return f"/api/ws/{self.sid}{path}"

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.http.get(self.ws(path) if path.startswith("/") and not path.startswith("/api") else path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> httpx.Response:
        return self.http.post(self.ws(path) if not path.startswith("/api") else path, json=body, **kw)

    def put(self, path: str, body: Any) -> httpx.Response:
        return self.http.put(self.ws(path), json=body)

    def delete(self, path: str) -> httpx.Response:
        return self.http.delete(self.ws(path))

    def sse(
        self,
        path: str,
        body: Any = None,
        *,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        limit_events: int = 200,
    ) -> list[tuple[str, str | None, Any]]:
        out: list[tuple[str, str | None, Any]] = []
        with self.http.stream(method, self.ws(path), json=body, headers=headers or {}, timeout=20) as r:
            event, id_, data = "message", None, ""
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("id:"):
                    id_ = line[3:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                elif line == "":
                    if data:
                        out.append((event, id_, json.loads(data)))
                    event, id_, data = "message", None, ""
                    if len(out) >= limit_events or (out and out[-1][0] in ("done", "closed", "error")):
                        break
        return out


def make_server(sources: list[Source], tmp: Path, brain_for: Any = None) -> WebServer:
    presentation = PresentationStore(tmp / "presentation.db")
    chat = ChatService(presentation, brain_for or (lambda _s: None))
    app = App(sources, presentation, token=TOKEN, host="127.0.0.1", port=0, chat=chat, actions=Actions())
    server = WebServer(app, "127.0.0.1", 0)
    app.port = server.port
    app.origins = {f"http://127.0.0.1:{server.port}", f"http://localhost:{server.port}"}
    app.hosts = {f"127.0.0.1:{server.port}", f"localhost:{server.port}"}
    server.start()
    return server


@pytest.fixture
def demo_source() -> Source:
    src = demo()
    src.streams = False  # tests want a stream that ends
    return src


@pytest.fixture
def server(demo_source: Source, tmp_path: Path) -> Iterator[WebServer]:
    srv = make_server([demo_source], tmp_path)
    yield srv
    srv.stop()


@pytest.fixture
def client(server: WebServer, demo_source: Source) -> Client:
    return Client(server, demo_source.id)


@pytest.fixture(autouse=True)
def spanish_chat(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The dashboard is Spanish, and so are these tests' expectations: the chat answers in Spanish here."""
    from unbidden import i18n

    monkeypatch.setenv("UNBIDDEN_LANG", "es")
    i18n.clear()
    yield
    i18n.clear()
