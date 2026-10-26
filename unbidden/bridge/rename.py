"""Deterministic, reversible renaming between real and synthetic names.

The model only suggests readable synthetic names; applying and reversing them is plain code, so what leaves
the machine and what comes back are both checked by something that cannot be talked into anything.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

_DEF = re.compile(
    r"""(?x)
    \b(?:def|class|function|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)
    | ^([A-Za-z_][\w]*)\s*(?::[^=\n]+)?=(?!=)              # module-level assignment
    | \bimport\s+([\w.]+) | \bfrom\s+([\w.]+)\s+import
    | from\s+["']([^"']+)["']                               # JS/TS module specifiers
    """,
    re.MULTILINE,
)
_TOKEN = re.compile(r"[A-Za-z_$][\w$]*")
# Names brought in by imports: `from x import a, b as c`, `import { a, b as c } from "x"`, `import a from "x"`.
_IMPORTED = re.compile(
    r"""(?x)
    \bfrom\s+[\w.]+\s+import\s+\((?P<paren>[^)]*)\)
    | \bfrom\s+[\w.]+\s+import\s+(?P<py>[^\n(]+)
    | \bimport\s*(?:type\s*)?\{(?P<js>[^}]*)\}
    | \bimport\s+(?:type\s+)?(?P<default>[A-Za-z_$][\w$]*)\s*(?:,|\s+from\b)
    """,
)

# Names that belong to languages and their standard libraries; renaming them would only hurt the answer.
COMMON = frozenset(
    {
        *keyword.kwlist, "self", "cls", "None", "True", "False", "print", "len", "range", "list", "dict", "set",
        "str", "int", "float", "bool", "bytes", "tuple", "object", "type", "super", "isinstance", "Exception",
        "ValueError", "TypeError", "KeyError", "decimal", "Decimal", "typing", "Optional", "Any", "dataclass",
        "dataclasses", "pathlib", "Path", "json", "re", "os", "sys", "math", "time", "datetime", "collections",
        "functools", "itertools", "logging", "asyncio", "abc", "enum", "annotations", "__future__",
        "const", "let", "var", "function", "return", "export", "default", "import", "from", "async", "await",
        "string", "number", "boolean", "undefined", "null", "void", "never", "unknown", "any", "Array", "Map",
        "Set", "Promise", "Record", "Partial", "console", "Math", "JSON", "Object", "Error", "Date", "this",
        "React", "props", "state", "value", "index", "item", "items", "result", "data", "args", "kwargs",
        "main", "test", "tests", "init", "__init__", "__name__", "__main__", "src", "lib", "utils",
    }
)  # fmt: skip


def private_names(files: dict[str, str], extra: tuple[str, ...] = ()) -> set[str]:
    """Names this code defines or imports locally, plus its path parts: what must not leave the machine."""
    names: set[str] = set(extra)
    for path, text in files.items():
        parts = PurePosixPath(path)
        names.update(p for p in parts.parent.parts if p not in (".", ""))
        names.add(parts.stem)
        for match in _DEF.finditer(text):
            for group in match.groups():
                if group:
                    names.update(seg for seg in re.split(r"[./@-]", group) if seg)
        for match in _IMPORTED.finditer(text):
            listed = match.group("paren") or match.group("py") or match.group("js") or match.group("default") or ""
            names.update(_TOKEN.findall(listed.replace(" as ", " ")))
    return {n for n in names if len(n) >= 3 and n not in COMMON and not n.isdigit()}


@dataclass(frozen=True)
class RenameMap:
    forward: dict[str, str]  # real -> synthetic

    @property
    def backward(self) -> dict[str, str]:
        return {v: k for k, v in self.forward.items()}

    @staticmethod
    def _apply(text: str, mapping: dict[str, str]) -> str:
        if not mapping:
            return text
        pattern = re.compile(
            r"(?<![\w$])(" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")(?![\w$])"
        )
        return pattern.sub(lambda m: mapping[m.group(1)], text)

    def to_synthetic(self, text: str) -> str:
        return self._apply(text, self.forward)

    def to_real(self, text: str) -> str:
        return self._apply(text, self.backward)

    def path_to_synthetic(self, path: str) -> str:
        return "/".join(self._apply(p, self.forward) if "." not in p else self._apply_stem(p, self.forward)
                        for p in path.split("/"))  # fmt: skip

    def path_to_real(self, path: str) -> str:
        return "/".join(self._apply(p, self.backward) if "." not in p else self._apply_stem(p, self.backward)
                        for p in path.split("/"))  # fmt: skip

    @classmethod
    def _apply_stem(cls, name: str, mapping: dict[str, str]) -> str:
        stem, dot, ext = name.partition(".")
        return cls._apply(stem, mapping) + dot + ext


def build_map(private: set[str], suggested: dict[str, str], texts: list[str]) -> RenameMap:
    """Take the model's suggestions where they are safe, and invent the rest.

    A synthetic name must be a plain identifier, must not be a private name itself, must not already occur in
    the code (or reversing would corrupt it), and must be unique.
    """
    existing = {t for text in texts for t in _TOKEN.findall(text)}
    used: set[str] = set()
    forward: dict[str, str] = {}
    counter = 0
    for real in sorted(private):
        candidate = suggested.get(real, "")
        ok = (
            bool(_TOKEN.fullmatch(candidate))
            and candidate not in private
            and candidate not in existing
            and candidate not in used
            and candidate.lower() != real.lower()
        )
        if not ok:
            while True:
                counter += 1
                candidate = f"{'Thing' if real[:1].isupper() else 'thing'}{counter}"
                if candidate not in existing and candidate not in used:
                    break
        used.add(candidate)
        forward[real] = candidate
    return RenameMap(forward)
