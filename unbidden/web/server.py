"""The local server: loopback only, a session token on every API call, Host and Origin checked, static assets.

Standard library only (`http.server`), so installing the web workspace adds nothing to the engine's dependencies.
Four APIs kept apart: read (`/summary`, `/opportunities`, `/data`...), presentation (`/presentation`), chat
(`/chat`) and actions (`/actions`). Every handler takes a validated request and answers JSON; two answer SSE.
"""

from __future__ import annotations

import contextlib
import json
import mimetypes
import re
import secrets
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

from unbidden.contracts.experiment import Experiment, Proposal
from unbidden.contracts.opportunity import Opportunity
from unbidden.contracts.world import WorldModel
from unbidden.web import datasets
from unbidden.web.actions import Actions, mandate_view
from unbidden.web.chat import ChatService
from unbidden.web.contracts import SCHEMA, ActionRequestWeb, ChatRequest, DataRef, PresentationUpdate
from unbidden.web.presentation import PresentationStore, StaleVersion
from unbidden.web.sources import Source

STATIC = Path(__file__).parent / "static"
HEARTBEAT_S = 15.0
POLL_S = 1.0
COLLECTIONS = frozenset(
    {
        "opportunities",
        "experiments",
        "proposals",
        "decisions",
        "connections",
        "needs",
        "blocks",
        "actions",
        "acceptances",
        "goal_runs",
        "deployments",
        "deploy_verdicts",
        "capabilities",
        "stats_capabilities",
        "integrations",
        "model_runs",
        "egress",
        "holds",
        "approvals",
        "hypotheses",
        "experiment_specs",
    }
)


class HttpError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes
    params: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        if not self.body:
            raise HttpError(400, "a JSON body is required")
        try:
            return json.loads(self.body)
        except json.JSONDecodeError as exc:
            raise HttpError(400, f"invalid JSON: {exc.msg}") from exc

    def int_query(self, name: str, default: int, *, low: int = 0, high: int = 100_000) -> int:
        try:
            return max(low, min(high, int(self.query.get(name, default))))
        except ValueError as exc:
            raise HttpError(400, f"{name} must be an integer") from exc


@dataclass
class Response:
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None
    content_type: str = "application/json"


@dataclass
class Stream:
    """Server-sent events: `events` yields (event, id, data) triples until the client goes away."""

    events: Iterator[tuple[str, str | None, Any]]


Handler = Callable[[Request], Response | Stream]


def sse(event: str, data: Any, id_: str | None = None) -> tuple[str, str | None, Any]:
    return event, id_, data


