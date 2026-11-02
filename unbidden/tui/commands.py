"""Slash commands: the grammar and the registry. Pure: a line in, a `Command` or chat text out."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Spec:
    usage: str
    help: str
    min_args: int = 0
    max_args: int | None = 0  # None: any number


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
    "help": Spec("/help", "what you can do here"),
    "start": Spec("/start [--ui] [--force]", "run the agent in the background; --ui serves the dashboard", 0, 2),
    "stop": Spec("/stop", "stop the agent cleanly; nothing stays frozen"),
    "kill": Spec("/kill [reason]", "engage the kill switch: nothing runs or leaves until /resume", 0, None),
    "resume": Spec("/resume", "release the kill switch"),
    "inbox": Spec("/inbox [--all]", "open opportunities, most proven first", 0, 1),
    "why": Spec("/why <id>", "every decision, verdict and outbound payload behind one opportunity", 1, 1),
    "approve": Spec("/approve <id> [--hours N]", "let the pull request for this opportunity open", 1, 3),
    "reject": Spec("/reject <id> <reason>", "close this opportunity with your reason", 2, None),
    "activity": Spec("/activity", "found, decided, checked, asked, proven, spent"),
    "spend": Spec("/spend", "the machine's spend ledger and its cap"),
    "doctor": Spec("/doctor", "what this machine provides, required or optional for your option"),
    "ui": Spec("/ui [--open]", "open or reuse the dashboard in the browser", 0, 1),
    "setup": Spec("/setup [section|--all]", "the guided configuration, resumable", 0, 1),
    "log": Spec("/log", "show or hide the agent's log"),
    "verbose": Spec("/verbose", "show or hide every allowed egress and model call"),
    "clear": Spec("/clear", "clear the feed"),
    "quit": Spec("/quit", "leave; the agent keeps running"),
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
