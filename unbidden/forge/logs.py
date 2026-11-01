"""Read a service's real traffic through an adapter Forge built: requests per route and status class."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.forge.adapter import ORACLE_VERSION, LogAdapter, parse_line
from unbidden.forge.bounded import compile_untrusted
from unbidden.guardian.policy import PolicyEngine
from unbidden.store import Store

COLLECTION = "capabilities"


def usable(store: Store, mandate: Mandate, source: str) -> LogAdapter | None:
    """The newest adapter for a source that passed its oracle and that the mandate (or a person) turned on."""
    candidates = sorted(
        (
            a
            for a in store.list(COLLECTION, LogAdapter)
            if a.source == source
            and a.status in ("validated", "approved")
            and a.quality.get("oracle") == ORACLE_VERSION  # judged by the current oracle, or not usable
        ),
        key=lambda a: a.version,
    )
    if not candidates:
        return None
    adapter = candidates[-1]
    return adapter if permitted(adapter.status, mandate, source) else None


def permitted(status: str, mandate: Mandate | None, source: str) -> bool:
    """The one gate for using a capability Forge built, log and stats readers alike: a person approved it, or it
    passed its oracle and the mandate lets Unbidden turn on what it built itself (`use_new_capabilities`)."""
    if status == "approved":
        return True
    if status != "validated" or mandate is None:
        return False
    verdict = PolicyEngine(mandate).evaluate(ActionRequest(capability="capability.use", purpose=f"read {source}"))
    return verdict.allowed


@dataclass(frozen=True)
class Traffic:
    lines: int
    parsed: int
    by_route: dict[str, Counter[str]]

    @property
    def server_errors(self) -> int:
        return sum(c["5xx"] for c in self.by_route.values())


def summarize(adapter: LogAdapter, lines: list[str], *, ignore_agents: tuple[str, ...] = ()) -> Traffic:
    compiled = compile_untrusted(adapter.pattern)
    by_route: dict[str, Counter[str]] = {}
    parsed = 0
    for line in lines:
        if any(a in line for a in ignore_agents):
            continue
        fields = parse_line(compiled, line)
        if not fields or "status" not in fields:
            continue
        parsed += 1
        route = f"{fields.get('method', '?')} {fields.get('path', '?').split('?')[0]}"
        by_route.setdefault(route, Counter())[f"{fields['status'][0]}xx"] += 1
    return Traffic(len(lines), parsed, by_route)
