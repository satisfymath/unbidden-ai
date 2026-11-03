"""The screens the app pushes over the home: a panel for a table or a block of lines."""

from __future__ import annotations

import threading
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
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

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


class AskScreen(ModalScreen[tuple[str, str | None] | None]):
    """A question from the agent with its options: arrows or a click, Enter answers; an option that takes a value
    (a key, a reason, an amount) shows an input next; Esc leaves it for later. Dismisses with (option, value) or
    None."""

    DEFAULT_CSS = """
    AskScreen { align: center middle; }
    AskScreen > Vertical { width: 90%; max-width: 100; height: auto; border: round $panel; padding: 1 2;
                           background: $surface; }
    AskScreen .title { text-style: bold; }
    AskScreen .why { color: $secondary; margin-bottom: 1; }
    AskScreen OptionList { height: auto; max-height: 8; border: tall $panel; }
    AskScreen OptionList:focus { border: tall $accent; }
    AskScreen Input { height: 3; border: tall $panel; display: none; }
    AskScreen Input:focus { border: tall $accent; }
    AskScreen .hint { height: 1; color: $secondary; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "later", show=False)]

    def __init__(self, ask: Any) -> None:
        super().__init__()
        self.ask = ask
        self._chosen: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(self.ask.title, style="bold"), classes="title")
            yield Static(self.ask.why, classes="why")
            yield OptionList(id="options")
            yield Input(id="value")
            yield Static(t("ask.hint"), classes="hint", id="hint")

    def on_mount(self) -> None:
        options = self.query_one("#options", OptionList)
        keys = [o.key for o in self.ask.options]
        for i, option in enumerate(self.ask.options):
            prompt = Text(option.label)
            if option.key == self.ask.default:
                prompt.append(f"  {t('setup.default')}", style="dim")
            options.add_option(Option(prompt, id=str(i)))
        options.highlighted = keys.index(self.ask.default) if self.ask.default in keys else 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id is None:
            return
        option = self.ask.options[int(event.option_id)]
        if option.input == "none":
            self.dismiss((option.key, None))
            return
        self._chosen = option.key
        value = self.query_one("#value", Input)
        value.password = option.input == "secret"
        value.placeholder = "" if option.input == "secret" else t("ask.value.placeholder")
        value.display = True
        self.query_one("#hint", Static).update(t("ask.hint.value"))
        value.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self._chosen is None:
            return
        self.dismiss((self._chosen, event.value))

    def action_later(self) -> None:
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
    SetupScreen #choices { height: auto; max-height: 8; border: tall $panel; display: none; }
    SetupScreen #choices:focus { border: tall $accent; }
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
        self._values: list[Any] = []  # what each menu option answers with, by position
        self.code: int | None = None
        self.cancel = threading.Event()  # Ctrl+C while the wizard waits on something that is not a question

    def compose(self) -> ComposeResult:
        yield Static(brand.banner(80, version=__version__), id="banner")
        yield RichLog(wrap=True, markup=False, highlight=False, min_width=20, id="log")
        with Vertical(id="ask"):
            yield Static("", id="question")
            yield OptionList(id="choices")
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

    def _terminal(self, argv: list[str]) -> int:
        """A command that needs the person's terminal (gh install, gh auth login): the app steps aside, the command
        runs in the real terminal, the app comes back. Called from the worker thread."""
        return self.app.call_from_thread(self._suspend_and_run, argv)

    def _suspend_and_run(self, argv: list[str]) -> int:
        """While the command owns the terminal, Ctrl+C is the command's (gh stops; the app does not): the app ignores
        SIGINT for that long and the child gets the default handler back."""
        import signal
        import subprocess

        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            with self.app.suspend():
                return subprocess.run(
                    argv, check=False, preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL)
                ).returncode
        except KeyboardInterrupt:
            return 130
        finally:
            signal.signal(signal.SIGINT, previous)

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
            code = run(
                self.ws, opts, out, io=AppIO(self._ask_from_worker), pull=self._pull, cancel=self.cancel,
                terminal=self._terminal,
            )  # fmt: skip
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
        """A choice or a confirmation is a menu (arrows or a click, Enter); text and secrets take the input."""
        future: Future[Any] = Future()
        self._pending = (ask, future)
        question = self.query_one("#question", Static)
        answer = self.query_one("#answer", Input)
        choices = self.query_one("#choices", OptionList)
        hint = self.query_one("#hint", Static)
        question.update(Text(ask.prompt or ask.key, style="bold"))
        if ask.kind in ("choice", "confirm"):
            if ask.kind == "confirm":
                labels, self._values = [t("setup.yes"), t("setup.no")], [True, False]
                default = 0 if ask.default else 1
            else:
                labels, self._values = list(ask.choices), list(ask.choices)
                default = self._values.index(ask.default) if ask.default in self._values else 0
            choices.clear_options()
            for i, label in enumerate(labels):
                prompt = Text(label)
                if i == default and (ask.kind == "confirm" or ask.default is not None):
                    prompt.append(f"  {t('setup.default')}", style="dim")
                choices.add_option(Option(prompt, id=str(i)))
            choices.highlighted = default
            answer.display = False
            choices.display = True
            hint.update(t("prompt.setup.menu"))
            choices.focus()
        else:
            answer.password = ask.kind == "secret"
            answer.value = ""
            answer.placeholder = "" if ask.kind == "secret" else t("prompt.placeholder.setup")
            choices.display = False
            answer.display = True
            hint.update(t("prompt.setup"))
            answer.focus()
        return future

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self._pending is None or event.option_id is None:
            return
        ask, future = self._pending
        self._pending = None
        value = self._values[int(event.option_id)]
        self.query_one("#choices", OptionList).display = False
        self.query_one("#question", Static).update("")
        shown = ("y" if value else "n") if ask.kind == "confirm" else str(value)
        self.log_widget.write(Text(f"> {shown}", style="bold"))
        if not future.cancelled():
            future.set_result(value)

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
        self.cancel.set()
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
