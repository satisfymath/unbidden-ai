"""What a request holds, decided from where each part came from and then from what the text itself shows.

Provenance first (callers know whether they read a file, a log or a database), then deterministic patterns on
the final text: secrets, credentials files, personal data, log lines. Patterns can only make a label stricter.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from unbidden.contracts.llm import ContentLabel, Message
from unbidden.guardian.scanner import scan, secret_hits

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOC_IPS = ("192.0.2.", "198.51.100.", "203.0.113.", "127.0.0.1", "0.0.0.0")  # documentation and loopback
_ENV_LINE = re.compile(r"^[A-Z][A-Z0-9_]{2,}=\S+$", re.MULTILINE)
_LOG_LINE = re.compile(
    r"^(?:\S+\s+)?(?:INFO|WARN|WARNING|ERROR|DEBUG)[: ]|\"[A-Z]+ /\S* HTTP/[\d.]+\" \d{3}", re.MULTILINE
)
_EXAMPLE_EMAIL = re.compile(r"@(?:example\.(?:com|org|net)|test|localhost)\b")

BY_SOURCE = {
    "prompt": ContentLabel.INSTRUCTIONS,
    "synthetic": ContentLabel.SYNTHETIC,
    "runtime": ContentLabel.PRODUCTION_DATA,
    "database": ContentLabel.PRODUCTION_DATA,
}


@dataclass(frozen=True)
class Classification:
    label: ContentLabel
    reasons: tuple[str, ...]


def _text_findings(text: str) -> list[tuple[ContentLabel, str]]:
    found: list[tuple[ContentLabel, str]] = []
    secrets = secret_hits(scan(text))
    if secrets:
        found.append((ContentLabel.SECRET, f"{len(secrets)} secret(s): {', '.join(sorted({h.kind for h in secrets}))}"))
    if len(_ENV_LINE.findall(text)) >= 3:
        found.append((ContentLabel.SECRET, "looks like an environment file (several KEY=value lines)"))
    emails = [e for e in _EMAIL.findall(text) if not _EXAMPLE_EMAIL.search(e)]
    if emails:
        found.append((ContentLabel.PRODUCTION_DATA, f"{len(emails)} email address(es)"))
    ips = [ip for ip in _IPV4.findall(text) if not ip.startswith(_DOC_IPS)]
    if ips:
        found.append((ContentLabel.PRODUCTION_DATA, f"{len(ips)} IP address(es)"))
    if len(_LOG_LINE.findall(text)) >= 3:
        found.append((ContentLabel.PRODUCTION_DATA, "contains log lines"))
    return found


def classify(messages: Iterable[Message], *, repo_public: bool) -> Classification:
    label = ContentLabel.INSTRUCTIONS
    reasons: list[str] = []
    for message in messages:
        if message.source is None:
            part, why = ContentLabel.PRIVATE_CODE, f"{message.role} message of undeclared origin"
        elif message.source == "repo":
            part = ContentLabel.PUBLIC_CODE if repo_public else ContentLabel.PRIVATE_CODE
            why = f"repository content ({'public' if repo_public else 'not confirmed public'})"
        else:
            part, why = BY_SOURCE[message.source], f"{message.source} content"
        findings = _text_findings(message.content)
        if message.source == "synthetic":
            # The bridge already replaced names; only secrets and personal data can still raise it.
            findings = [f for f in findings if f[0] is ContentLabel.SECRET or "email" in f[1] or "IP" in f[1]]
        for found, finding_why in [(part, why), *findings]:
            if found.rank > label.rank:
                label = found
            if found.rank >= ContentLabel.PRIVATE_CODE.rank:
                reasons.append(finding_why)
    return Classification(label, tuple(dict.fromkeys(reasons)))
