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
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError, parse_json
from unbidden.bridge.rename import RenameMap, build_map
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.llm import LLMRequest, Message, Source, Tier
from unbidden.forge.adapter import ORACLE_VERSION, LogAdapter, admit, oracle, parse_line
from unbidden.guardian.scanner import SensitiveTermIndex
from unbidden.store import Store
from unbidden.world.runtime import compose_project

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


@dataclass
class ForgeResult:
    adapter: LogAdapter | None
    notes: list[str] = field(default_factory=list[str])


def compose_logs(repo: Path, service: str, tail: int = 3000) -> list[str]:
    out = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            compose_project(repo),
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
    """Exact duplicates removed, then a seeded shuffle: the model sees some lines, the oracle judges the rest."""
    unique = list(dict.fromkeys(ln for ln in lines if ln.strip()))
    random.Random(SEED).shuffle(unique)
    access = [ln for ln in unique if _ACCESS.search(ln)]
    other = [ln for ln in unique if not _ACCESS.search(ln)]
    shown = access[: SHOWN // 2] + other[: SHOWN // 2]
    heldout = access[SHOWN // 2 :] + other[SHOWN // 2 :]
    return shown, heldout


class Forge:
    def __init__(self, brain: Brain, store: Store, *, repairs: int = 4, remote: bool = False) -> None:
        self.brain, self.store, self.repairs, self.remote = brain, store, repairs, remote

    async def _json(
        self,
        purpose: str,
        prompt_name: str,
        schema: dict[str, Any],
        *,
        source: Source = "runtime",
        identifiers: SensitiveTermIndex | None = None,
        **values: str,
    ) -> Any:
        prompt = load_prompt(prompt_name)
        request = LLMRequest(
            purpose=purpose,
            tier=Tier.LOCAL,
            response_schema=schema,
            max_tokens=3000,
            prompt_sha256=prompt.sha256,
            messages=[Message(role="user", content=prompt.render(schema=json.dumps(schema), **values), source=source)],
        )
        response = await self.brain.complete(request, identifiers=identifiers)
        return parse_json(response.content)

    async def _pattern(
        self, purpose: str, *, source: Source, identifiers: SensitiveTermIndex | None, **values: str
    ) -> str:
        """The pattern comes back as raw text (D-005): inside JSON the local model lost its backslashes."""
        prompt = load_prompt("forge_pattern")
        request = LLMRequest(
            purpose=purpose,
            tier=Tier.LOCAL,
            max_tokens=3000,
            prompt_sha256=prompt.sha256,
            messages=[Message(role="user", content=prompt.render(**values), source=source)],
        )
        response = await self.brain.complete(request, identifiers=identifiers)
        found = re.search(r"^\s*PATTERN:[ \t]*(.+?)\s*$", response.content, re.MULTILINE)
        if found is None:
            raise ValueError("no `PATTERN:` line in the answer")
        return found.group(1)

    async def build_log_adapter(self, source: str, lines: list[str]) -> ForgeResult:
        result = ForgeResult(None)
        shown, heldout = split(lines)
        numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(shown, 1))
        try:
            expected = await self._json("forge.tests", "forge_expectations", EXPECT_SCHEMA, lines=numbered)
        except (BrainError, ProviderError) as exc:
            return ForgeResult(None, [f"no tests: {exc}"])
        tests = [t for t in expected["tests"] if 1 <= t["line"] <= len(shown)]
        tests = [t for t in tests if all(t[k] in shown[t["line"] - 1] for k in ("method", "path", "status"))]
        if len(tests) < 3:
            return ForgeResult(None, ["the expected values do not appear in their own lines; tests discarded"])
        if await self._attempts(source, shown, tests, heldout, result, origin="local", transform=None):
            return result
        if self.remote:
            # The local model could not: ask Muse Spark through the privacy bridge. Paths are renamed and addresses
            # masked before anything leaves; the adapter that comes back is structure, judged on the real lines.
            transform = log_transform(shown)
            result.notes.append(f"bridge: {len(transform.rename.forward)} private names and the addresses replaced")
            await self._attempts(source, shown, tests, heldout, result, origin="bridge", transform=transform)
        return result

    async def _attempts(
        self,
        source: str,
        shown: list[str],
        tests: list[dict[str, Any]],
        heldout: list[str],
        result: ForgeResult,
        *,
        origin: str,
        transform: LogTransform | None,
    ) -> bool:
        view = transform.apply if transform else (lambda text: text)
        tests_text = "\n".join(
            view(f"{shown[t['line'] - 1]} → method={t['method']} path={t['path']} status={t['status']}") for t in tests
        )
        # Real log lines are production data and stay local; the bridge's renamed view may leave.
        msg_source: Source = "runtime" if transform is None else "synthetic"
        identifiers = transform.identifiers if transform else None
        feedback = ""
        tries = self.repairs + 1 if transform is None else 3
        for attempt in range(tries):
            try:
                pattern = await self._pattern(
                    "forge.adapter" if transform is None else "forge.adapter.bridge",
                    source=msg_source,
                    identifiers=identifiers,
                    feedback=feedback,
                    tests=tests_text,
                    lines="\n".join(view(ln) for ln in shown),
                )
            except (BrainError, ProviderError, ValueError) as exc:
                result.notes.append(f"{origin} attempt {attempt + 1}: {exc}")
                if transform is not None:
                    return False
                continue
            problems = admit(pattern)
            if not problems:
                compiled = re.compile(pattern)
                for t in tests:  # always judged on the real lines and the real expected values
                    got = parse_line(compiled, shown[t["line"] - 1]) or {}
                    if any(got.get(k) != t[k] for k in ("method", "path", "status")):
                        problems.append(
                            view(f"line {t['line']}: expected {t['method']} {t['path']} {t['status']}, got {got}")
                        )
            if problems:
                feedback = (
                    f"Your previous pattern was `{pattern}`. It was refused:\n- "
                    + "\n- ".join(problems[:5])
                    + "\nWrite a corrected pattern."
                )
                result.notes.append(f"{origin} attempt {attempt + 1} refused: {problems[0]}")
                continue
            judged = oracle(pattern, heldout)
            version = 1 + len([a for a in self.store.list(COLLECTION, LogAdapter) if a.source == source])
            adapter = LogAdapter(
                source=source,
                version=version,
                pattern=pattern,
                status="validated" if judged.passed else "rejected",
                quality={
                    "oracle": ORACLE_VERSION,
                    "heldout_access_lines": judged.access_lines,
                    "parsed": judged.parsed,
                    "coverage": round(judged.coverage, 3),
                    "us_per_line": round(judged.us_per_line, 1),
                    "problems": judged.problems,
                    "tests": len(tests),
                    "shown_lines": len(shown),
                },
                provenance={"model": origin, "attempts": attempt + 1},
            )
            self.store.put(COLLECTION, adapter)
            self.store.append_event(
                Event(
                    type=EventType.CAPABILITY_BUILT,
                    actor="forge",
                    entity_id=adapter.id,
                    payload={
                        "source": source,
                        "version": version,
                        "status": adapter.status,
                        "origin": origin,
                        **adapter.quality,
                    },
                )
            )
            result.adapter = adapter
            if judged.passed:
                return True
            feedback = (
                f"Your previous pattern was `{pattern}`. On lines you have not seen it failed:\n- "
                + "\n- ".join(judged.problems)
                + "\nWrite a corrected pattern."
            )
            result.notes.append(f"{origin} attempt {attempt + 1}: oracle refused ({judged.problems[0]})")
        return False


_PATH = re.compile(r'"[A-Z]+ (/[^ "?]*)')
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


@dataclass
class LogTransform:
    """What a remote model may see of a log: request paths renamed, addresses replaced by documentation ones."""

    rename: RenameMap
    identifiers: SensitiveTermIndex

    def apply(self, text: str) -> str:
        # Every occurrence of a private name is replaced, not only inside request lines: tests and feedback quote
        # paths too (the egress gate caught exactly that on the first real run).
        return self.rename.to_synthetic(_IPV4.sub("192.0.2.1", text))


def log_transform(lines: list[str]) -> LogTransform:
    segments = {seg for ln in lines for path in _PATH.findall(ln) for seg in path.split("/") if seg}
    private = {s for s in segments if len(s) >= 3 and not s.isdigit()}
    return LogTransform(build_map(private, {}, lines), SensitiveTermIndex(private))
