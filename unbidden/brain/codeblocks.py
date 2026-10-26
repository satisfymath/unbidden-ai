"""Code comes back as fenced blocks headed by `# file: <path>`, never inside JSON.

Asking for a whole file inside a JSON string made answers slow and mostly invalid; fenced blocks are what
models write well.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_HEADER = re.compile(r"^(?:#|//)\s*file:\s*(?P<path>\S+)\s*$", re.MULTILINE)
_FENCE = re.compile(r"^```[\w+-]*\s*$")


class CodeBlockError(ValueError):
    pass


def _safe_path(raw: str) -> str:
    path = PurePosixPath(raw.strip("`'\""))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise CodeBlockError(f"unsafe path {raw!r}")
    return str(path)


def _strip_fences(body: str) -> str:
    lines = body.strip("\n").splitlines()
    while lines and _FENCE.match(lines[0]):
        lines.pop(0)
    while lines and (_FENCE.match(lines[-1]) or not lines[-1].strip()):
        lines.pop()
    return "\n".join(lines)


def parse_files(text: str) -> dict[str, str]:
    """Split an answer into {path: content}. Each file ends with exactly one newline."""
    headers = list(_HEADER.finditer(text))
    if not headers:
        raise CodeBlockError("no '# file: <path>' header found")
    files: dict[str, str] = {}
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        chunk = text[header.end() : end]
        # The header may sit inside the fence or just above it; fences at either end are dropped.
        content = _strip_fences(chunk)
        if not content.strip():
            raise CodeBlockError(f"{header.group('path')} is empty")
        files[_safe_path(header.group("path"))] = content.rstrip("\n") + "\n"
    return files