class App:
    def __init__(
        self,
        sources: list[Source],
        presentation: PresentationStore,
        *,
        token: str,
        host: str,
        port: int,
        chat: ChatService,
        actions: Actions,
        dev_origins: list[str] | None = None,
        static_dir: Path = STATIC,
    ) -> None:
        if not sources:
            raise ValueError("at least one source")
        self.sources = {s.id: s for s in sources}
        self.presentation = presentation
        self.token = token
        self.host, self.port = host, port
        self.chat = chat
        self.actions = actions
        self.static_dir = static_dir
        own = f"http://{host}:{port}"
        self.origins = {own, own.replace("127.0.0.1", "localhost"), *(dev_origins or [])}
        self.hosts = {o.split("://", 1)[1] for o in self.origins}
        self.routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self._register()

    # Routing --------------------------------------------------------------------------------------------------

    def route(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")
        self.routes.append((method, regex, handler))

    def _register(self) -> None:
        r = self.route
        r("GET", "/api/session", self.session)
        r("GET", "/api/sources", self.list_sources)
        r("GET", "/api/datasets", lambda _: Response(body={"schema": SCHEMA, "datasets": datasets.catalogue()}))
        r("GET", "/api/ws/{sid}/summary", self.summary)
        r("GET", "/api/ws/{sid}/mandate", self.mandate)
        r("GET", "/api/ws/{sid}/opportunities", self.opportunities)
        r("GET", "/api/ws/{sid}/opportunities/{id}", self.opportunity)
        r("GET", "/api/ws/{sid}/experiments/{id}", self.experiment)
        r("GET", "/api/ws/{sid}/world", self.world)
        r("GET", "/api/ws/{sid}/collection/{name}", self.collection)
        r("GET", "/api/ws/{sid}/timeline", self.timeline)
        r("GET", "/api/ws/{sid}/events", self.events)
        r("GET", "/api/ws/{sid}/events/stream", self.events_stream)
        r("POST", "/api/ws/{sid}/data", self.data)
        r("GET", "/api/ws/{sid}/presentation", self.presentation_get)
        r("PUT", "/api/ws/{sid}/presentation", self.presentation_put)
        r("GET", "/api/ws/{sid}/presentation/history", self.presentation_history)
        r("POST", "/api/ws/{sid}/presentation/undo", self.presentation_undo)
        r("POST", "/api/ws/{sid}/presentation/redo", self.presentation_redo)
        r("GET", "/api/ws/{sid}/chat", self.chat_get)
        r("POST", "/api/ws/{sid}/chat", self.chat_post)
        r("DELETE", "/api/ws/{sid}/chat", self.chat_delete)
        r("POST", "/api/ws/{sid}/chat/cancel", self.chat_cancel)
        r("POST", "/api/ws/{sid}/actions", self.action)

    def source(self, req: Request) -> Source:
        sid = unquote(req.params["sid"])
        src = self.sources.get(sid)
        if src is None:
            raise HttpError(404, f"no workspace {sid!r}; see /api/sources")
        return src

    def dispatch(self, req: Request) -> Response | Stream:
        if req.path.startswith("/api/"):
            self._guard(req)
            for method, regex, handler in self.routes:
                m = regex.match(req.path)
                if m and method == req.method:
                    req.params = m.groupdict()
                    return handler(req)
            if any(regex.match(req.path) for _, regex, _ in self.routes):
                raise HttpError(405, "method not allowed")
            raise HttpError(404, "no such endpoint")
        if req.method != "GET":
            raise HttpError(405, "method not allowed")
        return self.static(req)

    def _guard(self, req: Request) -> None:
        host = req.headers.get("host", "")
        if host not in self.hosts:
            raise HttpError(403, f"host {host!r} is not this server")
        origin = req.headers.get("origin")
        if origin and origin not in self.origins:
            raise HttpError(403, "cross-origin request refused")
        auth = req.headers.get("authorization", "")
        given = (
            auth.removeprefix("Bearer ").strip()
            if auth.startswith("Bearer ")
            else req.headers.get("x-unbidden-session", "")
        )
        if not given or not secrets.compare_digest(given, self.token):
            raise HttpError(401, "missing or wrong session token (open the URL the server printed)")

    # Static ---------------------------------------------------------------------------------------------------

    def static(self, req: Request) -> Response:
        if not (self.static_dir / "index.html").exists():
            html = (
                "<!doctype html><meta charset=utf-8><title>Unbidden</title>"
                "<body style='font:15px system-ui;padding:32px'>"
                "<h1>Unbidden web</h1><p>The built assets are not here yet. In development run "
                "<code>cd frontend && npm run dev</code> and open the Vite URL with <code>?s=&lt;token&gt;</code>; "
                "for a distribution run <code>make web-build</code>.</p><p>API: <code>/api/session</code></p>"
            )
            return Response(body=None, raw=html.encode(), content_type="text/html; charset=utf-8")
        rel = req.path.lstrip("/") or "index.html"
        target = (self.static_dir / rel).resolve()
        if not str(target).startswith(str(self.static_dir.resolve())) or not target.is_file():
            target = self.static_dir / "index.html"
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        headers = {"Cache-Control": "no-cache" if target.name == "index.html" else "public, max-age=86400"}
        return Response(raw=target.read_bytes(), content_type=ctype, headers=headers)

    # Read API -------------------------------------------------------------------------------------------------

    def session(self, _: Request) -> Response:
        return Response(body={"schema": SCHEMA, "ok": True, "sources": self._sources_brief()})

    def _sources_brief(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "name": s.name,
                "mode": s.mode,
                "repo": str(s.repo) if s.repo else None,
                "streams": s.streams,
                "notes": s.notes,
            }
            for s in self.sources.values()
        ]

    def list_sources(self, _: Request) -> Response:
        return Response(body={"schema": SCHEMA, "sources": self._sources_brief()})

    def summary(self, req: Request) -> Response:
        src = self.source(req)
        try:
            return Response(body=src.summary())
        except Exception as exc:  # a workspace mid-write, or a record the viewer cannot read whole
            raise HttpError(503, f"the workspace could not be read: {type(exc).__name__}: {str(exc)[:200]}") from exc

    def mandate(self, req: Request) -> Response:
        src = self.source(req)
        return Response(
            body={
                "schema": SCHEMA,
                "mandate": mandate_view(src.mandate),
                "route": src.route_info(),
                "autonomy": src.autonomy_info(),
            }
        )

    def opportunities(self, req: Request) -> Response:
        src = self.source(req)
        offset, limit = req.int_query("offset", 0), req.int_query("limit", 50, low=1, high=500)
        status = req.query.get("status")
        with src.lock:
            opps = src.store.list("opportunities", Opportunity, status=status)
        opps.sort(key=lambda o: (-int(o.evidence_level), -o.priority_score, o.created_at))
        page = [
            o.model_dump(mode="json", exclude={"details"})
            | {
                "decision": (o.details.get("decision") or {}),
                "blocked": (o.details.get("blocked") or {}).get("why"),
                "experiment_id": (o.details.get("verdict") or {}).get("experiment_id")
                or o.details.get("experiment_id"),
            }
            for o in opps[offset : offset + limit]
        ]
        return Response(
            body={
                "schema": SCHEMA,
                "items": page,
                "total": len(opps),
                "offset": offset,
                "limit": limit,
                "provenance": src.provenance().model_dump(mode="json"),
            }
        )

    def opportunity(self, req: Request) -> Response:
        src = self.source(req)
        with src.lock:
            opp = src.store.get("opportunities", req.params["id"], Opportunity)
            if opp is None:
                raise HttpError(404, "no such opportunity")
            events = src.store.events(correlation_id=opp.id, limit=500)
            exp_id = (opp.details.get("verdict") or {}).get("experiment_id") or opp.details.get("experiment_id")
            experiment = src.store.get("experiments", str(exp_id), Experiment) if exp_id else None
            proposal = next((p for p in src.store.list("proposals", Proposal) if p.opportunity_id == opp.id), None)
        return Response(
            body={
                "schema": SCHEMA,
                "opportunity": opp.model_dump(mode="json"),
                "events": [e.model_dump(mode="json") for e in events],
                "experiment": _experiment_brief(experiment) if experiment else None,
                "proposal": proposal.model_dump(mode="json", exclude={"body_md"})
                | {"body_md": proposal.body_md[:20000]}
                if proposal
                else None,
                "provenance": src.provenance(scope=opp.id).model_dump(mode="json"),
            }
        )

    def experiment(self, req: Request) -> Response:
        src = self.source(req)
        with src.lock:
            exp = src.store.get("experiments", req.params["id"], Experiment)
        if exp is None:
            raise HttpError(404, "no such experiment")
        return Response(
            body={
                "schema": SCHEMA,
                "experiment": _experiment_brief(exp),
                "provenance": src.provenance(scope=exp.id).model_dump(mode="json"),
            }
        )

    def world(self, req: Request) -> Response:
        src = self.source(req)
        with src.lock:
            world = src.store.get("world", "world", WorldModel)
        if world is None:
            return Response(body={"schema": SCHEMA, "world": None, "note": "no world model in this workspace"})
        return Response(
            body={
                "schema": SCHEMA,
                "world": {
                    "rev": world.rev,
                    "updated_at": world.updated_at.isoformat(),
                    "resources": [r.model_dump(mode="json") for r in world.resources.values()][:2000],
                    "relations": [r.model_dump(mode="json") for r in world.current_relations()][:5000],
                    "blind_spots": [b.model_dump(mode="json") for b in world.blind_spots],
                },
                "provenance": src.provenance(scope=world.rev[:12]).model_dump(mode="json"),
            }
        )

    def collection(self, req: Request) -> Response:
        src = self.source(req)
        name = req.params["name"]
        if name not in COLLECTIONS:
            raise HttpError(404, f"no such collection; known: {', '.join(sorted(COLLECTIONS))}")
        offset, limit = req.int_query("offset", 0), req.int_query("limit", 50, low=1, high=500)
        with src.lock:
            conn = src.store._conn
            total = int(conn.execute("SELECT COUNT(*) FROM docs WHERE collection = ?", (name,)).fetchone()[0])
            rows = conn.execute(
                "SELECT doc FROM docs WHERE collection = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (name, limit, offset),
            ).fetchall()
        items = [json.loads(r[0]) for r in rows]
        for item in items:  # never a payload a browser should not hold whole
            item.pop("payload", None)
            if "body_md" in item:
                item["body_md"] = str(item["body_md"])[:20000]
        return Response(
            body={
                "schema": SCHEMA,
                "items": items,
                "total": total,
                "offset": offset,
                "limit": limit,
                "provenance": src.provenance(scope=name).model_dump(mode="json"),
            }
        )

    def timeline(self, req: Request) -> Response:
        src = self.source(req)
        offset, limit = req.int_query("offset", 0), req.int_query("limit", 200, low=1, high=2000)
        return Response(
            body={
                "schema": SCHEMA,
                "items": src.timeline[offset : offset + limit],
                "total": len(src.timeline),
                "offset": offset,
                "limit": limit,
                "freshness": src.freshness,
            }
        )

    def events(self, req: Request) -> Response:
        src = self.source(req)
        after, limit = req.int_query("after", 0), req.int_query("limit", 200, low=1, high=2000)
        with src.lock:
            events = src.store.events(after=after, correlation_id=req.query.get("correlation_id"), limit=limit)
            last = src.last_seq()
        return Response(
            body={
                "schema": SCHEMA,
                "items": [e.model_dump(mode="json") | {"mode": src.mode} for e in events],
                "last_seq": last,
                "freshness": src.freshness,
            }
        )

    def events_stream(self, req: Request) -> Stream:
        src = self.source(req)
        after = req.int_query("after", 0)
        last_id = req.headers.get("last-event-id")
        if last_id and last_id.isdigit():
            after = int(last_id)
        return Stream(self._event_iter(src, after))

    def _event_iter(self, src: Source, after: int) -> Iterator[tuple[str, str | None, Any]]:
        yield sse(
            "hello",
            {
                "last_seq": src.last_seq(),
                "freshness": src.freshness,
                "streams": src.streams,
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )
        last = after
        beat = time.monotonic()
        stale = False
        while True:
            try:
                with src.lock:
                    batch = src.store.events(after=last, limit=200)
                if stale:
                    stale = False
                    yield sse("recovered", {"last_seq": src.last_seq()})
                for e in batch:
                    last = e.seq or last
                    yield sse("engine", e.model_dump(mode="json") | {"mode": src.mode}, str(last))
            except Exception as exc:
                if not stale:
                    stale = True
                    yield sse("stale", {"reason": f"{type(exc).__name__}: {str(exc)[:160]}", "last_seq": last})
            if not src.streams:
                yield sse("closed", {"reason": "a historical record: nothing new will arrive", "last_seq": last})
                return
            if time.monotonic() - beat >= HEARTBEAT_S:
                beat = time.monotonic()
                yield sse("heartbeat", {"last_seq": last, "observed_at": datetime.now(UTC).isoformat()})
            time.sleep(POLL_S)

    def data(self, req: Request) -> Response:
        src = self.source(req)
        try:
            ref = DataRef.model_validate(req.json())
            result = datasets.resolve(src, ref)
        except ValidationError as exc:
            raise HttpError(422, _first_error(exc)) from exc
        except datasets.DatasetError as exc:
            raise HttpError(422, str(exc)) from exc
        return Response(body=result.model_dump(mode="json", by_alias=True))

    # Presentation API -----------------------------------------------------------------------------------------

    def presentation_get(self, req: Request) -> Response:
        src = self.source(req)
        doc = self.presentation.current(src.id)
        return Response(
            body=doc.model_dump(mode="json", by_alias=True) | {"history": self.presentation.history(src.id)}
        )

    def presentation_put(self, req: Request) -> Response:
        src = self.source(req)
        try:
            update = PresentationUpdate.model_validate(req.json())
            doc = self.presentation.save(src.id, update)
        except ValidationError as exc:
            raise HttpError(422, _first_error(exc)) from exc
        except StaleVersion as exc:
            raise HttpError(409, str(exc)) from exc
        return Response(
            body=doc.model_dump(mode="json", by_alias=True) | {"history": self.presentation.history(src.id)}
        )

    def presentation_history(self, req: Request) -> Response:
        src = self.source(req)
        return Response(
            body={"schema": SCHEMA, **self.presentation.history(src.id), "reasons": self.presentation.reasons(src.id)}
        )

    def presentation_undo(self, req: Request) -> Response:
        src = self.source(req)
        doc = self.presentation.undo(src.id)
        if doc is None:
            raise HttpError(409, "nothing to undo")
        return Response(
            body=doc.model_dump(mode="json", by_alias=True) | {"history": self.presentation.history(src.id)}
        )

    def presentation_redo(self, req: Request) -> Response:
        src = self.source(req)
        doc = self.presentation.redo(src.id)
        if doc is None:
            raise HttpError(409, "nothing to redo")
        return Response(
            body=doc.model_dump(mode="json", by_alias=True) | {"history": self.presentation.history(src.id)}
        )

    # Chat API -------------------------------------------------------------------------------------------------

    def chat_get(self, req: Request) -> Response:
        src = self.source(req)
        limit = req.int_query("limit", 200, low=1, high=1000)
        return Response(
            body={
                "schema": SCHEMA,
                "messages": [
                    m.model_dump(mode="json", by_alias=True) for m in self.presentation.messages(src.id, limit=limit)
                ],
            }
        )

    def chat_post(self, req: Request) -> Stream:
        src = self.source(req)
        try:
            request = ChatRequest.model_validate(req.json())
        except ValidationError as exc:
            raise HttpError(422, _first_error(exc)) from exc
        queue: list[tuple[str, str | None, Any]] = []
        done = threading.Event()
        lock = threading.Lock()

        def emit(event: str, data: dict[str, Any]) -> None:
            with lock:
                queue.append(sse(event, data))

        def work() -> None:
            try:
                self.chat.turn(src, request, emit)
            except Exception as exc:
                emit("error", {"detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
            finally:
                done.set()

        threading.Thread(target=work, name="unbidden-web-chat", daemon=True).start()

        def events() -> Iterator[tuple[str, str | None, Any]]:
            while True:
                with lock:
                    batch, queue[:] = list(queue), []
                yield from batch
                if done.is_set() and not queue:
                    with lock:
                        batch, queue[:] = list(queue), []
                    yield from batch
                    return
                time.sleep(0.05)

        return Stream(events())

    def chat_delete(self, req: Request) -> Response:
        src = self.source(req)
        n = self.presentation.clear_messages(src.id)
        return Response(body={"schema": SCHEMA, "deleted": n, "note": "the conversation only; no audit was touched"})

    def chat_cancel(self, req: Request) -> Response:
        src = self.source(req)
        return Response(body={"schema": SCHEMA, **self.chat.cancel(src.id)})

    # Actions API ----------------------------------------------------------------------------------------------

    def action(self, req: Request) -> Response:
        src = self.source(req)
        try:
            request = ActionRequestWeb.model_validate(req.json())
        except ValidationError as exc:
            raise HttpError(422, _first_error(exc)) from exc
        response = self.actions.run(src, request)
        return Response(body=response.model_dump(mode="json"))


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = "/".join(str(p) for p in err.get("loc", ())) or "the root"
    return f"{where}: {err.get('msg', 'invalid')}"


def _experiment_brief(exp: Experiment) -> dict[str, Any]:
    d = exp.model_dump(
        mode="json", exclude={"sessions", "control", "confirmation", "samples_before_ms", "samples_after_ms"}
    )
    d["counts"] = {
        "sessions": len(exp.sessions),
        "control": len(exp.control),
        "confirmation": len(exp.confirmation),
        "samples_before": len(exp.samples_before_ms),
        "samples_after": len(exp.samples_after_ms),
    }
    return d


# The HTTP layer -----------------------------------------------------------------------------------------------


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "unbidden-web/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            if app_log_enabled:
                super().log_message(format, *args)

        def _request(self) -> Request:
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            if length > 2_000_000:
                raise HttpError(413, "body too large")
            body = self.rfile.read(length) if length else b""
            query = {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
            headers = {k.lower(): v for k, v in self.headers.items()}
            return Request(self.command, parts.path, query, headers, body)

        def _send(self, response: Response) -> None:
            raw = response.raw if response.raw is not None else json.dumps(response.body, default=str).encode()
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'",
            )
            for k, v in response.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _stream(self, stream: Stream) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for event, id_, data in stream.events:
                    chunk = (
                        f"event: {event}\n"
                        + (f"id: {id_}\n" if id_ else "")
                        + f"data: {json.dumps(data, default=str)}\n\n"
                    )
                    self.wfile.write(chunk.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            finally:
                self.close_connection = True

        def _handle(self) -> None:
            try:
                req = self._request()
                result = app.dispatch(req)
            except HttpError as exc:
                self._send(Response(status=exc.status, body={"error": exc.detail, "status": exc.status}))
                return
            except Exception as exc:  # never a stack trace to the browser
                traceback.print_exc()
                self._send(
                    Response(status=500, body={"error": f"{type(exc).__name__}: {str(exc)[:200]}", "status": 500})
                )
                return
            if isinstance(result, Stream):
                self._stream(result)
            else:
                self._send(result)

        do_GET = do_POST = do_PUT = do_DELETE = _handle

        def finish(self) -> None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):  # the browser left mid-stream
                super().finish()

        def do_OPTIONS(self) -> None:  # no CORS preflight is ever granted: the page is same-origin
            self._send(Response(status=HTTPStatus.NO_CONTENT, raw=b"", content_type="text/plain"))

    return Handler


app_log_enabled = False


class WebServer:
    def __init__(self, app: App, host: str, port: int) -> None:
        self.app = app
        self.httpd = ThreadingHTTPServer((host, port), make_handler(app))
        self.httpd.daemon_threads = True
        self.host, self.port = host, self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?s={self.app.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="unbidden-web", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def free_port(host: str, preferred: int, tries: int = 20) -> int:
    """The preferred port if free, else the next free one. Whatever holds a port is never touched."""
    import socket

    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in {preferred}..{preferred + tries - 1}")
