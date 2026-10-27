"""Build a stats adapter for a text metrics endpoint: research the format first, then a spec, then the oracle.

The endpoint's text is runtime data: it is shown only to the local model, whatever the routing profile.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

import httpx

from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError, parse_json
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.forge.stats import ORACLE_VERSION, CapabilityCard, StatsAdapter, admit, known_format, oracle, read
from unbidden.store import Store

COLLECTION = "stats_capabilities"
SHOWN = 40
SEED = 13
SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "line": {"type": "string", "maxLength": 300},
        "entity": {"type": ["string", "null"], "maxLength": 300},
    },
    "required": ["line", "entity"],
    "additionalProperties": False,
}


@dataclass
class BuildResult:
    adapter: StatsAdapter | None
    decision: str  # built | reuse:<format> | failed
    notes: list[str] = field(default_factory=list[str])


def fetch(url: str, timeout_s: float = 3.0) -> list[str]:
    response = httpx.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.text.splitlines()


def split(lines: list[str]) -> tuple[list[str], list[str]]:
    """A seeded sample for the model, spread over the whole text; the rest is held out for the oracle."""
    content = [ln for ln in lines if ln.strip()]
    rng = random.Random(SEED)
    shown_idx = set(rng.sample(range(len(content)), min(SHOWN, len(content) // 3)))
    return [ln for i, ln in enumerate(content) if i in shown_idx], [
        ln for i, ln in enumerate(content) if i not in shown_idx
    ]


async def build(
    brain: Brain, store: Store, source: str, lines: list[str], *, permissions: list[str], tries: int = 4
) -> BuildResult:
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
    feedback = ""
    for attempt in range(tries):
        try:
            response = await brain.complete(
                LLMRequest(
                    purpose="forge.stats",
                    tier=Tier.LOCAL,
                    response_schema=SPEC_SCHEMA,
                    max_tokens=1500,
                    prompt_sha256=prompt.sha256,
                    messages=[
                        Message(
                            role="user",
                            source="runtime",
                            content=prompt.render(
                                schema=json.dumps(SPEC_SCHEMA), feedback=feedback, source=source, lines="\n".join(shown)
                            ),
                        )
                    ],
                )
            )
            spec = parse_json(response.content)
        except (BrainError, ProviderError, ValueError) as exc:
            result.notes.append(f"attempt {attempt + 1}: {exc}")
            continue
        line, entity = spec["line"], spec.get("entity")
        problems = admit(line, entity)
        if not problems:
            probe = StatsAdapter(source=source, version=0, line=line, entity=entity, card=_card(source, permissions))
            missed = [ln for ln in shown if not read(probe, [ln])]
            if missed:
                problems.append(f"does not read {len(missed)} of the lines shown, e.g. {missed[0][:100]!r}")
        if problems:
            feedback = f"Your previous answer was {json.dumps(spec)}. It was refused:\n- " + "\n- ".join(problems[:4])
            result.notes.append(f"attempt {attempt + 1} refused: {problems[0]}")
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
                "problems": judged.problems,
            },
            failures=[{"attempt": str(i + 1), "why": n} for i, n in enumerate(result.notes)],
            provenance={"origin": "local", "attempts": attempt + 1, "shown_lines": len(shown)},
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
            f"Your previous answer was {json.dumps(spec)}. On other lines of the same endpoint:\n- "
            + "\n- ".join(judged.problems[:4])
        )
        result.notes.append(f"attempt {attempt + 1} failed the oracle: {judged.problems[0]}")
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


def usable(store: Store, source: str) -> StatsAdapter | None:
    """The newest adapter for a source that passed the current oracle and is not disabled."""
    candidates = [
        a
        for a in store.list(COLLECTION, StatsAdapter)
        if a.source == source and a.status in ("validated", "approved") and a.quality.get("oracle") == ORACLE_VERSION
    ]
    return max(candidates, key=lambda a: a.version) if candidates else None


def disable(store: Store, capability_id: str, why: str) -> StatsAdapter | None:
    adapter = store.get(COLLECTION, capability_id, StatsAdapter)
    if adapter is None:
        return None
    adapter.status = "disabled"
    adapter.failures = [*adapter.failures, {"attempt": "disabled", "why": why}]
    store.put(COLLECTION, adapter)
    return adapter
