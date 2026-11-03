"""The app: a full-screen reader of one workspace with the actions that already exist. It runs no job and calls a
model only when the person asks a question the records cannot answer (the chat's `analyze`, under the same spend
rules as the dashboard). Quitting stops nothing."""

from __future__ import annotations

import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar, Literal

from rich.markup import escape
from rich.table import Table
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.theme import Theme
from textual.widgets import Input

from unbidden.contracts.events import EventType
from unbidden.tui import actions
from unbidden.tui.commands import Command, help_lines, parse
from unbidden.tui.feed import Coalescer, Entry, seed
from unbidden.tui.screens import PanelScreen, SetupScreen
from unbidden.tui.state import key_rejected, read_cheap, read_dashboard, read_mandate, read_route, read_spend
from unbidden.tui.text import t
from unbidden.tui.widgets import ACCENT, Feed, Header, Prompt, StatusBar
from unbidden.workspace import Workspace

Planner = Literal["auto", "rule", "brain"]
POLL_S = 1.0

# Black and white, one accent: the brand's palette on a terminal (NO_COLOR makes Textual drop the colours).
THEME = Theme(
    name="unbidden",
    primary="#d7d7d7",
    secondary="#9a9a9a",
    accent=ACCENT,
    foreground="#ececec",
    background="#0e0e0e",
    surface="#161616",
    panel="#2a2a2a",
    success="#d7d7d7",
    warning=ACCENT,
    error="#ffffff",
    dark=True,
)
QUIT_WINDOW_S = 2.0


