"""Lexical secret and identifier scanner, run on every prompt, outbound payload and stored record."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+([A-Za-z0-9._~+/-]{20,}=*)")),
    ("url_credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]{3,})@")),
    # name=value assignments whose name says it holds a credential, in env, yaml, inline or quoted form.
    (
        "credential_assignment",
        re.compile(
            r"""(?ix)
            \b[\w.-]*(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key)[\w.-]*
            ["']?\s*[:=]\s*
            ["']?(?P<value>[^\s"',;}{()\[\]]{6,})
            """
        ),
    ),
)

# Values that look like assignments but are not secrets: references, placeholders and type names.
_PLACEHOLDER = re.compile(
    r"""(?ix)^(
        \$\{?[\w.-]+\}?            # ${VAR} or $VAR
        |<[^>]*>                   # <your-token>
        |\{\{.*\}\}                # {{ template }}
        |true|false|null|none|undefined
        |str|string|int|bytes|optional\[.*
        |(?:bool|int|float|str|bytes|dict|list|tuple|optional|union)(?:\[[^=]*\])?=.*   # annotation with a default
        |(?:x+|\*+|\.{3,}|changeme|placeholder|redacted|example|dummy|your[_-].*|xxx.*)
        |os\.environ.*|process\.env.*|getenv.*|settings\..*|config\..*|env\..*
    )$""",
)


@dataclass(frozen=True, slots=True)
class Hit:
    kind: str
    start: int
    end: int

    def label(self) -> str:
        return self.kind


class SensitiveTermIndex:
    """Real identifiers of the observed environment (tables, routes, hostnames, people) that may not leave."""

    def __init__(self, terms: Iterable[str] = ()) -> None:
        self._terms: set[str] = set()
        self._regex: re.Pattern[str] | None = None
        self.add(terms)

    def add(self, terms: Iterable[str]) -> None:
        # Very short or generic words would block every payload; identifiers shorter than 4 chars are ignored.
        self._terms.update(t for t in terms if len(t) >= 4)
        if self._terms:
            alternatives = "|".join(re.escape(t) for t in sorted(self._terms, key=len, reverse=True))
            self._regex = re.compile(rf"(?<![\w]){'(?:' + alternatives + ')'}(?![\w])", re.IGNORECASE)

    def __len__(self) -> int:
        return len(self._terms)

    @property
    def terms(self) -> frozenset[str]:
        return frozenset(self._terms)

    def find(self, text: str) -> list[Hit]:
        if self._regex is None:
            return []
        return [Hit(f"identifier:{m.group(0).lower()}", m.start(), m.end()) for m in self._regex.finditer(text)]


_CODE_NAME = re.compile(r"^[a-z_][a-z_]*$")
_CODE_PATH = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+$")  # reservation.reservation_token
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_MASKED = re.compile(r"^.{0,2}\*{3}$")  # what `_mask` leaves


def _is_code_reference(match: re.Match[str]) -> bool:
    """`password = new_password`, `token = r.json()`, `key = response["k"]`, `token=run.token`: code, not a credential.

    Only unquoted values qualify: a quoted literal is always judged as a possible secret.
    """
    text, start, end = match.string, match.start("value"), match.end("value")
    if start > 0 and text[start - 1] in "'\"":
        return False
    if end < len(text) and text[end] in "([.":
        return True
    value = match.group("value")
    if _CODE_NAME.match(value) or _CODE_PATH.match(value):
        return True
    # `ORMCsrfToken = CsrfToken`: a name assigned to a name it ends with is an alias, not a value (stage 10, Prefect).
    name = text[match.start() : start].rstrip("\"' :=")
    return bool(_IDENTIFIER.match(value)) and len(value) >= 4 and name.endswith(value)


def _secret_span(kind: str, match: re.Match[str]) -> tuple[int, int] | None:
    if kind == "credential_assignment":
        value = match.group("value")
        if _PLACEHOLDER.match(value) or _MASKED.match(value) or _is_code_reference(match):
            return None
        return match.start("value"), match.end("value")
    if kind == "url_credentials" and (_PLACEHOLDER.match(match.group(1)) or _MASKED.match(match.group(1))):
        # `${PASSWORD}` is a reference; `ab***` is what masking left (stage 10: the mask of a URL password matched
        # the URL pattern again, and the scan of the masked prompt refused the whole request).
        return None
    if match.re.groups:
        return match.start(1), match.end(1)
    return match.start(), match.end()


def scan(text: str, identifiers: SensitiveTermIndex | None = None) -> list[Hit]:
    hits: list[Hit] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            span = _secret_span(kind, match)
            if span is not None:
                hits.append(Hit(kind, *span))
    if identifiers is not None:
        hits.extend(identifiers.find(text))
    return sorted(hits, key=lambda h: (h.start, -h.end))


def scan_many(texts: Iterable[str], identifiers: SensitiveTermIndex | None = None) -> list[Hit]:
    return [hit for text in texts for hit in scan(text, identifiers)]


def secret_hits(hits: Sequence[Hit]) -> list[Hit]:
    return [h for h in hits if not h.kind.startswith("identifier:")]


def _mask(value: str) -> str:
    # Five characters at most: shorter than any pattern's shortest secret, so a masked value is never flagged again
    # (a three-character prefix made `password="pas***"` a six-character value the scan still flagged).
    return value[:2] + "***" if len(value) > 6 else "***"


def redact_text(text: str) -> str:
    """Mask every secret, keeping a two-character prefix so a person can tell which value it was.

    Idempotent: a masked value no longer matches any pattern.
    """
    hits = secret_hits(scan(text))
    if not hits:
        return text
    out: list[str] = []
    cursor = 0
    for hit in hits:
        if hit.start < cursor:
            continue
        out.append(text[cursor : hit.start])
        out.append(_mask(text[hit.start : hit.end]))
        cursor = hit.end
    out.append(text[cursor:])
    return "".join(out)


def redact_json(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): redact_json(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if isinstance(value, list | tuple):
        return [redact_json(v) for v in value]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return value
