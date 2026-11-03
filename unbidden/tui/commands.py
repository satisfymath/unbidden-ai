"""Slash commands: the grammar and the registry. Pure: a line in, a `Command` or chat text out."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from unbidden.tui.text import t


@dataclass(frozen=True)
class Spec:
    name: str
    min_args: int = 0
    max_args: int | None = 0  # None: any number

    @property
    def usage(self) -> str:  # the usage and the help live in the text table, so /help follows the language
        return t(f"cmd.{self.name}.usage")

    @property
    def help(self) -> str:
        return t(f"cmd.{self.name}.help")


@dataclass(frozen=True)
class Command:
    name: str
    args: list[str] = field(default_factory=list)
    raw: str = ""
    error: str | None = None  # unknown command or wrong arity; the app prints it and does nothing else

    @property
    def flags(self) -> set[str]:
        return {a for a in self.args if a.startswith("--")}

    @property
    def words(self) -> list[str]:
        return [a for a in self.args if not a.startswith("--")]


SPECS: dict[str, Spec] = {
    "help": Spec("help"),
    "start": Spec("start", 0, 2),
    "stop": Spec("stop"),
    "kill": Spec("kill", 0, None),
    "resume": Spec("resume"),
    "inbox": Spec("inbox", 0, 1),
    "why": Spec("why", 1, 1),
    "approve": Spec("approve", 1, 3),
    "reject": Spec("reject", 2, None),
    "activity": Spec("activity"),
    "spend": Spec("spend"),
    "doctor": Spec("doctor"),
    "ui": Spec("ui", 0, 1),
    "setup": Spec("setup", 0, 1),
    "key": Spec("key"),
    "language": Spec("language", 0, 1),
    "log": Spec("log"),
    "verbose": Spec("verbose"),
    "clear": Spec("clear"),
    "quit": Spec("quit"),
}

ALIASES: dict[str, str] = {"q": "quit", "exit": "quit", "h": "help", "?": "help", "status": "activity"}


def parse(line: str) -> Command | str | None:
    """Empty → None; `/name args` → Command (with `error` set when unknown or malformed); anything else → chat."""
    text = line.strip()
    if not text:
        return None
    if text == "?":
        return Command("help", raw=text)
    if not text.startswith("/"):
        return text
    try:
        parts = shlex.split(text[1:])
    except ValueError:
        parts = text[1:].split()
    if not parts:
        return Command("help", raw=text)
    name = ALIASES.get(parts[0].lower(), parts[0].lower())
    args = parts[1:]
    spec = SPECS.get(name)
    if spec is None:
        return Command(name, args, text, error=f"unknown:{name}")
    n = len(args)
    if n < spec.min_args or (spec.max_args is not None and n > spec.max_args):
        return Command(name, args, text, error=f"usage:{spec.usage}")
    return Command(name, args, text)


def completions(prefix: str) -> list[str]:
    """Command names that start with `prefix` (with or without the slash), for the prompt's Tab."""
    stem = prefix[1:] if prefix.startswith("/") else prefix
    return [f"/{name}" for name in SPECS if name.startswith(stem.lower())]


def help_lines() -> list[tuple[str, str]]:
    return [(spec.usage, spec.help) for spec in SPECS.values()]
