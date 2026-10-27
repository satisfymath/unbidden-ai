"""What of the code a fix request shows the model, chosen by relevance and measured against the egress cap.

Whole files are sent when they fit. When they do not, each finding gets an excerpt: its enclosing function or class
member (from the AST for Python), else a window of lines around it; overlapping excerpts are merged and each file's
import header is added once. Selection is deterministic: the same findings at the same commit give the same bytes.

Every finding must be shown. When they cannot all fit, nothing is sent: a partial task would yield a candidate that
cannot pass the lab, and the reason is reported instead. The cap itself (Guardian's) is never changed here.

The model answers an excerpt with a block headed `# file: <path>:<start>-<end>` holding the new text for exactly those
lines; `splice` puts it back and refuses a block for lines it was not shown.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

WINDOW = 12  # lines on each side of a finding when no enclosing definition is known
MAX_DEF_LINES = 120  # an enclosing definition longer than this is cut to a window around the finding
MAX_HEADER_LINES = 40


@dataclass(frozen=True)
class Excerpt:
    path: str
    start: int  # 1-based, inclusive
    end: int
    text: str

    @property
    def key(self) -> str:
        return f"{self.path}:{self.start}-{self.end}"


@dataclass(frozen=True)
class Selection:
    mode: str  # "files" | "excerpts" | "does_not_fit"
    files: dict[str, str]  # whole files, mode "files"
    excerpts: list[Excerpt]  # mode "excerpts"
    bytes: int  # what the code costs inside the payload, JSON-escaped
    reason: str


def payload_bytes(text: str) -> int:
    """Bytes a text takes inside the JSON payload the egress gate measures."""
    return len(json.dumps(text, ensure_ascii=False).encode()) - 2


def _enclosing(tree: ast.AST | None, line: int) -> tuple[int, int] | None:
    """The innermost function, or method of a class, holding `line`."""
    best: tuple[int, int] | None = None
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            end = node.end_lineno or node.lineno
            if start <= line <= end and (best is None or end - start < best[1] - best[0]):
                best = (start, end)
    return best


def _header_end(lines: list[str], tree: ast.AST | None) -> int:
    """Last line of the import block at the top of a module (0 when there is none)."""
    if isinstance(tree, ast.Module):
        last = 0
        for node in tree.body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                last = node.end_lineno or node.lineno
            elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)) and last:
                break
        return min(last, MAX_HEADER_LINES)
    imports = [i for i, ln in enumerate(lines[:MAX_HEADER_LINES], 1) if re.match(r"\s*(import|export .* from)\b", ln)]
    return imports[-1] if imports else 0


def _windows(path: str, text: str, lines_of_findings: list[int]) -> list[tuple[int, int, int]]:
    """(start, end, findings inside) per merged excerpt of one file, plus its import header."""
    lines = text.splitlines()
    tree: ast.AST | None = None
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
    spans: list[tuple[int, int]] = []
    for line in sorted(set(lines_of_findings)):
        line = max(1, min(line, len(lines) or 1))
        enclosing = _enclosing(tree, line)
        if enclosing is not None and enclosing[1] - enclosing[0] < MAX_DEF_LINES:
            spans.append(enclosing)
        else:
            spans.append((max(1, line - WINDOW), min(len(lines), line + WINDOW)))
    header = _header_end(lines, tree)
    if header:
        spans.append((1, header))
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e, sum(s <= ln <= e for ln in lines_of_findings)) for s, e in merged]


def select(base: Path, findings: Sequence[tuple[str, int | None]], budget: int) -> Selection:
    """Choose what of `base` to show for `findings` ((path, line) pairs) within `budget` payload bytes."""
    paths = sorted({p for p, _ in findings})
    texts = {p: (base / p).read_text(errors="replace") for p in paths}
    whole = sum(payload_bytes(t) for t in texts.values())
    if whole <= budget:
        return Selection("files", texts, [], whole, f"whole files fit ({whole} of {budget} bytes)")
    if any(line is None for _, line in findings):
        return Selection("does_not_fit", {}, [], whole, f"files are {whole} bytes, over {budget}, and a finding has "
                         "no line to excerpt around")  # fmt: skip
    excerpts: list[Excerpt] = []
    for path in paths:
        lines = texts[path].splitlines()
        wanted = [ln for p, ln in findings if p == path and ln is not None]
        for start, end, _ in _windows(path, texts[path], wanted):
            excerpts.append(Excerpt(path, start, end, "\n".join(lines[start - 1 : end]) + "\n"))
    used = sum(payload_bytes(e.text) + len(e.key) + 16 for e in excerpts)
    if used > budget:
        return Selection("does_not_fit", {}, [], used, f"excerpts around every finding need {used} bytes, over the "
                         f"{budget} the egress cap leaves; nothing partial is sent")  # fmt: skip
    return Selection("excerpts", {}, excerpts, used, f"files are {whole} bytes; {len(excerpts)} excerpts, {used} bytes")


def render(selection: Selection, comment: str) -> str:
    if selection.mode == "files":
        return "\n\n".join(f"`{p}`:\n```\n{t}```" for p, t in selection.files.items())
    return "\n\n".join(f"Lines {e.start}-{e.end} of `{e.path}`:\n```\n{comment} file: {e.key}\n{e.text}```"
                       for e in selection.excerpts)  # fmt: skip


class SpliceError(ValueError):
    pass


def splice(base: Path, excerpts: list[Excerpt], answer: dict[str, str]) -> dict[str, str]:
    """New whole files from replacement blocks keyed `path:start-end`. Only excerpts that were shown may change."""
    shown = {e.key: e for e in excerpts}
    unknown = sorted(set(answer) - set(shown))
    if unknown:
        raise SpliceError(f"blocks for lines that were not shown: {', '.join(unknown)}")
    files: dict[str, str] = {}
    for path in sorted({shown[k].path for k in answer}):
        lines = (base / path).read_text(errors="replace").splitlines()
        # From the bottom up, so earlier line numbers stay valid.
        for key in sorted((k for k in answer if shown[k].path == path), key=lambda k: -shown[k].start):
            e = shown[key]
            lines[e.start - 1 : e.end] = answer[key].rstrip("\n").split("\n")
        files[path] = "\n".join(lines) + "\n"
    return files
