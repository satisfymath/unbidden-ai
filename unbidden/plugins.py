"""Extension points: what an installed package may add to Unbidden, and nothing it may widen.

A package declares entry points in three groups; Unbidden loads them by name when the registry is first read:

- `unbidden.connectors`: a `connect.base.Connector` (or a callable returning one) for a kind of resource a grant
  may name (`mqtt`, `opcua`, ...). It is checked and gated exactly like the shipped ones: every read and write
  still passes `connect.base.require`, the mandate's grant, the egress policy and the credential broker.
- `unbidden.ask_kinds`: an `AskKind`, a class of question for a person with the effect its answer applies.
- `unbidden.skills`: a `Skill`, a capability with a card (purpose, inputs, outputs, permissions, limits) that can
  be listed and run.

Rules that hold for every group: a plugin never replaces a shipped name; a plugin that fails to load, or is not
what its group expects, is left out and reported (`problems`, shown by `unbidden plugins` and `unbidden doctor`),
and the agent runs without it. Installing a plugin is trusting its code, like any dependency: it runs in the
agent's process. What it cannot do is grant itself anything: permissions come from the mandate alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Protocol, runtime_checkable

CONNECTORS = "unbidden.connectors"
ASK_KINDS = "unbidden.ask_kinds"
SKILLS = "unbidden.skills"
GROUPS = (CONNECTORS, ASK_KINDS, SKILLS)

# The names Unbidden ships, which no plugin may take.
NATIVE_CONNECTORS = frozenset({"github", "http_api", "postgres"})
NATIVE_ASK_KINDS = frozenset(
    {"approval", "credential", "access", "hold", "deploy_steps", "spend", "capability", "registry", "drill", "resume",
     "ledger", "connection"}
)  # fmt: skip
_RESERVED: dict[str, frozenset[str]] = {CONNECTORS: NATIVE_CONNECTORS, ASK_KINDS: NATIVE_ASK_KINDS, SKILLS: frozenset()}


@runtime_checkable
class AskKind(Protocol):
    """A class of question a plugin asks a person. `apply` runs when the person picks an option and returns, in
    one line, what that did; raise `ValueError` when the answer cannot be applied. An ask it opens offers the
    option `later` like any other, which never reaches `apply`."""

    kind: str

    def apply(self, ws: Any, store: Any, ask: Any, option: str, value: str | None, who: str) -> str: ...


@dataclass(frozen=True)
class SkillCard:
    """What a skill is, readable before it runs: the same questions a forged capability's card answers."""

    purpose: str  # one line: what it finds out or produces
    inputs: dict[str, str] = field(default_factory=dict[str, str])  # name -> what it is, with its unit
    outputs: dict[str, str] = field(default_factory=dict[str, str])
    permissions: tuple[str, ...] = ()  # what it needs granted to run ("sandbox.run", "connection.read")
    limits: dict[str, float] = field(default_factory=dict[str, float])  # e.g. timeout_s, max_memory_mb
    evidence_level: int | None = None  # the highest level a result of it supports on its own


@runtime_checkable
class Skill(Protocol):
    name: str
    card: SkillCard

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Plugin:
    group: str
    name: str
    obj: Any
    source: str  # the distribution that provides it, with its version


@dataclass(frozen=True)
class Problem:
    group: str
    name: str
    source: str
    why: str


_cache: tuple[dict[str, dict[str, Plugin]], list[Problem]] | None = None


def _source(entry: metadata.EntryPoint) -> str:
    dist = entry.dist
    return f"{dist.name} {dist.version}" if dist is not None else entry.value


def _check(group: str, name: str, obj: Any) -> str | None:
    """Why the loaded object is not what its group expects, or None."""
    if group == CONNECTORS:
        if not (callable(getattr(obj, "validate", None)) and callable(getattr(obj, "check", None))):
            return "not a connector: it needs validate(grant) and check(grant)"
        if getattr(obj, "kind", None) != name:
            return f"its kind is {getattr(obj, 'kind', None)!r}, not the name it is registered under"
    elif group == ASK_KINDS:
        if not isinstance(obj, AskKind):
            return "not an ask kind: it needs kind and apply(ws, store, ask, option, value, who)"
        if obj.kind != name:
            return f"its kind is {obj.kind!r}, not the name it is registered under"
    elif group == SKILLS:
        if not isinstance(obj, Skill) or not isinstance(obj.card, SkillCard):
            return "not a skill: it needs name, card (a SkillCard) and run(inputs)"
        if obj.name != name:
            return f"its name is {obj.name!r}, not the name it is registered under"
    return None


def _load() -> tuple[dict[str, dict[str, Plugin]], list[Problem]]:
    found: dict[str, dict[str, Plugin]] = {group: {} for group in GROUPS}
    problems: list[Problem] = []
    for group in GROUPS:
        for entry in sorted(metadata.entry_points(group=group), key=lambda e: (e.name, e.value)):
            source = _source(entry)
            if entry.name in _RESERVED[group]:
                problems.append(Problem(group, entry.name, source, "the name is one Unbidden ships; left out"))
                continue
            if entry.name in found[group]:
                other = found[group][entry.name].source
                problems.append(Problem(group, entry.name, source, f"already provided by {other}; left out"))
                continue
            try:
                obj = entry.load()
                if isinstance(obj, type):  # a class is registered: one instance serves
                    obj = obj()
            except Exception as exc:  # a plugin's import or constructor may fail in any way; the agent goes on
                problems.append(Problem(group, entry.name, source, f"failed to load: {type(exc).__name__}: {exc}"))
                continue
            why = _check(group, entry.name, obj)
            if why is not None:
                problems.append(Problem(group, entry.name, source, why))
                continue
            found[group][entry.name] = Plugin(group, entry.name, obj, source)
    return found, problems


def _state() -> tuple[dict[str, dict[str, Plugin]], list[Problem]]:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def reload() -> None:
    """Forget what was loaded (a package was installed or removed; a test changed the entry points)."""
    global _cache
    _cache = None


def plugins(group: str) -> dict[str, Plugin]:
    return dict(_state()[0][group])


def problems() -> list[Problem]:
    return list(_state()[1])


def connectors() -> dict[str, Any]:
    return {name: p.obj for name, p in _state()[0][CONNECTORS].items()}


def ask_kinds() -> dict[str, AskKind]:
    return {name: p.obj for name, p in _state()[0][ASK_KINDS].items()}


def skills() -> dict[str, Skill]:
    return {name: p.obj for name, p in _state()[0][SKILLS].items()}


def known_ask_kinds() -> frozenset[str]:
    return NATIVE_ASK_KINDS | frozenset(_state()[0][ASK_KINDS])


def summary() -> dict[str, Any]:
    found, bad = _state()
    return {
        "plugins": [
            {"group": p.group, "name": p.name, "source": p.source} for group in GROUPS for p in found[group].values()
        ],
        "problems": [{"group": b.group, "name": b.name, "source": b.source, "why": b.why} for b in bad],
    }
