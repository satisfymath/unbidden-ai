from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from unbidden.contracts.common import Contract

Severity = Literal["error", "warning", "info"]


class Completeness(StrEnum):
    """How much of a tool's output survived. Only a complete report can resolve a finding or be a lab side."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    TRUNCATED = "truncated"
    FAILED = "failed"
    UNKNOWN = "unknown"


def fingerprint(tool: str, rule: str, path: str, message: str) -> str:
    # Line numbers are left out on purpose: an unrelated edit above a finding must not make it look new.
    raw = "\x1f".join((tool, rule, path, message.strip()))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Finding(Contract):
    tool: str
    rule: str
    severity: Severity
    category: str = Field(max_length=40)
    path: str
    line: int | None = None
    message: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{16}$")
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        tool: str,
        rule: str,
        severity: Severity,
        category: str,
        path: str,
        message: str,
        line: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Finding:
        return cls(
            tool=tool,
            rule=rule,
            severity=severity,
            category=category,
            path=path,
            line=line,
            message=message,
            fingerprint=fingerprint(tool, rule, path, message),
            extra=extra or {},
        )


class AnalyzerReport(Contract):
    tool: str
    argv: list[str]
    exit_code: int | None
    findings: list[Finding] = Field(default_factory=list[Finding])
    completeness: Completeness
    dropped: int = 0
    error: str | None = None

    @property
    def can_resolve(self) -> bool:
        return self.completeness is Completeness.COMPLETE