class UnbiddenApp(App[int]):
    TITLE = "Unbidden"
    CSS = """
    Screen { layout: vertical; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "interrupt", "cancel / quit", priority=True, show=False),
        Binding("ctrl+d", "eof", show=False, priority=True),
        Binding("escape", "escape", show=False),
        Binding("ctrl+l", "clear_feed", show=False, priority=True),
        Binding("pageup", "scroll_feed(-1)", show=False, priority=True),
        Binding("pagedown", "scroll_feed(1)", show=False, priority=True),
    ]

    def __init__(self, ws: Workspace, *, planner: Planner = "auto") -> None:
        super().__init__()
        self.register_theme(THEME)
        self.theme = THEME.name
        self.ws = ws
        self.planner: Planner = planner
        self.source: Any = None
        self.chat: Any = None
        self.ledger: Any = None
        self.verbose = False
        self.show_log = False
        self._last_seq = 0
        self._stopping = threading.Event()
        self._ticks = 0
        self._quit_armed_at = 0.0
        self._turn_running = False
        self._log_pos = 0
        self.asks = False

    # --- layout -------------------------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Feed()
        yield Prompt()
        yield StatusBar()

    @property
    def feed(self) -> Feed:
        return self.query_one(Feed)

    @property
    def bar(self) -> StatusBar:
        return self.query_one(StatusBar)

    @property
    def prompt(self) -> Prompt:
        return self.query_one(Prompt)

    def on_mount(self) -> None:
        self.prompt.focus()
        if not self.ws.initialized:
            self.push_screen(SetupScreen(self.ws), callback=self._first_setup_done)
            return
        self._open()

    def _first_setup_done(self, code: int | None) -> None:
        if not self.ws.initialized:  # the wizard did not even create the workspace
            self.exit(code or 2)
            return
        self._open()
        self._setup_outcome(code)

    def _setup_outcome(self, code: int | None) -> None:
        path = self.ws.mandate_path if code == 0 else self.ws.dir / "setup.json"
        try:
            shown = path.relative_to(self.ws.repo)
        except ValueError:
            shown = path
        self._say(t("open.setup.done" if code == 0 else "open.setup.incomplete", path=shown), accent=code != 0)

    def _open(self) -> None:
        """The workspace is initialized: read it, seed the feed, start the tail and the ticks."""
        from unbidden.brain.spend import SpendLedger
        from unbidden.web.sources import live

        if not (self.ws.dir / "state.db").exists():
            self.ws.store().close()
        self.source = live(self.ws.repo)
        self.ledger = SpendLedger()
        mandate = self.source.mandate
        self.asks = bool(mandate and str(mandate.autonomy.open_pull_requests) == "require_approval")
        header = self.query_one(Header)
        header.workspace = self.ws.repo.name
        try:
            from unbidden.workspace import head_sha

            header.head = head_sha(self.ws.repo)
        except Exception:
            header.head = ""
        read_mandate(self.ws, self.bar.bar)
        header.mode, header.profile = self.bar.bar.mode, self.bar.bar.profile
        header.refresh_line()
        self.feed.banner()
        self.prompt.focus()
        self._open_feed()
        self._tick()
        self.set_interval(POLL_S, self._tick)
        self._tail()
        self._probe_route()
        self._probe_dashboard()

    # --- the feed on open and its tail ----------------------------------------------------------------------------

    def _open_feed(self) -> None:
        with self.source.lock:
            highlights = self.source.highlights()
            entries = seed(self.source.store, highlights, asks_for_proposals=self.asks)
            self._last_seq = int(self.source.store.last_seq() or 0)
            recent = self.source.store.events(after=max(0, self._last_seq - 240), limit=240)
        self.feed.add_many(entries)
        self.bar.bar.key_rejected = bool(key_rejected(recent))

    @work(thread=True, exclusive=True, group="tail", exit_on_error=False)
    def _tail(self) -> None:
        """New events every second, as the dashboard's stream reads them; one line when the record cannot be read."""
        stale = False
        while not self._stopping.is_set():
            try:
                with self.source.lock:
                    events = self.source.store.events(after=self._last_seq, limit=200)
                if events:
                    folder = Coalescer(asks_for_proposals=self.asks, verbose=self.verbose)
                    entries: list[Entry] = []
                    mandate_changed = False
                    for e in events:
                        entries.extend(folder.push(e))
                        mandate_changed |= e.type == EventType.MANDATE_CHANGED
                    entries.extend(folder.flush())
                    self._last_seq = int(events[-1].seq or self._last_seq)
                    self.call_from_thread(self._arrived, entries, mandate_changed, key_rejected(events))
                if stale:
                    stale = False
                    self.call_from_thread(
                        self.feed.add, Entry(verb="Noting", text=t("open.tail.recovered"), kind="stale")
                    )
            except Exception as exc:  # the record moved or is locked: say it once, keep trying
                if not stale:
                    stale = True
                    note = Entry(verb="Noting", text=t("open.tail.stale", reason=str(exc)[:80]), kind="stale")
                    self.call_from_thread(self.feed.add, note)
            self._stopping.wait(POLL_S)

    def _arrived(self, entries: list[Entry], mandate_changed: bool, key: bool | None = None) -> None:
        self.feed.add_many(entries)
        if key is not None:
            self.bar.bar.key_rejected = key
        if mandate_changed:
            read_mandate(self.ws, self.bar.bar)
            header = self.query_one(Header)
            header.mode, header.profile = self.bar.bar.mode, self.bar.bar.profile
            header.refresh_line()
        if self.show_log:
            self._tail_log()

    # --- the status bar -----------------------------------------------------------------------------------------

    def _tick(self) -> None:
        if self.source is None:
            return
        self._ticks += 1
        bar = self.bar.bar
        read_cheap(self.ws, self.source.store, bar)
        if self._ticks % 10 == 1:
            read_spend(self.ledger, bar)
        if self._ticks % 30 == 0:
            read_mandate(self.ws, bar)
            self._probe_route()
        if self._ticks % 15 == 0:
            self._probe_dashboard()
        if self._quit_armed_at and time.monotonic() - self._quit_armed_at > QUIT_WINDOW_S:
            self._quit_armed_at = 0.0
            bar.transient = t("bar.thinking") if self._turn_running else ""
        self.bar.refresh_line()

    @work(thread=True, group="route", exclusive=True, exit_on_error=False)
    def _probe_route(self) -> None:
        read_route(self.source, self.bar.bar)
        self.call_from_thread(self.bar.refresh_line)

    @work(thread=True, group="dashboard", exclusive=True, exit_on_error=False)
    def _probe_dashboard(self) -> None:
        read_dashboard(self.ws, self.bar.bar)
        self.call_from_thread(self.bar.refresh_line)

    # --- the prompt ---------------------------------------------------------------------------------------------

    def on_prompt_line(self, message: Prompt.Line) -> None:
        parsed = parse(message.text)
        if parsed is None:
            return
        if isinstance(parsed, str):
            self._ask(parsed)
            return
        self._command(parsed)

    def _say(self, text: str, *, accent: bool = False) -> None:
        self.feed.add(Entry(verb="Noting", text=text, kind="note", accent=accent))

    def _command(self, cmd: Command) -> None:
        if cmd.error:
            kind, _, rest = cmd.error.partition(":")
            self._say(t("cmd.unknown", name=rest) if kind == "unknown" else t("cmd.usage", usage=rest))
            return
        match cmd.name:
            case "help":
                self._help()
            case "quit":
                self._quit()
            case "clear":
                self.feed.clear_all()
            case "verbose":
                self.verbose = not self.verbose
                self._say(t("cmd.verbose.on" if self.verbose else "cmd.verbose.off"))
            case "log":
                self.show_log = not self.show_log
                self._say(
                    t("cmd.log.on", path=self.ws.dir / "logs" / "agent.log") if self.show_log else t("cmd.log.off")
                )
                if self.show_log:
                    self._log_pos = 0
                    self._tail_log()
            case "start":
                self._run_action(
                    "start", lambda: actions.start(self.ws, ui="--ui" in cmd.flags, force="--force" in cmd.flags)
                )
            case "stop":
                self._run_action("stop", lambda: actions.stop(self.ws))
            case "kill":
                self.feed.add_many(actions.kill(self.ws, " ".join(cmd.args)))
                self._tick()
            case "resume":
                self.feed.add_many(actions.resume(self.ws))
                self._tick()
            case "approve":
                hours = 24.0
                if "--hours" in cmd.args:
                    try:
                        hours = float(cmd.args[cmd.args.index("--hours") + 1])
                    except (IndexError, ValueError):
                        self._say(t("cmd.usage", usage="/approve <id> [--hours N]"))
                        return
                self.feed.add_many(actions.approve(self.ws, cmd.words[0], hours=hours))
            case "reject":
                self.feed.add_many(actions.reject(self.ws, cmd.words[0], " ".join(cmd.words[1:])))
            case "why":
                with self.source.lock:
                    self.feed.add_many(actions.why(self.source.store, cmd.words[0]))
            case "inbox":
                with self.source.lock:
                    rows = actions.inbox(self.source.store, all_="--all" in cmd.flags)
                if not rows:
                    self._say(t("cmd.inbox.empty"))
                    return
                table = Table(box=None, header_style="bold")
                for column in ("id", "evidence", "status", "title"):
                    table.add_column(column)
                for row in rows:
                    table.add_row(*row)
                self.push_screen(PanelScreen(t("cmd.inbox.title"), table))
            case "spend":
                self.feed.add_many(actions.spend(self.ledger))
                read_spend(self.ledger, self.bar.bar)
                self.bar.refresh_line()
            case "activity":
                with self.source.lock:
                    self.feed.add_many(actions.activity(self.source))
            case "doctor":
                self._run_action("doctor", lambda: actions.doctor(self.ws))
            case "ui":
                self._run_action("ui", lambda: actions.ui(self.ws, open_="--open" in cmd.flags, planner=self.planner))
            case "setup":
                self._say(t("cmd.setup.push"))
                self._setup(cmd.args[0] if cmd.args else None)
            case "key":
                self._say(t("cmd.key.push"))
                self._setup("key")
            case "language":
                self._language(cmd.words[0] if cmd.words else None)
            case _:
                self._say(t("cmd.unknown", name=cmd.name))

    @work(thread=True, group="action", exclusive=True, exit_on_error=False)
    def _run_action(self, name: str, fn: Any) -> None:
        """An action that may take seconds (start, stop, doctor, ui) runs off the UI thread."""
        try:
            entries = fn()
        except Exception as exc:
            entries = [Entry(verb="Noting", text=escape(f"{name}: {exc}"), kind="note", accent=True)]
        self.call_from_thread(self.feed.add_many, entries)
        self.call_from_thread(self._tick)

    def _help(self) -> None:
        self.feed.add(Entry(verb="Noting", text=t("cmd.help.title"), kind="heading"))
        width = max(len(usage) for usage, _ in help_lines())
        for usage, help_ in help_lines():
            line = f"[bold]{escape(usage.ljust(width))}[/]  {escape(help_)}"  # a usage holds [brackets]
            self.feed.add(Entry(verb="Noting", text=line, kind="note"))
        self._say(t("cmd.help.chat"))
        self._say(t("cmd.help.keys"))

    def _language(self, code: str | None) -> None:
        """Say the language, or change it: saved on this machine; the header, bar and prompt follow at once."""
        from unbidden import i18n

        if code is None:
            self._say(t("cmd.language.now", name=i18n.name(), how=t(f"lang.how.{i18n.source()}")))
            return
        code = code.lower()
        if code not in i18n.LANGUAGES:
            self._say(t("cmd.language.unknown", code=code, codes=", ".join(i18n.LANGUAGES)))
            return
        i18n.set_language(code)
        self.prompt.placeholder = t("prompt.placeholder")
        self.query_one(Header).refresh_line()
        self.bar.refresh_line()
        self._say(t("cmd.language.set", name=i18n.name()))

    def _setup(self, section: str | None) -> None:
        redo_all = section == "--all"
        screen = SetupScreen(self.ws, section=None if redo_all else section, redo_all=redo_all)
        self.push_screen(screen, callback=lambda code: self._setup_done(code, section))

    def _setup_done(self, code: int | None, section: str | None = None) -> None:
        if section == "key":
            self._say(t("cmd.key.done" if code == 0 else "cmd.key.incomplete"), accent=code != 0)
            self.prompt.focus()
            return
        self._setup_outcome(code)
        read_mandate(self.ws, self.bar.bar)
        header = self.query_one(Header)
        header.mode, header.profile = self.bar.bar.mode, self.bar.bar.profile
        header.refresh_line()
        self.prompt.focus()

    # --- the agent's log ----------------------------------------------------------------------------------------

    def _tail_log(self) -> None:
        path = Path(self.ws.dir) / "logs" / "agent.log"
        if not path.exists():
            return
        with path.open("rb") as fh:
            fh.seek(0, 2)
            end = fh.tell()
            if self._log_pos == 0:
                self._log_pos = max(0, end - 4000)
            fh.seek(self._log_pos)
            chunk = fh.read()
            self._log_pos = end
        for line in chunk.decode("utf-8", errors="replace").splitlines()[-40:]:
            self.feed.dim(line)

    # --- the chat -----------------------------------------------------------------------------------------------

    def _ask(self, text: str) -> None:
        if self._turn_running:
            self._say(t("bar.thinking"))
            return
        self.feed.add(Entry(verb="Noting", text=text, kind="person"))
        self._turn_running = True
        self.bar.bar.transient = t("bar.thinking")
        self.bar.refresh_line()
        self._turn(text)

    def _chat_service(self) -> Any:
        if self.chat is None:
            from unbidden.web.__main__ import make_brain_for, web_home
            from unbidden.web.chat import ChatService
            from unbidden.web.presentation import PresentationStore

            state_dir = web_home()
            state_dir.mkdir(parents=True, exist_ok=True)
            self.chat = ChatService(PresentationStore(state_dir / "presentation.db"),
                                    make_brain_for(self.planner, state_dir))  # fmt: skip
        return self.chat

    def _turn(self, text: str) -> None:
        """A plain daemon thread, not a Textual worker: a model call cannot be interrupted, and quitting the app
        must never wait for one. The turn is cancelled on quit; the thread dies with the process."""
        threading.Thread(target=self._turn_work, args=(text,), name="unbidden-chat", daemon=True).start()

    def _turn_work(self, text: str) -> None:
        from unbidden.web.contracts import ChatRequest

        last: list[str] = []

        def emit(event: str, data: dict[str, Any]) -> None:
            if event == "state" and data.get("state") not in ("done", None):
                line = str(data.get("state")) + (f": {data['detail']}" if data.get("detail") else "")
                if last and last[-1] == line:  # the same state again says nothing new
                    return
                last.append(line)
                self._from_thread(self.feed.dim, t("chat.state", state=line))
            elif event == "tool_result":
                mark = "ok" if data.get("ok") else "!!"
                self._from_thread(self.feed.dim, t("chat.tool", mark=mark, tool=data.get("tool"),
                                                   summary=data.get("summary")))  # fmt: skip

        try:
            service = self._chat_service()
            message = service.turn(self.source, ChatRequest(content=text, planner=self.planner), emit)
        except Exception as exc:
            self._from_thread(self._answered, None, str(exc))
            return
        self._from_thread(self._answered, message, None)

    def _from_thread(self, fn: Any, *args: Any) -> None:
        with suppress(RuntimeError):  # the app may have quit while the turn ran
            self.call_from_thread(fn, *args)

    def _quit(self) -> None:
        """Leave. A running answer is cancelled, the agent is never stopped."""
        if self._turn_running and self.chat is not None:
            self.chat.cancel(self.source.id)
        self.exit(0)

    def _answered(self, message: Any, error: str | None) -> None:
        self._turn_running = False
        self.bar.bar.transient = ""
        if error:
            self._say(t("chat.error", error=error), accent=True)
        elif message is not None:
            trailer = None
            route = message.route
            if route is not None:
                via = route.model or route.tier or "no model"
                trailer = t("chat.route", intent=route.intent, purpose=route.purpose or "rules", via=via)
                if route.blocked:
                    trailer += " · " + t("chat.blocked", reason=route.blocked)
                    if route.hint:
                        trailer += " · " + t("chat.hint", hint=route.hint)
            if message.state == "cancelled":
                self._say(t("chat.cancelled"))
            else:
                self.feed.answer(message.content, trailer)
        read_spend(self.ledger, self.bar.bar)
        self.bar.refresh_line()

    # --- keys ---------------------------------------------------------------------------------------------------

    def action_interrupt(self) -> None:
        if isinstance(self.screen, SetupScreen):  # the app's binding has priority; setup owns Ctrl+C while it is open
            self.screen.action_interrupt()
            return
        if self._turn_running and self.chat is not None:
            self.chat.cancel(self.source.id)
            return
        if self.prompt.value:
            self.prompt.value = ""
            return
        if self._quit_armed_at and time.monotonic() - self._quit_armed_at <= QUIT_WINDOW_S:
            self._quit()
            return
        self._quit_armed_at = time.monotonic()
        self.bar.bar.transient = t("bar.quit")
        self.bar.refresh_line()

    def action_eof(self) -> None:
        if not self.prompt.value:
            self._quit()

    def action_escape(self) -> None:
        if self._turn_running and self.chat is not None:
            self.chat.cancel(self.source.id)

    def action_clear_feed(self) -> None:
        self.feed.clear_all()

    def action_scroll_feed(self, direction: int) -> None:
        if direction < 0:
            self.feed.scroll_page_up()
        else:
            self.feed.scroll_page_down()

    def on_unmount(self) -> None:
        self._stopping.set()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._quit_armed_at:
            self._quit_armed_at = 0.0
            self.bar.bar.transient = t("bar.thinking") if self._turn_running else ""
            self.bar.refresh_line()


def run_app(ws: Workspace, *, planner: Planner = "auto") -> int:
    """Open the app on a workspace; one not set up yet opens the assistant first. The exit code is what the app
    returns (0 on /quit)."""
    app = UnbiddenApp(ws, planner=planner)
    code = app.run()
    return int(code) if code is not None else 0


__all__ = ["ACCENT", "UnbiddenApp", "run_app"]
