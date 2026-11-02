"""The screens the app pushes over the home: a panel for a table or a block of lines."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from contextlib import suppress
from typing import Any, ClassVar

from rich.console import Console, RenderableType
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, RichLog, Static

from unbidden import __version__
from unbidden.tui import brand
from unbidden.tui.setup_io import INTERRUPTED, AppIO, Ask, LineSink
from unbidden.tui.text import t


class PanelScreen(ModalScreen[None]):
    """A titled panel over the feed; Esc, q or Enter close it."""

    DEFAULT_CSS = """
    PanelScreen { align: center middle; }
    PanelScreen > VerticalScroll { width: 90%; height: 80%; border: round $panel; padding: 1 2; background: $surface; }
    PanelScreen .title { text-style: bold; margin-bottom: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", show=False),
        Binding("q", "dismiss", show=False),
        Binding("enter", "dismiss", show=False),
    ]

    def __init__(self, title: str, body: RenderableType) -> None:
        super().__init__()
        self.title_text = title
        self.body = body

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(self.title_text, classes="title")
            yield Static(self.body)

    def action_dismiss(self) -> None:  # type: ignore[override]
        self.dismiss(None)


class SetupScreen(Screen[int]):
    """The guided configuration inside the app: the wizard runs unchanged in a worker thread and asks through the
    panel at the bottom; its narration lands in the log above. Ctrl+C keeps the answers given so far."""

    DEFAULT_CSS = """
    SetupScreen { layout: vertical; }
    SetupScreen #banner { height: 3; padding: 0 1; }
    SetupScreen #log { height: 1fr; padding: 0 1; }
    SetupScreen #ask { height: auto; padding: 0 1; border-top: solid $panel; }
    SetupScreen #question { height: auto; padding: 0 0 0 0; }
    SetupScreen Input { height: 3; border: tall $panel; }
    SetupScreen Input:focus { border: tall $accent; }
    SetupScreen #hint { height: 1; color: $secondary; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("ctrl+c", "interrupt", show=False, priority=True)]

    class Finished(Message):
        def __init__(self, code: int) -> None:
            super().__init__()
            self.code = code

    def __init__(self, ws: Any, *, section: str | None = None, redo_all: bool = False) -> None:
        super().__init__()
        self.ws = ws
        self.section = section
        self.redo_all = redo_all
        self._pending: tuple[Ask, Future[Any]] | None = None
        self.code: int | None = None

    def compose(self) -> ComposeResult:
        yield Static(brand.banner(80, version=__version__), id="banner")
        yield RichLog(wrap=True, markup=False, highlight=False, min_width=20, id="log")
        with Vertical(id="ask"):
            yield Static("", id="question")
            yield Input(id="answer")
            yield Static(t("prompt.setup"), id="hint")

    @property
    def log_widget(self) -> RichLog:
        return self.query_one("#log", RichLog)

    def on_mount(self) -> None:
        self.query_one("#answer", Input).focus()
        self._run_wizard()

    # --- the worker -------------------------------------------------------------------------------------------

    def _emit_line(self, line: str) -> None:
        self.log_widget.write(Text.from_ansi(line))

    def _ask_from_worker(self, ask: Ask) -> Future[Any]:
        return self.app.call_from_thread(self._show_ask, ask)

    def _pull(self, tag: str, say: Callable[[str], None]) -> bool:
        """`ollama pull` with its output streamed into the log instead of the terminal the app owns."""
        import subprocess

        say(f"ollama pull {tag} ...")
        try:
            proc = subprocess.Popen(
                ["ollama", "pull", tag], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
        except OSError as exc:
            say(f"could not run ollama: {exc}")
            return False
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.strip():
                say(line.rstrip()[-120:])
        return proc.wait() == 0

    @work(thread=True, group="setup", exclusive=True, exit_on_error=False)
    def _run_wizard(self) -> None:
        from unbidden.setup.wizard import Options, SetupError, run

        sink = LineSink(lambda line: self.app.call_from_thread(self._emit_line, line))
        out = Console(
            file=sink,  # type: ignore[arg-type]
            force_terminal=True,
            color_system="standard",
            width=100,
            soft_wrap=True,
            highlight=False,  # the wizard's own styles only; no path or number highlighting
        )
        opts = Options(section=self.section, redo_all=self.redo_all)
        try:
            code = run(self.ws, opts, out, io=AppIO(self._ask_from_worker), pull=self._pull)
        except SetupError as exc:
            if str(exc) != INTERRUPTED:
                self.app.call_from_thread(self._emit_line, f"setup: {exc}")
            code = 2
        except Exception as exc:  # a failure inside the wizard must not take the app down
            self.app.call_from_thread(self._emit_line, f"setup failed: {exc}")
            code = 2
        sink.flush()
        with suppress(RuntimeError):  # the app may already be gone (quit during setup)
            self.app.call_from_thread(self._finished, code)

    def _finished(self, code: int) -> None:
        self.code = code
        self.post_message(self.Finished(code))
        self.dismiss(code)

    # --- the questions --------------------------------------------------------------------------------------------

    def _show_ask(self, ask: Ask) -> Future[Any]:
        future: Future[Any] = Future()
        self._pending = (ask, future)
        question = self.query_one("#question", Static)
        answer = self.query_one("#answer", Input)
        label = Text(ask.prompt or ask.key, style="bold")
        if ask.kind == "choice":
            label.append(f"  ({' / '.join(ask.choices)})", style="dim")
        if ask.kind == "confirm":
            label.append("  (y/n)", style="dim")
        if ask.default not in (None, "", False):
            label.append(f"  [{ask.default if not isinstance(ask.default, bool) else 'y'}]", style="dim")
        elif ask.kind == "confirm":
            label.append("  [n]", style="dim")
        question.update(label)
        answer.password = ask.kind == "secret"
        answer.value = ""
        answer.placeholder = "" if ask.kind == "secret" else t("prompt.placeholder.setup")
        answer.focus()
        return future

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self._pending is None:
            return
        ask, future = self._pending
        self._pending = None
        value = event.value
        self.query_one("#answer", Input).value = ""
        self.query_one("#question", Static).update("")
        if ask.kind != "secret":
            if value:
                shown = value
            elif ask.kind == "confirm":
                shown = "y" if ask.default else "n"
            else:
                shown = str(ask.default) if ask.default is not None else ""
            self.log_widget.write(Text(f"> {shown}", style="bold"))
        if not future.cancelled():
            future.set_result(value)

    def action_interrupt(self) -> None:
        if self._pending is not None:
            _, future = self._pending
            self._pending = None
            future.cancel()
        else:
            self._emit_line(t("setup.wait"))

    def on_unmount(self) -> None:
        """The screen goes away (the app quits) while a question waits: the worker must not wait forever."""
        if self._pending is not None:
            _, future = self._pending
            self._pending = None
            future.cancel()
