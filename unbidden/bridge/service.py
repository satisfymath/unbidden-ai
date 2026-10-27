"""The privacy bridge, end to end, producing a candidate for FixLab to measure like any other.

1. Glimmer (local) suggests neutral names for every private name in the affected files.
2. Code renames deterministically; the renamed task is judged by the egress gate against the real names.
3. Muse Spark (remote) solves the synthetic task.
4. Code reverses the names; FixLab measures the result offline against the real repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError, EgressBlocked
from unbidden.bridge.rename import RenameMap, build_map, declared_dependencies, private_names
from unbidden.contracts.finding import Finding
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.guardian.scanner import SensitiveTermIndex

MAX_BRIDGE_BYTES = 16_000

NAMES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "renames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"real": {"type": "string"}, "synthetic": {"type": "string"}},
                "required": ["real", "synthetic"],
                "additionalProperties": False,
            },
        },
        "task": {"type": "string", "minLength": 20, "maxLength": 600},
    },
    "required": ["renames", "task"],
    "additionalProperties": False,
}


@dataclass
class BridgeResult:
    files: dict[str, str] | None
    rename: RenameMap | None = None
    notes: list[str] = field(default_factory=list[str])
    preview: str | None = None  # the exact text that would leave, in a dry run


def _findings_text(findings: list[Finding], rename: RenameMap | None) -> str:
    lines = [f"- {f.path}:{f.line or '?'} {f.rule}: {f.message}" for f in findings[:30]]
    text = "\n".join(lines)
    if rename is None:
        return text
    return "\n".join(
        f"- {rename.path_to_synthetic(f.path)}:{f.line or '?'} {f.rule}: {rename.to_synthetic(f.message)}"
        for f in findings[:30]
    )


REVIEW_ROUNDS = 2
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"words": {"type": "array", "items": {"type": "string", "maxLength": 60}, "maxItems": 40}},
    "required": ["words"],
    "additionalProperties": False,
}


class PrivacyBridge:
    def __init__(self, brain: Brain, *, repo_name: str) -> None:
        self.brain = brain
        self.repo_name = repo_name

    async def _review(self, content: str, synthetic: set[str], correlation_id: str) -> set[str] | None:
        """Words the local model says still reveal the owner, that appear verbatim and are not synthetic names."""
        prompt = load_prompt("bridge_review")
        try:
            value, _ = await self.brain.complete_json(
                LLMRequest(
                    purpose="bridge.review",
                    tier=Tier.LOCAL,
                    response_schema=REVIEW_SCHEMA,
                    max_tokens=800,
                    prompt_sha256=prompt.sha256,
                    correlation_id=correlation_id,
                    messages=[
                        Message(
                            role="user",
                            source="synthetic",
                            content=prompt.render(schema=str(REVIEW_SCHEMA), text=content),
                        )
                    ],
                )
            )
        except (BrainError, ProviderError):
            return None
        words = {w.strip() for w in value["words"] if len(w.strip()) >= 3}
        return {w for w in words if re.search(rf"(?<![\w$]){re.escape(w)}(?![\w$])", content) and w not in synthetic}

    async def solve(
        self, base: Path, findings: list[Finding], *, correlation_id: str, dry_run: bool = False
    ) -> BridgeResult:
        """With `dry_run`, stop before anything is sent: the result carries the exact payload that would leave."""
        paths = sorted({f.path for f in findings})
        real_files = {p: (base / p).read_text(errors="replace") for p in paths}
        if sum(len(t) for t in real_files.values()) > MAX_BRIDGE_BYTES:
            return BridgeResult(None, notes=["too much code to rewrite safely as a synthetic task"])
        private = private_names(real_files, extra=(self.repo_name,), dependencies=declared_dependencies(base))
        identifiers = SensitiveTermIndex(private)

        # 1. Local: readable neutral names and a description of the problem.
        names_prompt = load_prompt("bridge_names")
        try:
            suggestion, _ = await self.brain.complete_json(
                LLMRequest(
                    purpose="bridge.names",
                    tier=Tier.LOCAL,
                    messages=[
                        Message(
                            role="user",
                            source="repo",
                            content=names_prompt.render(
                                schema=str(NAMES_SCHEMA),
                                names="\n".join(f"- {n}" for n in sorted(private)),
                                findings=_findings_text(findings, None),
                            ),
                        )
                    ],
                    response_schema=NAMES_SCHEMA,
                    max_tokens=1500,
                    prompt_sha256=names_prompt.sha256,
                    correlation_id=correlation_id,
                )
            )
        except (BrainError, ProviderError) as exc:
            return BridgeResult(None, notes=[f"local rewrite failed: {exc}"])

        # 2. Code: rename deterministically. The model's task text is renamed too, in case it slipped.
        suggested = {r["real"]: r["synthetic"] for r in suggestion["renames"]}
        comment = "#" if paths[0].endswith(".py") else "//"
        solve_prompt = load_prompt("bridge_solve")
        reviewed: list[str] = []
        rename = build_map(private, suggested, list(real_files.values()))
        content = ""
        for _round in range(REVIEW_ROUNDS + 1):
            rename = build_map(private, suggested, list(real_files.values()))
            synthetic_files = {rename.path_to_synthetic(p): rename.to_synthetic(t) for p, t in real_files.items()}
            content = solve_prompt.render(
                task=rename.to_synthetic(str(suggestion["task"])),
                findings=_findings_text(findings, rename),
                comment=comment,
                files="\n\n".join(f"{comment} file: {p}\n```\n{t}```" for p, t in sorted(synthetic_files.items())),
            )
            if _round == REVIEW_ROUNDS:
                break
            # 2b. Local review: what would still tell an outsider whose code this is? Those words are renamed too.
            flagged = await self._review(content, set(rename.forward.values()), correlation_id)
            if flagged is None:
                return BridgeResult(None, rename, ["the local review could not run; nothing was sent"])
            if not flagged:
                break
            reviewed.extend(sorted(flagged))
            private |= flagged
            identifiers = SensitiveTermIndex(private)

        if dry_run:
            return BridgeResult(
                None,
                rename,
                [
                    f"{len(rename.forward)} private names replaced",
                    *([f"review flagged: {', '.join(reviewed)}"] if reviewed else []),
                ],
                preview=content,
            )

        # 3. Remote: the gate judges this exact payload against every private name before it is sent.
        try:
            response = await self.brain.complete(
                LLMRequest(
                    purpose="bridge.solve",
                    expect_files=True,
                    tier=Tier.CODE,
                    messages=[Message(role="user", content=content, source="synthetic")],
                    max_tokens=4000,
                    prompt_sha256=solve_prompt.sha256,
                    correlation_id=correlation_id,
                ),
                identifiers=identifiers,
            )
        except EgressBlocked as exc:
            return BridgeResult(None, rename, [f"the egress gate blocked the synthetic task: {exc}"])
        except (BrainError, ProviderError) as exc:
            return BridgeResult(None, rename, [f"remote solve failed: {exc}"])

        # 4. Code: reverse the names and keep only the files that were shown.
        try:
            returned = parse_files(response.content)
        except CodeBlockError as exc:
            return BridgeResult(None, rename, [f"the remote answer had no usable files: {exc}"])
        real: dict[str, str] = {}
        for synthetic_path, text in returned.items():
            path = rename.path_to_real(synthetic_path)
            if path in real_files:
                real[path] = rename.to_real(text)
        if not real:
            return BridgeResult(None, rename, ["the remote answer changed none of the files it was shown"])
        notes = [f"{len(rename.forward)} private names were replaced before sending"]
        if reviewed:
            notes.append(
                f"the local review flagged {len(reviewed)} more word(s), replaced too: {', '.join(reviewed[:12])}"
            )
        return BridgeResult(real, rename, notes)
