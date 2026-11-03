"""Endpoint-to-table relations inferred by the local model from each handler's code.

The model may only pick among table names already in the World Model (an enum in the schema), so it cannot
invent a table; what it says is recorded as `inferred`, with the confidence an inference may carry.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.common import EpistemicStatus, EvidenceLevel, EvidenceRef, capped_confidence
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.contracts.world import Predicate, Relation, WorldModel

MAX_HANDLER_LINES = 80
_NEXT_DEF = re.compile(r"^(?:@|def |async def |class )", re.MULTILINE)


def handler_source(repo: Path, rev: str, file: str, line: int) -> str:
    text = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{file}"], capture_output=True, text=True).stdout
    lines = text.splitlines()[line - 1 :][:MAX_HANDLER_LINES]
    # Stop at the next decorator or definition at the handler's own depth, or shallower: a method of a class-based
    # controller ends at the next method, not at the next top-level definition.
    first = next((i for i, x in enumerate(lines) if re.match(r"\s*(async\s+)?def\s", x)), None)
    if first is None:
        return "\n".join(lines)
    depth = len(lines[first]) - len(lines[first].lstrip())
    for i in range(first + 1, len(lines)):
        stripped = lines[i].lstrip()
        if stripped and len(lines[i]) - len(stripped) <= depth and _NEXT_DEF.match(stripped):
            return "\n".join(lines[:i])
    return "\n".join(lines)


# Handlers per model call and the code they may add up to: well under the egress payload cap (20 KB) with the prompt's
# own text. Spoolman, campaign 12: one call per handler, 81 of 92 calls in a run, asked again at every map.
BATCH_HANDLERS = 8
BATCH_CHARS = 12_000


def _batches(pending: list[tuple[Any, ...]]) -> list[list[tuple[Any, ...]]]:
    """Consecutive handlers grouped by count and size; one too large for a batch goes alone, as before."""
    batches: list[list[tuple[Any, ...]]] = []
    current: list[tuple[Any, ...]] = []
    size = 0
    for item in pending:
        chars = len(item[3])
        if current and (len(current) >= BATCH_HANDLERS or size + chars > BATCH_CHARS):
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += chars
    if current:
        batches.append(current)
    return batches


def _relate(
    world: WorldModel, endpoint: Any, file: str, line: int, digest: str, reads: list[str], writes: list[str]
) -> int:
    evidence = [EvidenceRef(kind="file", locator=f"{file}:{line}", note=f"read by the local model; handler {digest}")]
    confidence = capped_confidence(0.9, EvidenceLevel.REASONABLE_SUSPICION)
    count = 0
    pairs: list[tuple[Predicate, list[str]]] = [("reads", reads), ("writes", writes)]
    for predicate, tables in pairs:
        for table in tables:
            world.relate(
                Relation(
                    src=endpoint.id,
                    dst=f"table:{table}",
                    predicate=predicate,
                    status=EpistemicStatus.INFERRED,
                    confidence=confidence,
                    evidence=evidence,
                )
            )
            count += 1
    return count


async def infer_endpoint_tables(
    repo: Path, rev: str, world: WorldModel, brain: Brain, *, limit: int = 40, store: Any = None
) -> int:
    """Which tables each endpoint's handler reads and writes, from the local model: several handlers per call, and
    a handler whose code has not changed since it was last read (`store`'s cache, by the code's digest) is not
    asked again: the previous answer is related again."""
    tables = sorted(r.name for r in world.of_kind("table"))
    if not tables:
        return 0
    item = {
        "type": "object",
        "properties": {
            "reads": {"type": "array", "items": {"type": "string", "enum": tables}},
            "writes": {"type": "array", "items": {"type": "string", "enum": tables}},
        },
        "required": ["reads", "writes"],
        "additionalProperties": False,
    }
    prompt = load_prompt("world_endpoint_tables")
    count = 0
    pending: list[tuple[Any, ...]] = []
    for endpoint in [e for e in world.of_kind("endpoint") if e.attributes.get("file")][:limit]:
        file, line = str(endpoint.attributes["file"]), int(endpoint.attributes.get("line") or 1)
        code = handler_source(repo, rev, file, line)
        digest = hashlib.sha256(code.encode()).hexdigest()[:16]
        known = store.get_value(f"endpoint_tables:{endpoint.id}") if store is not None else None
        if isinstance(known, dict) and known.get("sha") == digest and known.get("tables") == tables:
            count += _relate(world, endpoint, file, line, digest, list(known["reads"]), list(known["writes"]))
            continue
        pending.append((endpoint, file, line, code, digest))
    for batch in _batches(pending):
        names = [str(e.name) for e, *_ in batch]
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {name: item for name in names},
            "required": names,
            "additionalProperties": False,
        }
        handlers = "\n\n".join(f"Handler `{e.name}` in `{file}`:\n```\n{code}\n```" for e, file, _, code, _ in batch)
        try:
            value, _ = await brain.complete_json(
                LLMRequest(
                    purpose="world.endpoint_tables",
                    tier=Tier.LOCAL,
                    messages=[
                        Message(
                            role="user",
                            source="repo",
                            content=prompt.render(tables=", ".join(tables), schema=str(schema), handlers=handlers),
                        )
                    ],
                    response_schema=schema,
                    max_tokens=max(300, 120 * len(batch)),
                    prompt_sha256=prompt.sha256,
                )
            )
        except (BrainError, ProviderError):
            continue
        for endpoint, file, line, _code, digest in batch:
            got = value.get(str(endpoint.name)) if isinstance(value, dict) else None
            got = got if isinstance(got, dict) else {}
            reads = sorted(set(got.get("reads") or []) & set(tables))
            writes = sorted(set(got.get("writes") or []) & set(tables))
            if store is not None:
                store.set_value(f"endpoint_tables:{endpoint.id}",
                                {"sha": digest, "tables": tables, "reads": reads, "writes": writes})  # fmt: skip
            count += _relate(world, endpoint, file, line, digest, reads, writes)
    return count
