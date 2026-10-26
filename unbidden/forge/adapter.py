"""A log adapter is data, not code: one regular expression with named groups, run by trusted code.

The model proposes it; admission rejects shapes that can hang a regex engine; an oracle with no model judges it
on lines the model never saw. Only then may a person (or an autonomous mandate) turn it on.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, new_id, utc_now

FIELDS = ("method", "path", "status", "level", "message")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
MAX_PATTERN = 300
MAX_GROUPS = 8
MIN_HELDOUT = 20
MIN_COVERAGE = 0.80
MAX_US_PER_LINE = 200.0


class LogAdapter(Contract):
    id: str = Field(default_factory=lambda: new_id("cap"))
    source: str  # e.g. "compose:backend"
    version: int
    pattern: str
    status: str = "validated"  # validated | rejected | approved | disabled
    quality: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.pattern.encode()).hexdigest()


_BACKREF = re.compile(r"\\[1-9]|\(\?P=")
_NESTED = re.compile(r"\((?:[^()\\]|\\.)*[+*}]\)\s*[+*{]")


def admit(pattern: str) -> list[str]:
    """Reasons to refuse a pattern before it ever runs on real data. Empty means admitted."""
    problems: list[str] = []
    if len(pattern) > MAX_PATTERN:
        problems.append(f"longer than {MAX_PATTERN} characters")
    if _BACKREF.search(pattern):
        problems.append("uses a backreference")
    if _NESTED.search(pattern):
        problems.append("nests quantifiers (catastrophic backtracking)")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return [*problems, f"does not compile: {exc}"]
    if compiled.groups > MAX_GROUPS:
        problems.append(f"more than {MAX_GROUPS} groups")
    unknown = set(compiled.groupindex) - set(FIELDS)
    if unknown:
        problems.append(f"unknown fields {sorted(unknown)}; allowed: {list(FIELDS)}")
    if not {"method", "path", "status"} <= set(compiled.groupindex):
        problems.append("needs the fields method, path and status")
    return problems


def parse_line(compiled: re.Pattern[str], line: str) -> dict[str, str] | None:
    match = compiled.search(line)
    return None if match is None else {k: v for k, v in match.groupdict().items() if v is not None}


@dataclass(frozen=True)
class OracleResult:
    passed: bool
    access_lines: int
    parsed: int
    coverage: float
    us_per_line: float
    problems: list[str]


def oracle(pattern: str, heldout: list[str]) -> OracleResult:
    """Judge an adapter with code only, on lines the model never saw."""
    compiled = re.compile(pattern)
    access = [ln for ln in heldout if re.search(r'"[A-Z]+ /\S* HTTP/[\d.]+"', ln)]
    problems: list[str] = []
    if len(access) < MIN_HELDOUT:
        problems.append(f"only {len(access)} held-out access lines; at least {MIN_HELDOUT} are needed to judge")
    started = time.perf_counter()
    parsed = 0
    for line in access:
        fields = parse_line(compiled, line)
        if fields is None:
            continue
        ok = (
            fields.get("method") in METHODS
            and fields.get("path", "").startswith("/")
            and fields.get("status", "").isdigit()
            and 100 <= int(fields["status"]) <= 599
            and all(value in line for value in fields.values())
        )
        parsed += int(ok)
    elapsed = (time.perf_counter() - started) * 1e6 / max(1, len(access))
    coverage = parsed / len(access) if access else 0.0
    if coverage < MIN_COVERAGE:
        problems.append(f"parsed {coverage:.0%} of held-out access lines correctly; at least {MIN_COVERAGE:.0%} needed")
    if elapsed > MAX_US_PER_LINE:
        problems.append(f"{elapsed:.0f} µs per line; at most {MAX_US_PER_LINE:.0f}")
    return OracleResult(not problems, len(access), parsed, coverage, elapsed, problems)
