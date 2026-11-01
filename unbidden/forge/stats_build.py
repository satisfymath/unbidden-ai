"""Build a stats adapter for a text metrics endpoint: research the format first, then a spec, then the oracle.

The endpoint's text is runtime data: it is shown only to the local model, whatever the routing profile.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

import httpx

from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.bridge.rename import build_map
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.forge.build import LogTransform
from unbidden.forge.stats import (
    ORACLE_VERSION,
    CapabilityCard,
    StatsAdapter,
    admit,
    known_format,
    oracle,
    read,
    scalar,
)
from unbidden.guardian.scanner import SensitiveTermIndex
from unbidden.store import Store

COLLECTION = "stats_capabilities"
SHOWN = 40
SEED = 13
_LAST_NUMBER = re.compile(r"-?\d+(\.\d+)?(?=\s*$)")


@dataclass
class BuildResult:
    adapter: StatsAdapter | None
    decision: str  # built | reuse:<format> | failed
    notes: list[str] = field(default_factory=list[str])


def fetch(url: str, timeout_s: float = 3.0) -> list[str]:
    response = httpx.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.text.splitlines()


_SPEC_LINE = re.compile(r"^\s*(LINE|ENTITY):[ \t]*(.+?)\s*$", re.MULTILINE)


def parse_spec(text: str) -> tuple[str, str | None]:
    """Patterns come back as raw text (D-005: code is never exchanged inside JSON, where escapes get lost)."""
    found = {key: value for key, value in _SPEC_LINE.findall(text)}
    if "LINE" not in found:
        raise ValueError("no `LINE:` in the answer; answer with one fenced block holding LINE: and ENTITY:")
    entity = found.get("ENTITY")
    return found["LINE"], None if not entity or entity.lower() in ("none", "null") else entity


def split(lines: list[str]) -> tuple[list[str], list[str]]:
    """A seeded sample for the model, spread over the whole text; the rest is held out for the oracle."""
    content = [ln for ln in lines if ln.strip()]
    rng = random.Random(SEED)
    shown_idx = set(rng.sample(range(len(content)), min(SHOWN, len(content) // 3)))
    return [ln for i, ln in enumerate(content) if i in shown_idx], [
        ln for i, ln in enumerate(content) if i not in shown_idx
    ]


def stats_transform(lines: list[str], private: set[str], seed: int = SEED) -> LogTransform:
    """What a remote model may see of a stats endpoint: the project's own names (services, containers, tables) renamed,
    addresses replaced, and every value replaced by a random number (values can be business data). What is left is
    the metric vocabulary of the software that serves them."""
    rng = random.Random(seed)
    renamed = build_map({p for p in private if len(p) >= 3}, {}, lines)

    class _Stats(LogTransform):
        def apply(self, text: str) -> str:
            out = []
            for ln in super().apply(text).splitlines():
                out.append(_LAST_NUMBER.sub(lambda _: str(rng.randint(0, 99_999)), ln) if scalar(ln) else ln)
            return "\n".join(out)

    return _Stats(renamed, SensitiveTermIndex(private))


async def build(
    brain: Brain,
    store: Store,
    source: str,
    lines: list[str],
    *,
    permissions: list[str],
    tries: int = 4,
    private: set[str] | None = None,
) -> BuildResult:
    """Local model first. When it fails and `private` is given (the remote model is allowed), the bridge's view of
    the endpoint is sent to Muse Spark instead; whatever comes back is judged on the real lines, here."""
    result = await _build(brain, store, source, lines, permissions=permissions, tries=tries, transform=None)
    if result.decision == "failed" and private is not None:
        transform = stats_transform(lines, private)
        result.notes.append(f"bridge: {len(transform.rename.forward)} private names renamed, values randomized")
        bridged = await _build(brain, store, source, lines, permissions=permissions, tries=3, transform=transform)
        bridged.notes = [*result.notes, *bridged.notes]
        return bridged
    return result


async def _build(
    brain: Brain,
    store: Store,
    source: str,
    lines: list[str],
    *,
    permissions: list[str],
    tries: int,
    transform: LogTransform | None,
) -> BuildResult:
    reuse = reusable(store, lines)
    if reuse is not None:
        adopted = reuse.model_copy(
            update={
                "id": f"cap_{random.Random(source).getrandbits(64):016x}",
                "source": source,
                "version": 1 + len([a for a in store.list(COLLECTION, StatsAdapter) if a.source == source]),
                "provenance": {**reuse.provenance, "reused_from": reuse.id, "reused_source": reuse.source},
                "card": _card(source, permissions),
            }
        )
        store.put(COLLECTION, adopted)
        store.append_event(
            Event(
                type=EventType.CAPABILITY_BUILT,
                actor="forge",
                entity_id=adopted.id,
                payload={"decision": f"reuse:{reuse.id}", "source": source},
            )
        )
        return BuildResult(
            adopted, f"reuse:{reuse.id}", [f"{reuse.id} (built for {reuse.source}) passes the oracle here"]
        )
    known = known_format(lines)
    if known is not None:
        store.append_event(
            Event(
                type=EventType.CAPABILITY_BUILT, actor="forge", entity_id=source, payload={"decision": f"reuse:{known}"}
            )
        )
        return BuildResult(None, f"reuse:{known}", [f"{known}: a reader for this format exists; nothing built"])
    shown, heldout = split(lines)
    prompt = load_prompt("forge_stats")
    result = BuildResult(None, "failed")
    origin = "bridge" if transform else "local"
    view = transform.apply if transform else (lambda text: text)
    feedback = ""
    for attempt in range(tries):
        try:
            response = await brain.complete(
                LLMRequest(
                    purpose="forge.stats.bridge" if transform else "forge.stats",
                    tier=Tier.LOCAL,
                    max_tokens=4000,  # the local model thinks before answering; 1500 cut its answers off
                    prompt_sha256=prompt.sha256,
                    messages=[
                        Message(
                            role="user",
                            # Real stats are runtime data and stay local; the bridge's view is synthetic.
                            source="synthetic" if transform else "runtime",
                            content=prompt.render(
                                feedback=view(feedback),
                                source="a service's text metrics endpoint" if transform else source,
                                lines=view("\n".join(shown)),
                            ),
                        )
                    ],
                ),
                identifiers=transform.identifiers if transform else None,
            )
            line, entity = parse_spec(response.content)
        except (BrainError, ProviderError, ValueError) as exc:
            result.notes.append(f"{origin} attempt {attempt + 1}: {exc}")
            continue
        problems = admit(line, entity)
        if not problems:
            probe = StatsAdapter(source=source, version=0, line=line, entity=entity, card=_card(source, permissions))
            missed = [ln for ln in shown if scalar(ln) and not read(probe, [ln])]
            if missed:
                problems.append(f"does not read {len(missed)} of the lines shown, e.g. {missed[0][:100]!r}")
        if problems:
            feedback = f"Your previous answer was LINE: {line} / ENTITY: {entity}. It was refused:\n- " + "\n- ".join(
                problems[:4]
            )
            result.notes.append(f"{origin} attempt {attempt + 1} refused: {view(problems[0])}")
            continue
        judged = oracle(line, entity, heldout)
        version = 1 + len([a for a in store.list(COLLECTION, StatsAdapter) if a.source == source])
        adapter = StatsAdapter(
            source=source,
            version=version,
            line=line,
            entity=entity,
            status="validated" if judged.passed else "rejected",
            card=_card(source, permissions),
            tests=[{"line": ln} for ln in shown[:10]],
            quality={
                "oracle": ORACLE_VERSION,
                "heldout_lines": judged.lines,
                "coverage": round(judged.coverage, 4),
                "us_per_line": round(judged.us_per_line, 2),
                "unread_other_shapes": len([ln for ln in lines if ln.strip() and not scalar(ln)]),
                "problems": judged.problems,
            },
            failures=[{"attempt": str(i + 1), "why": n} for i, n in enumerate(result.notes)],
            provenance={"origin": origin, "attempts": attempt + 1, "shown_lines": len(shown)},
        )
        store.put(COLLECTION, adapter)
        store.append_event(
            Event(
                type=EventType.CAPABILITY_BUILT,
                actor="forge",
                entity_id=adapter.id,
                payload={"kind": "stats", "source": source, "status": adapter.status, "quality": adapter.quality},
            )
        )
        result.adapter = adapter
        result.decision = "built" if judged.passed else "failed"
        if judged.passed:
            return result
        feedback = (
            f"Your previous answer was LINE: {line} / ENTITY: {entity}. On other lines of the same endpoint:\n- "
            + "\n- ".join(judged.problems[:4])
        )
        result.notes.append(f"{origin} attempt {attempt + 1} failed the oracle: {view(judged.problems[0])}")
    return result


def _card(source: str, permissions: list[str]) -> CapabilityCard:
    return CapabilityCard(
        purpose=f"read the counters and gauges {source} serves as text",
        kind="stats",
        input={"lines": "list[str]: the endpoint's text, one metric per line"},
        output={"readings": "list[{name: str, value: float, entity: str | None, metric: str | None}]"},
        permissions=permissions,
        data_sources=[source],
        privacy="metric names may name internal services; readings stay local and are never sent to a model",
        limits={"max_pattern_chars": 300, "max_us_per_line": 100},
    )


def latest(store: Store, source: str) -> StatsAdapter | None:
    """The newest adapter for a source that passed the current oracle and is not disabled, usable or not."""
    candidates = [
        a
        for a in store.list(COLLECTION, StatsAdapter)
        if a.source == source and a.status in ("validated", "approved") and a.quality.get("oracle") == ORACLE_VERSION
    ]
    return max(candidates, key=lambda a: a.version) if candidates else None


def usable(store: Store, mandate: Mandate | None, source: str) -> StatsAdapter | None:
    """The newest adapter for a source that Unbidden may read through on its own: approved by a person, or the
    mandate lets it use what it built (the same gate as log adapters)."""
    from unbidden.forge.logs import permitted

    adapter = latest(store, source)
    return adapter if adapter is not None and permitted(adapter.status, mandate, source) else None


def reusable(store: Store, lines: list[str]) -> StatsAdapter | None:
    """A validated reader built for another source that the current oracle also passes on these lines: reused
    instead of building a new one (the same software, in another project, serves the same format)."""
    _, heldout = split(lines)
    for adapter in sorted(store.list(COLLECTION, StatsAdapter), key=lambda a: a.created_at, reverse=True):
        if adapter.status not in ("validated", "approved") or adapter.quality.get("oracle") != ORACLE_VERSION:
            continue
        if oracle(adapter.line, adapter.entity, heldout).passed:
            return adapter
    return None


def disable(store: Store, capability_id: str, why: str) -> StatsAdapter | None:
    adapter = store.get(COLLECTION, capability_id, StatsAdapter)
    if adapter is None:
        return None
    adapter.status = "disabled"
    adapter.failures = [*adapter.failures, {"attempt": "disabled", "why": why}]
    store.put(COLLECTION, adapter)
    return adapter
