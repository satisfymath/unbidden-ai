"""Build a log adapter for a source Unbidden cannot read yet: tests first, then the adapter, then the oracle."""

from __future__ import annotations

import json
import random
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unbidden.brain.prompts import load_prompt
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.forge.adapter import LogAdapter, admit, oracle, parse_line
from unbidden.store import Store

COLLECTION = "capabilities"
SHOWN = 30
SEED = 11
_ACCESS = re.compile(r'"[A-Z]+ /\S* HTTP/[\d.]+"')

EXPECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tests": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "minimum": 1},
                    "method": {"type": "string"},
                    "path": {"type": "string"},
                    "status": {"type": "string", "pattern": "^[1-5][0-9][0-9]$"},
                },
                "required": ["line", "method", "path", "status"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tests"],
    "additionalProperties": False,
}
PATTERN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"pattern": {"type": "string", "maxLength": 300}},
    "required": ["pattern"],
    "additionalProperties": False,
}


@dataclass
class ForgeResult:
    adapter: LogAdapter | None
    notes: list[str] = field(default_factory=list[str])


def compose_logs(repo: Path, service: str, tail: int = 3000) -> list[str]:
    out = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(repo),
            "logs",
            "--no-log-prefix",
            "--tail",
            str(tail),
            service,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.splitlines()


def split(lines: list[str]) -> tuple[list[str], list[str]]:
    """Deduplicated by shape (so probes repeating one request do not flood both sides), then a seeded shuffle."""
    seen: dict[str, str] = {}
    for line in lines:
        shape = re.sub(r"\d+", "0", line)
        seen.setdefault(shape, line)
    unique = list(seen.values())
    random.Random(SEED).shuffle(unique)
    access = [ln for ln in unique if _ACCESS.search(ln)]
    other = [ln for ln in unique if not _ACCESS.search(ln)]
    shown = access[: SHOWN // 2] + other[: SHOWN // 2]
    heldout = access[SHOWN // 2 :] + other[SHOWN // 2 :]
    return shown, heldout


class Forge:
    def __init__(self, brain: Brain, store: Store, *, repairs: int = 2) -> None:
        self.brain, self.store, self.repairs = brain, store, repairs

    async def _json(self, purpose: str, prompt_name: str, schema: dict[str, Any], **values: str) -> Any:
        prompt = load_prompt(prompt_name)
        value, _ = await self.brain.complete_json(
            LLMRequest(
                purpose=purpose,
                tier=Tier.LOCAL,
                response_schema=schema,
                max_tokens=1500,
                messages=[Message(role="user", content=prompt.render(schema=json.dumps(schema), **values))],
                prompt_sha256=prompt.sha256,
            )
        )
        return value

    async def build_log_adapter(self, source: str, lines: list[str]) -> ForgeResult:
        result = ForgeResult(None)
        shown, heldout = split(lines)
        numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(shown, 1))
        try:
            expected = await self._json("forge.tests", "forge_expectations", EXPECT_SCHEMA, lines=numbered)
        except BrainError as exc:
            return ForgeResult(None, [f"no tests: {exc}"])
        tests = [t for t in expected["tests"] if 1 <= t["line"] <= len(shown)]
        tests = [t for t in tests if all(t[k] in shown[t["line"] - 1] for k in ("method", "path", "status"))]
        if len(tests) < 3:
            return ForgeResult(None, ["the expected values do not appear in their own lines; tests discarded"])
        tests_text = "\n".join(
            f"{shown[t['line'] - 1]} → method={t['method']} path={t['path']} status={t['status']}" for t in tests
        )
        feedback = ""
        for attempt in range(self.repairs + 1):
            try:
                proposed = await self._json(
                    "forge.adapter",
                    "forge_pattern",
                    PATTERN_SCHEMA,
                    feedback=feedback,
                    tests=tests_text,
                    lines="\n".join(shown),
                )
            except BrainError as exc:
                result.notes.append(f"attempt {attempt + 1}: {exc}")
                continue
            pattern = proposed["pattern"]
            problems = admit(pattern)
            if not problems:
                compiled = re.compile(pattern)
                for t in tests:
                    got = parse_line(compiled, shown[t["line"] - 1]) or {}
                    if any(got.get(k) != t[k] for k in ("method", "path", "status")):
                        problems.append(
                            f"line {t['line']}: expected {t['method']} {t['path']} {t['status']}, got {got}"
                        )
            if problems:
                feedback = "Your previous pattern was refused:\n- " + "\n- ".join(problems[:5]) + "\nFix it."
                result.notes.append(f"attempt {attempt + 1} refused: {problems[0]}")
                continue
            judged = oracle(pattern, heldout)
            version = 1 + len([a for a in self.store.list(COLLECTION, LogAdapter) if a.source == source])
            adapter = LogAdapter(
                source=source,
                version=version,
                pattern=pattern,
                status="validated" if judged.passed else "rejected",
                quality={
                    "heldout_access_lines": judged.access_lines,
                    "parsed": judged.parsed,
                    "coverage": round(judged.coverage, 3),
                    "us_per_line": round(judged.us_per_line, 1),
                    "problems": judged.problems,
                    "tests": len(tests),
                    "shown_lines": len(shown),
                },
                provenance={"model": "local", "attempts": attempt + 1},
            )
            self.store.put(COLLECTION, adapter)
            self.store.append_event(
                Event(
                    type=EventType.CAPABILITY_BUILT,
                    actor="forge",
                    entity_id=adapter.id,
                    payload={"source": source, "version": version, "status": adapter.status, **adapter.quality},
                )
            )
            result.adapter = adapter
            if judged.passed:
                return result
            feedback = "The pattern failed on lines you have not seen:\n- " + "\n- ".join(judged.problems) + "\nFix it."
            result.notes.append(f"attempt {attempt + 1}: oracle refused ({judged.problems[0]})")
        return result
