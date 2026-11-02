"""The screens the app pushes over the home: a panel for a table or a block of lines."""

from __future__ import annotations

from typing import ClassVar

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


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
