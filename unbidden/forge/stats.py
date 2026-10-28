"""A stats adapter reads a text metrics endpoint no installed connector understands. It is data, not code.

The need: a service of the project serves numbers as text on a published port (Envoy's `/stats`, nginx's
`stub_status`, a home-grown `/status`) and nothing Unbidden has can read them. Before building, the format is checked
against the ones a reader already exists for; only an unknown one is built.

The spec is two regular expressions run by trusted code: `line` splits a line into `name` and `value`, and `entity`
optionally splits a name into the thing measured (`entity`, an upstream, a pool) and the `metric`. A model proposes
the spec from a sample; admission refuses shapes that can hang; an oracle with no model judges it on lines it never
saw, and on the same lines with their numbers changed (an adapter that memorized values reads the old ones).
"""

from __future__ import annotations

import hashlib
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, new_id, utc_now
from unbidden.forge.adapter import _BACKREF, _NESTED, MAX_PATTERN  # pyright: ignore[reportPrivateUsage]
from unbidden.forge.bounded import Unbounded, compile_untrusted

ORACLE_VERSION = 1
MIN_HELDOUT = 50
MIN_COVERAGE = 0.95
MAX_US_PER_LINE = 100.0
KNOWN_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Prometheus text exposition: `name{labels} value [timestamp]`, with `# HELP` / `# TYPE` comments.
    ("prometheus-text", re.compile(r"^(# (HELP|TYPE) |[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})? -?[\d.eE+-]+|NaN|[+-]Inf)")),
)


class CapabilityCard(Contract):
    """What every capability Forge builds declares, whatever its kind. Permissions are the ones the need was
    granted; a capability can never ask for more than its builder had."""

    purpose: str
    kind: str
    input: dict[str, str]
    output: dict[str, str]
    dependencies: list[str] = Field(default_factory=list)
    permissions: list[str]
    data_sources: list[str]
    privacy: str
    side_effects: str = "none: reads text it is given; no network, no files, no processes"
    limits: dict[str, float | int] = Field(default_factory=dict)
    disable: str = "`unbidden forge disable <id>`: status becomes disabled and nothing reads through it again"


class StatsAdapter(Contract):
    id: str = Field(default_factory=lambda: new_id("cap"))
    kind: str = "stats"
    source: str  # "http://127.0.0.1:10000/stats (frontend-proxy)"
    version: int
    line: str  # regex with groups `name` and `value`
    entity: str | None = None  # regex on a name with groups `entity` and `metric`
    status: str = "validated"  # validated | rejected | approved | disabled
    card: CapabilityCard
    tests: list[dict[str, str]] = Field(default_factory=list)  # kept, so the contract can be re-checked later
    quality: dict[str, Any] = Field(default_factory=dict)
    failures: list[dict[str, str]] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(f"{self.line}\n{self.entity}".encode()).hexdigest()


def known_format(lines: list[str]) -> str | None:
    """A format a reader already exists for, when most non-empty lines fit it: then nothing is built."""
    content = [ln for ln in lines if ln.strip()]
    for name, pattern in KNOWN_FORMATS:
        if content and sum(1 for ln in content if pattern.match(ln)) / len(content) >= 0.9:
            return name
    return None


def admit(line: str, entity: str | None) -> list[str]:
    problems: list[str] = []
    for label, pattern, groups in (("line", line, {"name", "value"}), ("entity", entity, {"entity", "metric"})):
        if pattern is None:
            continue
        if len(pattern) > MAX_PATTERN:
            problems.append(f"{label}: longer than {MAX_PATTERN} characters")
        if _BACKREF.search(pattern):
            problems.append(f"{label}: uses a backreference")
        if _NESTED.search(pattern):
            problems.append(f"{label}: nests quantifiers (catastrophic backtracking)")
        try:
            compiled = compile_untrusted(pattern)
        except Unbounded as exc:
            problems.append(f"{label}: {exc}")
            continue
        if set(compiled.groupindex) != groups:
            problems.append(f"{label}: needs exactly the groups {sorted(groups)}, has {sorted(compiled.groupindex)}")
    return problems


@dataclass(frozen=True)
class Reading:
    name: str
    value: float
    entity: str | None
    metric: str | None


def read(adapter: StatsAdapter, lines: list[str]) -> list[Reading]:
    line_re = compile_untrusted(adapter.line)
    entity_re = compile_untrusted(adapter.entity) if adapter.entity else None
    found: list[Reading] = []
    for raw in lines:
        match = line_re.fullmatch(raw.strip())
        if match is None:
            continue
        try:
            value = float(match["value"])
        except ValueError:
            continue
        split = entity_re.fullmatch(match["name"]) if entity_re else None
        found.append(
            Reading(match["name"], value, split["entity"] if split else None, split["metric"] if split else None)
        )
    return found


