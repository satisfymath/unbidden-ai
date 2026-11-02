"""The dashboard served by the agent itself (`unbidden start --ui` / `unbidden watch --ui`): one process, one
store, one egress record and one monthly cap check. The server is a daemon thread beside the loop; actions open
their own short connections (`operate/decisions.py`); the chat uses the engine's own Brain. The dashboard lives as
long as the agent: `unbidden stop` ends both, closing the browser ends nothing."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from unbidden.workspace import Workspace


def serve(ws: Workspace, runtime: Any, *, host: str = "127.0.0.1", port: int = 8765, planner: str = "auto") -> Any:
    """Start the dashboard over this workspace inside the current process and announce it in `.unbidden/ui.json`.
    Returns the WebServer (call `.stop()`; `withdraw` the announcement after)."""
    from unbidden.web import announce
    from unbidden.web.__main__ import make_brain_for, web_home
    from unbidden.web.actions import Actions
    from unbidden.web.chat import ChatService
    from unbidden.web.presentation import PresentationStore
    from unbidden.web.server import App, WebServer, free_port
    from unbidden.web.sources import live

    if announce.alive(announce.ui_path(ws.dir)) is not None:
        raise RuntimeError("a dashboard is already served apart for this workspace (`unbidden ui --stop` ends it)")
    source = live(ws.repo)
    state_dir: Path = web_home()
    state_dir.mkdir(parents=True, exist_ok=True)
    presentation = PresentationStore(state_dir / "presentation.db")
    chat = ChatService(presentation, make_brain_for(planner, state_dir, shared=runtime.brain))
    chosen = free_port(host, port)
    app = App([source], presentation, token=secrets.token_urlsafe(24), host=host, port=chosen, chat=chat,
              actions=Actions())  # fmt: skip
    server = WebServer(app, host, chosen)
    server.start()
    announce.announce(announce.ui_path(ws.dir), host=host, port=server.port, token=app.token, in_daemon=True)
    return server


def close(ws: Workspace, server: Any) -> None:
    from unbidden.web import announce

    try:
        server.stop()
    finally:
        announce.withdraw(announce.ui_path(ws.dir))
