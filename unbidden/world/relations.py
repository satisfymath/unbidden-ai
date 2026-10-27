"""Endpoint-to-table relations inferred by the local model from each handler's code.

The model may only pick among table names already in the World Model (an enum in the schema), so it cannot
invent a table; what it says is recorded as `inferred`, with the confidence an inference may carry.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.common import EpistemicStatus, EvidenceLevel, EvidenceRef, capped_confidence
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.contracts.world import Relation, WorldModel

MAX_HANDLER_LINES = 80
_NEXT_DEF = re.compile(r"^(?:@|def |async def |class )", re.MULTILINE)


def handler_source(repo: Path, rev: str, file: str, line: int) -> str:
    text = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{file}"], capture_output=True, text=True).stdout
    lines = text.splitlines()[line - 1 :]
    body = "\n".join(lines[:MAX_HANDLER_LINES])
    # Stop at the next top-level decorator or definition after the handler's own def line.
    first_def = body.find("def ")
    cut = _NEXT_DEF.search(body, first_def + 4) if first_def >= 0 else None
    return body[: cut.start()] if cut else body


async def infer_endpoint_tables(repo: Path, rev: str, world: WorldModel, brain: Brain, *, limit: int = 40) -> int:
    tables = sorted(r.name for r in world.of_kind("table"))
    if not tables:
        return 0
    schema: dict[str, Any] = {
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
    for endpoint in [e for e in world.of_kind("endpoint") if e.attributes.get("file")][:limit]:
        file, line = str(endpoint.attributes["file"]), int(endpoint.attributes.get("line") or 1)
        code = handler_source(repo, rev, file, line)
        try:
            value, _ = await brain.complete_json(
                LLMRequest(
                    purpose="world.endpoint_tables",
                    tier=Tier.LOCAL,
                    messages=[
                        Message(
                            role="user",
                            source="repo",
                            content=prompt.render(
                                tables=", ".join(tables),
                                schema=str(schema),
                                endpoint=endpoint.name,
                                file=file,
                                code=code,
                            ),
                        )
                    ],
                    response_schema=schema,
                    max_tokens=300,
                    prompt_sha256=prompt.sha256,
                )
            )
        except (BrainError, ProviderError):
            continue
        evidence = [EvidenceRef(kind="file", locator=f"{file}:{line}", note="read by the local model")]
        confidence = capped_confidence(0.9, EvidenceLevel.REASONABLE_SUSPICION)
        for predicate in ("reads", "writes"):
            for table in sorted(set(value[predicate])):
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
