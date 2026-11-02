"""The slash-command grammar."""

from __future__ import annotations

import pytest

from unbidden.tui.commands import SPECS, Command, completions, parse

pytestmark = pytest.mark.unit


def test_plain_text_is_a_chat_turn_and_empty_is_nothing() -> None:
    assert parse("why is the index slow") == "why is the index slow"
    assert parse("   ") is None


def test_commands_parse_with_their_arguments_and_flags() -> None:
    cmd = parse("/approve opp_1 --hours 2")
    assert isinstance(cmd, Command) and cmd.name == "approve" and cmd.error is None
    assert cmd.words == ["opp_1", "2"] and cmd.flags == {"--hours"}
    reject = parse('/reject opp_2 "not worth it"')
    assert isinstance(reject, Command) and reject.args == ["opp_2", "not worth it"]


def test_unknown_commands_and_wrong_arity_carry_an_error() -> None:
    nope = parse("/nope")
    assert isinstance(nope, Command) and nope.error == "unknown:nope"
    why = parse("/why")
    assert isinstance(why, Command) and why.error == "usage:/why <id>"


def test_aliases_and_the_question_mark() -> None:
    assert isinstance(parse("?"), Command) and parse("?").name == "help"  # type: ignore[union-attr]
    assert parse("/q").name == "quit"  # type: ignore[union-attr]


def test_completions_cover_every_command() -> None:
    assert completions("/") == [f"/{name}" for name in SPECS]
    assert completions("/st") == ["/start", "/stop"]
