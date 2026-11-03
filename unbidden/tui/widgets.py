"""The app's widgets: the header, the feed, the status bar and the prompt. Rendering only; the data comes from
`feed`, `state` and `actions`."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from rich.markdown import Markdown
from rich.text import Text
from textual import events
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.suggester import SuggestFromList
from textual.widgets import Input, RichLog, Static

from unbidden import __version__
from unbidden.tui import brand
from unbidden.tui.commands import SPECS, completions
from unbidden.tui.feed import Entry
from unbidden.tui.state import Bar, format_bar
from unbidden.tui.text import t

ACCENT = brand.ACCENT


class Header(Static):
    """One line: the mark and wordmark, the workspace, head, mode and option; the version at the right."""

    DEFAULT_CSS = "Header { height: 1; padding: 0 1; background: $surface; color: $foreground; }"

    def __init__(self) -> None:
        super().__init__("")
        self.workspace = ""
        self.head = ""
        self.mode = ""
        self.profile = ""
        self.line = ""

    def refresh_line(self) -> None:
        width = max(20, self.size.width - 2)
        left = f"[bold]{brand.MARK} {brand.WORDMARK}[/]"
        facts = " · ".join(x for x in (self.workspace, f"head {self.head[:12]}" if self.head else "", self.mode,
                                        self.profile) if x)  # fmt: skip
        if facts:
            left += f"  [dim]{facts}[/]"
        right = f"[dim]{__version__}[/]"
        gap = width - Text.from_markup(left).cell_len - Text.from_markup(right).cell_len
        self.line = left + " " * max(1, gap) + right if gap >= 1 else left
        self.update(self.line)

    def on_resize(self) -> None:
        self.refresh_line()


class Feed(RichLog):
    """The conversation: the engine's work narrated under its verbs, the person's turns and the answers."""

    DEFAULT_CSS = "Feed { height: 1fr; padding: 0 1; scrollbar-size: 1 1; }"

    def __init__(self) -> None:
        super().__init__(wrap=True, markup=False, highlight=False, min_width=20)
        self.current_verb: str | None = None

    def banner(self) -> None:
        width = max(40, self.size.width or 80)
        self.write(brand.banner(width, version=__version__))
        self.write(Text(""))
        self.write(brand.verbs())
        self.write(Text(""))

    def add(self, entry: Entry) -> None:
        if entry.kind == "heading":
            self.write(Text(""))
            self.write(Text(entry.text, style="bold"))
            self.current_verb = None
            return
        if entry.kind in ("event", "note") and entry.verb != self.current_verb and entry.verb != "Noting":
            self.write(Text(""))
            head = Text("> ", style="dim")
            head.append(f"{entry.verb}.", style=f"bold {ACCENT}" if entry.accent else "bold")
            self.write(head)
            self.current_verb = entry.verb
        line = Text()
        if entry.kind == "event":
            line.append(f"  {_clock(entry.ts)}  ", style="dim")
        elif entry.kind == "person":
            line.append(f"{t('chat.person')} > ", style="bold")
        elif entry.kind == "stale":
            line.append("  ", style="dim")
        else:
            line.append("  ")
        body = Text.from_markup(entry.text) if entry.kind == "note" else Text(entry.text)
        shade = entry.shade
        if shade == "good":
            line.append("✓ ", style="bold")
            body.stylize("bold")
        elif shade == "bad":
            line.append("✗ ", style="bold")
            body.stylize("bold")
        elif shade == "warn":
            line.append("! ", style=ACCENT)
            body.stylize(ACCENT)
        elif shade == "ask":
            body.stylize(ACCENT)
        elif entry.kind == "stale":
            body.stylize("dim")
        line.append_text(body)
        self.write(line)
        if entry.detail:
            self.write(Text(f"          {entry.detail}", style="dim"))

    def add_many(self, entries: list[Entry]) -> None:
        for entry in entries:
            self.add(entry)

    def answer(self, content: str, trailer: str | None = None) -> None:
        self.write(Markdown(content))
        if trailer:
            self.write(Text(trailer, style="dim"))
        self.current_verb = None

    def dim(self, text: str) -> None:
        self.write(Text(f"  {text}", style="dim"))

    def clear_all(self) -> None:
        self.clear()
        self.current_verb = None


class StatusBar(Static):
    DEFAULT_CSS = "StatusBar { height: 1; padding: 0 1; background: $surface; }"

    def __init__(self) -> None:
        super().__init__("")
        self.bar = Bar()
        self.line = ""

    def refresh_line(self) -> None:
        line = format_bar(self.bar, max(20, self.size.width - 2), accent=ACCENT)
        if line != self.line:
            self.line = line
            self.update(line)

    def on_resize(self) -> None:
        self.refresh_line()


class Prompt(Input):
    """The prompt: plain text is a question, a leading slash is a command; Up and Down walk the history; Tab
    completes a command (the suggestion, else the one command that matches) and never leaves the prompt."""

    DEFAULT_CSS = "Prompt { height: 3; border: tall $panel; } Prompt:focus { border: tall $accent; }"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "history(-1)", show=False),
        Binding("down", "history(1)", show=False),
    ]

    class Line(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__(placeholder=t("prompt.placeholder"),
                         suggester=SuggestFromList([f"/{name}" for name in SPECS], case_sensitive=False))  # fmt: skip
        self.history: list[str] = []
        self._at = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        self.value = ""
        if text:
            if not self.history or self.history[-1] != text:
                self.history.append(text)
            self._at = len(self.history)
            self.post_message(self.Line(text))

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.complete()
            return
        await super()._on_key(event)

    def complete(self) -> None:
        """Fill the command in: the suggestion shown, else the only /command that starts with what was typed;
        several matches leave the text alone (the suggestion already shows the first)."""
        text = self.value
        if not text.startswith("/") or " " in text:
            return
        suggestion = self._suggestion
        if suggestion and suggestion.lower().startswith(text.lower()):
            self.value = suggestion + " "
        else:
            matches = completions(text)
            if len(matches) == 1:
                self.value = matches[0] + " "
            elif text in matches:
                self.value = text + " "
        self.cursor_position = len(self.value)

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        self._at = max(0, min(len(self.history), self._at + step))
        self.value = self.history[self._at] if self._at < len(self.history) else ""
        self.cursor_position = len(self.value)


def _clock(ts: datetime | Any) -> str:
    try:
        return ts.astimezone().strftime("%H:%M")
    except Exception:
        return "--:--"