_NUMBER = re.compile(r"(?<![\w.])\d+(\.\d+)?(?![\w.])")
_SCALAR = re.compile(r"[:=\s]\s*-?\d+(\.\d+)?\s*$")


def scalar(line: str) -> bool:
    """A line whose value is one number at its end. Others (histograms, lists of quantiles) are another shape:
    an adapter may leave them unread, and says how many it left."""
    return bool(_SCALAR.search(line.rstrip()))


@dataclass(frozen=True)
class OracleResult:
    passed: bool
    lines: int  # held-out lines with one number at their end: what an adapter must read
    parsed: int
    coverage: float
    us_per_line: float
    problems: list[str]


def oracle(line: str, entity: str | None, heldout: list[str], seed: int = 7) -> OracleResult:
    """Judge a spec with code only, on lines the model never saw and on those lines with other numbers."""
    probe = StatsAdapter(source="oracle", version=0, line=line, entity=entity, card=_ORACLE_CARD)
    content = [ln for ln in heldout if ln.strip() and scalar(ln)]
    problems: list[str] = []
    if len(content) < MIN_HELDOUT:
        problems.append(f"only {len(content)} held-out lines; at least {MIN_HELDOUT} are needed to judge")
    per_line = [(ln, read(probe, [ln])) for ln in content]
    elapsed = _us_per_line(probe, content)
    readings = [r for _, got in per_line for r in got]
    coverage = len(readings) / len(content) if content else 0.0
    if coverage < MIN_COVERAGE:
        problems.append(f"read {coverage:.0%} of held-out lines; at least {MIN_COVERAGE:.0%} needed")
    if any(got[0].name not in ln or _value_text(ln) == "" for ln, got in per_line if got):
        problems.append("a name it read is not in its line, or a line it read has no number")
    # Metamorphic: replace each line's value with another number; the adapter must read the new one.
    rng = random.Random(seed)
    for raw in rng.sample(content, min(30, len(content))):
        before = read(probe, [raw])
        if not before:
            continue
        new = rng.randint(1000, 999_999)
        changed = raw.rstrip()[: raw.rstrip().rfind(_value_text(raw))] + str(new) if _value_text(raw) else raw
        after = read(probe, [changed])
        if not after or after[0].value != float(new) or after[0].name != before[0].name:
            problems.append(f"does not read a changed value: {changed[:80]!r}")
            break
    if entity is not None:
        split = [r for r in readings if r.entity is not None]
        if len(split) < len(readings) * 0.2:
            problems.append("the entity pattern splits almost no name")
        if any(r.entity and r.entity.isdigit() for r in split):
            problems.append("an entity is a number: values leaked into names")
    if elapsed > MAX_US_PER_LINE:
        problems.append(f"{elapsed:.0f} µs per line; at most {MAX_US_PER_LINE:.0f}")
    return OracleResult(not problems, len(content), len(readings), coverage, elapsed, problems)


def _us_per_line(probe: StatsAdapter, content: list[str], passes: int = 3) -> float:
    """What reading costs per line, as a reader runs: one batch, its pattern compiled once. The best of a few
    passes, so another process's load on the machine is not charged to the pattern. (Timing `read` line by line
    measured compiling the pattern once per line: 12 µs here, over the bound on a slower or busy machine.)"""
    best = float("inf")
    for _ in range(passes):
        started = time.perf_counter()
        read(probe, content)
        best = min(best, time.perf_counter() - started)
    return best * 1e6 / max(1, len(content))


def _value_text(raw: str) -> str:
    """The last number of a line: where a stats format keeps its value."""
    numbers = list(_NUMBER.finditer(raw.rstrip()))
    return numbers[-1].group(0) if numbers else ""


_ORACLE_CARD = CapabilityCard(
    purpose="oracle probe",
    kind="stats",
    input={},
    output={},
    permissions=[],
    data_sources=[],
    privacy="n/a",
)


def deltas(adapter: StatsAdapter, before: list[str], after: list[str], metric: str) -> dict[str, float]:
    """How much `metric` grew per entity between two snapshots: counters are cumulative, change is what matters."""
    first = {(r.entity, r.metric): r.value for r in read(adapter, before) if r.metric == metric}
    second = {(r.entity, r.metric): r.value for r in read(adapter, after) if r.metric == metric}
    return {str(e): second[(e, m)] - first.get((e, m), 0.0) for (e, m) in second if e is not None}
