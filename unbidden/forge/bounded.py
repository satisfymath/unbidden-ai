"""Patterns a model wrote run on RE2 only: time linear in the input, whatever the pattern.

Python's `re` backtracks, and no admission rule catches every catastrophic form (alternation and optional repeats
slip through any syntactic check). RE2 has no backtracking, so it cannot blow up; what it cannot express
(backreferences, lookaround) is refused at compile time rather than run slowly. Unbidden's own fixed patterns stay on
`re`: they are code, reviewed with it.
"""

from __future__ import annotations

from typing import Any, Protocol

import re2  # pyright: ignore[reportMissingTypeStubs]

_OPTIONS = re2.Options()
_OPTIONS.log_errors = False  # a refused pattern is a reason in the result, not a line on stderr


class Match(Protocol):
    def __getitem__(self, group: str, /) -> Any: ...
    def groupdict(self) -> dict[str, str | None]: ...


class Pattern(Protocol):
    groups: int
    groupindex: dict[str, int]

    def search(self, text: str, /) -> Match | None: ...
    def match(self, text: str, /) -> Match | None: ...
    def fullmatch(self, text: str, /) -> Match | None: ...


class Unbounded(ValueError):
    """A pattern RE2 cannot run: it would need backtracking, or does not compile at all."""


def compile_untrusted(pattern: str) -> Pattern:
    try:
        compiled: Pattern = re2.compile(pattern, _OPTIONS)  # pyright: ignore[reportAssignmentType]
    except re2.error as exc:
        raise Unbounded(f"cannot run in linear time (RE2): {exc}") from exc
    return compiled
