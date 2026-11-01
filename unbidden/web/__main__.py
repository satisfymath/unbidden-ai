"""`python -m unbidden.web`: the local web workspace.

    uv run python -m unbidden.web --demo
    uv run python -m unbidden.web --record docs/bench/stage9-demo/DEMO-B-1 \
        --record docs/bench/stage10-revalidation/v4-f9fe965/fst-f9fe965.json
    uv run python -m unbidden.web --workspace ~/unbidden-fe-dev/sample

Prints one URL with the session token. Binds the loopback address only.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any

from unbidden.web.actions import Actions
from unbidden.web.chat import ChatService
from unbidden.web.presentation import PresentationStore
from unbidden.web.server import App, WebServer, free_port
from unbidden.web.sources import Source, SourceError, demo, historical, live

DEV_ORIGINS = ["http://127.0.0.1:5174", "http://localhost:5174"]


def web_home() -> Path:
    from unbidden.brain.spend import home

    return home() / "web"


def ollama_reachable(base_url: str) -> bool:
    from unbidden.web.sources import local_reachable

    return local_reachable(base_url)


def make_brain_for(planner: str, state_dir: Path, *, shared: Any | None = None) -> Any:
    """A Brain per source, with the web process's own store for its records. No precondition on Ollama: the Brain
    itself decides whether a call may go to Meta's API (the mandate's option and the key the broker holds) and
    finds out on the call whether the local server answers. A source whose option offers no route at all (no key
    and the local server down) still gets a Brain: its refusal carries the router's reason into the message.
    `shared` (the agent serving its own dashboard) is a Brain used for every live source instead: one store, one
    egress record, one monthly cap check in the same process as the engine."""
    from unbidden.brain.router import Brain
    from unbidden.brain.spend import SpendLedger
    from unbidden.config import load_config
    from unbidden.contracts.guardian import Mandate
    from unbidden.runtime import build_providers, resolve_local_model
    from unbidden.store import Store
    from unbidden.workspace import default_mandate

    cache: dict[str, Any] = {}
    lock = threading.Lock()

    def brain_for(source: Source) -> Any | None:
        if planner == "rule":
            return None
        if shared is not None and source.mode == "live":
            return shared
        with lock:
            if source.id in cache:
                return cache[source.id]
            config = source.config or load_config(None)
            mandate = source.mandate or Mandate.model_validate(default_mandate(source.name, None)["mandate"])
            local = config.providers.get("ollama")
            local_up = local is not None and ollama_reachable(local.base_url)
            if local_up:
                try:
                    resolve_local_model(config)
                except Exception as exc:  # no installed model fits: the provider will say so on the first call
                    print(f"local model: {exc}", file=sys.stderr)
            elif mandate.models.local_inference != "deny" and planner == "brain":
                print(f"{source.id}: no local model server answers; remote calls follow the mandate", file=sys.stderr)
            # A chat turn tolerates a few rejected tool calls from a small local model; the engine's default (one
            # repair) is tuned for its own, more constrained purposes. This copy is the web process's alone.
            config = config.model_copy(deep=True)
            config.brain.max_repairs = max(config.brain.max_repairs, 3)
            safe = "".join(c if c.isalnum() else "_" for c in source.id)
            store = Store(state_dir / f"{safe}-state.db")  # see sources.apart_store_path: the CLI reads it back
            brain = Brain(
                config, build_providers(config), store, mandate, killswitch=source.killswitch(), spend=SpendLedger()
            )
            if source.mode == "live" and source.store is not None:
                cached = source.store.get_value("repo_visibility") or {}  # what the engine last confirmed; no network
                brain.repo_public = bool(cached.get("public"))
            cache[source.id] = brain
            return brain

    return brain_for


def build(args: argparse.Namespace) -> tuple[App, list[Source]]:
    sources: list[Source] = []
    if args.demo or not (args.record or args.workspace):
        sources.append(demo())
    for path in args.record or []:
        sources.append(historical(Path(path)))
    for path in args.workspace or []:
        src = live(Path(path))
        if any(s.id == src.id for s in sources):
            src.id = f"{src.id}:{len(sources)}"
        sources.append(src)
    state_dir = Path(args.state_dir) if args.state_dir else web_home()
    state_dir.mkdir(parents=True, exist_ok=True)
    presentation = PresentationStore(state_dir / "presentation.db")
    chat = ChatService(presentation, make_brain_for(args.planner, state_dir))
    token = args.token or secrets.token_urlsafe(24)
    port = free_port(args.host, args.port)
    if port != args.port:
        print(f"port {args.port} is taken; using {port} (nothing was stopped)", file=sys.stderr)
    app = App(
        sources,
        presentation,
        token=token,
        host=args.host,
        port=port,
        chat=chat,
        actions=Actions(),
        dev_origins=DEV_ORIGINS if args.dev else None,
    )
    return app, sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m unbidden.web", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--demo", action="store_true", help="serve the demo fixtures")
    parser.add_argument("--record", action="append", help="a published record directory or revalidation file")
    parser.add_argument("--workspace", action="append", help="a workspace repository to read live (read-only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dev", action="store_true", help="accept the Vite dev server's origin")
    parser.add_argument("--planner", choices=["auto", "rule", "brain"], default="auto")
    parser.add_argument("--state-dir", help="where the canvas and the conversation are kept (default ~/.unbidden/web)")
    parser.add_argument("--no-tick", action="store_true", help="demo: do not append a synthetic event every 20 s")
    parser.add_argument("--open", action="store_true", help="open the browser")
    parser.add_argument("--log", action="store_true", help="log every request")
    parser.add_argument(
        "--token",
        default=os.environ.get("UNBIDDEN_WEB_TOKEN"),
        help="a fixed session token (tests and scripts); by default a random one is generated",
    )
    parser.add_argument(
        "--announce",
        metavar="PATH",
        help="write where this dashboard is (url, port, pid; mode 600) once the port is bound, for `unbidden ui`",
    )
    args = parser.parse_args(argv)
    try:
        app, sources = build(args)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.log:
        from unbidden.web import server as srv

        srv.app_log_enabled = True
    server = WebServer(app, args.host, app.port)
    announced: Path | None = None
    if args.announce:
        from unbidden.web.announce import announce

        announced = Path(args.announce)
        announce(announced, host=args.host, port=server.port, token=app.token, in_daemon=False)
        import signal

        def _term(_sig: int, _frame: Any) -> None:
            raise KeyboardInterrupt  # the same clean exit as ctrl-c: the announcement is withdrawn below

        signal.signal(signal.SIGTERM, _term)
    for s in sources:
        print(f"  {s.mode:<10} {s.id}  {' · '.join(s.notes)[:100]}", file=sys.stderr)
    print(f"\n  {server.url}\n", file=sys.stderr)
    if args.dev:
        print(f"  dev: open http://127.0.0.1:5174/?s={app.token} with `cd frontend && npm run dev`\n", file=sys.stderr)
    stop = threading.Event()
    demo_src = next((s for s in sources if s.mode == "demo"), None)
    if demo_src is not None and not args.no_tick:

        def tick() -> None:
            while not stop.wait(20):
                with demo_src.lock:
                    demo_src.ticker.tick()  # type: ignore[attr-defined]

        threading.Thread(target=tick, name="unbidden-web-demo-ticker", daemon=True).start()
    if args.open:
        import webbrowser

        webbrowser.open(server.url)
    server.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.stop()
        if announced is not None:
            from unbidden.web.announce import withdraw

            withdraw(announced)
    return 0


if __name__ == "__main__":
    sys.exit(main())
