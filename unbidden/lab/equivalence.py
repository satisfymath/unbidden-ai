"""Whether two sessions answered the same, when the application generates its own ids and times (stage 10).

Every session starts from a fresh database with the same data, but the records the application creates get new ids
(uuid4) and creation times (fst: no two base sessions answered alike). No value is set aside for its shape. Two
responses are equivalent when they are equal, or when a value of one stands for a value of the other through one
correspondence kept for the whole session: the same base id always meets the same id on the other side and no two
base ids meet one, and times keep their order. An item whose owner changed, two dates exchanged, a value replaced by
another, or a list in another order are all differences.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")


def _kind(value: Any) -> str | None:
    """Which values may stand for another: those the application generates, an id or a time."""
    if not isinstance(value, str):
        return None
    if UUID.fullmatch(value):
        return "id"
    if TIME.fullmatch(value):
        return "time"
    return None


class Correspondence:
    """One session's mapping of generated values to the reference's, one to one, per kind."""

    def __init__(self) -> None:
        self.forward: dict[str, dict[str, str]] = {"id": {}, "time": {}}
        self.backward: dict[str, dict[str, str]] = {"id": {}, "time": {}}

    def admit(self, kind: str, a: str, b: str) -> str | None:
        here, there = self.forward[kind].get(a), self.backward[kind].get(b)
        if here is None and there is None:
            self.forward[kind][a], self.backward[kind][b] = b, a
            return None
        if here == b:
            return None
        if here is not None:
            return f"{a} stands for {here} elsewhere, here for {b}"
        return f"{b} already stands for {there}, here for {a}"

    def order(self) -> str | None:
        """Times keep their order: the earlier of two reference times is the earlier on the other side."""
        pairs = sorted(self.forward["time"].items(), key=lambda p: _instant(p[0]))
        for (a1, b1), (a2, b2) in pairwise(pairs):
            if _instant(a1) < _instant(a2) and not _instant(b1) < _instant(b2):
                return f"times out of order: {a1} < {a2}, but {b1} >= {b2}"
        return None


def _instant(text: str) -> float:
    """Seconds since the epoch; a time without an offset is read as UTC (both sides are the same application's)."""
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def difference(a: Any, b: Any, link: Correspondence, path: str = "$") -> str | None:
    """The first difference between `a` (the reference) and `b`, or None when they are equivalent under `link`."""
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return f"{path}: fields {sorted(a.keys() ^ b.keys())} on one side only"
        for key in a:
            found = difference(a[key], b[key], link, f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items against {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = difference(x, y, link, f"{path}[{i}]")
            if found:
                return found
        return None
    kind = _kind(a)
    if kind is not None and kind == _kind(b) and isinstance(a, str) and isinstance(b, str):
        problem = link.admit(kind, a, b)
        return f"{path}: {problem}" if problem else None
    if a != b or type(a) is not type(b):
        return f"{path}: {str(a)[:80]!r} against {str(b)[:80]!r}"
    return None


def sessions_differ(reference: list[Any], other: list[Any]) -> str | None:
    """Two sessions' responses, call by call, under one correspondence for the whole session."""
    if len(reference) != len(other):
        return f"{len(reference)} responses against {len(other)}"
    link = Correspondence()
    for i, (a, b) in enumerate(zip(reference, other, strict=True)):
        found = difference(a, b, link, f"call {i + 1}")
        if found:
            return found
    return link.order()
