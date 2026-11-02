"""The setup assistant's questions across a thread boundary: the wizard runs synchronously in a worker and asks
through `IO`; `AppIO` turns each question into an `Ask` the screen shows, and waits on a Future the screen resolves.
`LineSink` is the file the wizard's Console writes to, one line at a time, into the screen's log."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from typing import Any, Literal

from unbidden.setup.wizard import SetupError

INTERRUPTED = "interrupted"
RETRIES = 20  # invalid answers to one question before the assistant gives up (a person never gets near it)


@dataclass(frozen=True)
class Ask:
    kind: Literal["choice", "text", "secret", "confirm"]
    key: str
    prompt: str
    choices: tuple[str, ...] = ()
    default: str | bool | None = None


class AppIO:
    """Implements `setup.wizard.IO`. `ask` is called from the worker thread and must return a Future the UI thread
    resolves (the app's `call_from_thread` does exactly that). A cancelled Future is the person's interruption."""

    def __init__(self, ask: Callable[[Ask], Future[Any]]) -> None:
        self._ask = ask

    def choice(self, key: str, prompt: str, choices: Sequence[str], default: str | None) -> str:
        for _ in range(RETRIES):
            answer = str(self._wait(Ask("choice", key, prompt, tuple(choices), default)) or "").strip()
            if not answer and default is not None:
                return default
            if answer in choices:
                return answer
        raise SetupError(f"no valid answer for {key} (one of {', '.join(choices)})")

    def text(self, key: str, prompt: str, default: str | None) -> str:
        answer = str(self._wait(Ask("text", key, prompt, default=default)) or "")
        return answer if answer or default is None else default

    def secret(self, key: str, prompt: str) -> str:
        return str(self._wait(Ask("secret", key, prompt)) or "")

    def confirm(self, key: str, prompt: str, default: bool) -> bool:
        for _ in range(RETRIES):
            answer = self._wait(Ask("confirm", key, prompt, default=default))
            if isinstance(answer, bool):
                return answer
            text = str(answer or "").strip().lower()
            if not text:
                return default
            if text in ("y", "yes"):
                return True
            if text in ("n", "no"):
                return False
        raise SetupError(f"no valid answer for {key} (y or n)")

    def _wait(self, ask: Ask) -> Any:
        future = self._ask(ask)
        try:
            return future.result()
        except CancelledError as exc:
            raise SetupError(INTERRUPTED) from exc


class LineSink:
    """A file-like object for a rich Console: every completed line goes to `emit` (ANSI kept, for Text.from_ansi)."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            line, self._buffer = self._buffer, ""
            self._emit(line)

    def isatty(self) -> bool:
        return False
