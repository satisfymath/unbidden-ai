"""Deterministic, reversible renaming between real and synthetic names.

The model only suggests readable synthetic names; applying and reversing them is plain code, so what leaves
the machine and what comes back are both checked by something that cannot be talked into anything.
"""

from __future__ import annotations

import builtins
import keyword
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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
        *keyword.kwlist,
        "self",
        "cls",
        "None",
        "True",
        "False",
        "print",
        "len",
        "range",
        "list",
        "dict",
        "set",
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "tuple",
        "object",
        "type",
        "super",
        "isinstance",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "decimal",
        "Decimal",
        "typing",
        "Optional",
        "Any",
        "dataclass",
        "dataclasses",
        "pathlib",
        "Path",
        "json",
        "re",
        "os",
        "sys",
        "math",
        "time",
        "datetime",
        "collections",
        "functools",
        "itertools",
        "logging",
        "asyncio",
        "abc",
        "enum",
        "annotations",
        "__future__",
        "const",
        "let",
        "var",
        "function",
        "return",
        "export",
        "default",
        "import",
        "from",
        "async",
        "await",
        "string",
        "number",
        "boolean",
        "undefined",
        "null",
        "void",
        "never",
        "unknown",
        "any",
        "Array",
        "Map",
        "Set",
        "Promise",
        "Record",
        "Partial",
        "console",
        "Math",
        "JSON",
        "Object",
        "Error",
        "Date",
        "this",
        "React",
        "props",
        "state",
        "value",
        "index",
        "item",
        "items",
        "result",
        "data",
        "args",
        "kwargs",
        "main",
        "test",
        "tests",
        "init",
        "__init__",
        "__name__",
        "__main__",
        "src",
        "lib",
        "utils",
    }
)


JS_WORDS = frozenset(
    {
        "abstract",
        "any",
        "as",
        "async",
        "await",
        "boolean",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "constructor",
        "continue",
        "debugger",
        "declare",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "from",
        "function",
        "get",
        "if",
        "implements",
        "import",
        "in",
        "instanceof",
        "interface",
        "is",
        "keyof",
        "let",
        "module",
        "namespace",
        "never",
        "new",
        "null",
        "number",
        "object",
        "of",
        "package",
        "private",
        "protected",
        "public",
        "readonly",
        "return",
        "set",
        "static",
        "string",
        "super",
        "switch",
        "symbol",
        "this",
        "throw",
        "true",
        "try",
        "type",
        "typeof",
        "undefined",
        "unknown",
        "var",
        "void",
        "while",
        "with",
        "yield",
        "Array",
        "Boolean",
        "Date",
        "Error",
        "JSON",
        "Map",
        "Math",
        "Number",
        "Object",
        "Promise",
        "Record",
        "Partial",
        "Required",
        "Readonly",
        "Pick",
        "Omit",
        "Set",
        "String",
        "console",
        "window",
        "document",
        "length",
        "push",
        "map",
        "filter",
        "reduce",
        "then",
        "toString",
        "valueOf",
    }
)
PY_WORDS = frozenset({*keyword.kwlist, *dir(builtins), "self", "cls", "__init__", "__name__", "__main__"})
_JS_IMPORT = re.compile(
    r"""import\s+(?:type\s+)?(?P<what>[^;]*?)\s+from\s+['"](?P<module>[^'"]+)['"]|import\s+['"](?P<bare>[^'"]+)['"]"""
)
_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+(?P<module>[\w.]+)\s+import\s+(?P<what>.+)|import\s+(?P<plain>[\w., ]+))$", re.MULTILINE
)
_LOCAL_SPECIFIER = re.compile(r"^(?:\.|@/|~/|#/|src/)")


def declared_dependencies(root: Path) -> set[str]:
    """Package names the project declares (package.json, pyproject.toml, requirements*.txt): what is published."""
    import json
    import tomllib

    names: set[str] = set()
    # Every manifest in the tree counts: a monorepo declares its packages' dependencies next to each package.
    for package in [p for p in root.rglob("package.json") if "node_modules" not in p.parts]:
        try:
            data = json.loads(package.read_text())
        except ValueError:
            continue
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            names.update(data.get(key, {}) or {})
    for pyproject in [p for p in root.rglob("pyproject.toml") if ".venv" not in p.parts]:
        try:
            data = tomllib.loads(pyproject.read_text())
        except tomllib.TOMLDecodeError:
            continue
        specs = list(data.get("project", {}).get("dependencies", []))
        for group in data.get("dependency-groups", {}).values():
            specs += [g for g in group if isinstance(g, str)]
        poetry = data.get("tool", {}).get("poetry", {})
        specs += list(poetry.get("dependencies", {})) + list(poetry.get("dev-dependencies", {}))
        names.update(re.split(r"[\s<>=!~;\[]", spec, maxsplit=1)[0] for spec in specs)
    for requirements in root.glob("requirements*.txt"):
        for line in requirements.read_text().splitlines():
            if line.strip() and not line.startswith(("#", "-")):
                names.add(re.split(r"[\s<>=!~;\[]", line.strip(), maxsplit=1)[0])
    # Import names differ from distribution names by case and dashes (PyYAML is yaml; scikit-learn is sklearn).
    return {n for n in names if n} | {n.lower().replace("-", "_") for n in names if n}


def _js_package(module: str) -> str:
    parts = module.split("/")
    return "/".join(parts[:2]) if module.startswith("@") else parts[0]


def public_names(files: dict[str, str], dependencies: set[str]) -> set[str]:
    """Names imported from published packages: a declared dependency, the Python standard library, or a Node
    builtin. Anything else, including an undeclared module, is the team's own code and stays private."""
    found: set[str] = set()
    for text in files.values():
        for match in _JS_IMPORT.finditer(text):
            module = match.group("module") or match.group("bare") or ""
            published = module.startswith("node:") or (
                not _LOCAL_SPECIFIER.match(module) and _js_package(module) in dependencies
            )
            if published:
                found.update(_TOKEN.findall(match.group("what") or ""))
                found.update(seg for seg in re.split(r"[/@.:-]", module) if seg)
        for match in _PY_IMPORT.finditer(text):
            module = match.group("module") or (match.group("plain") or "").split(",")[0].strip()
            root = module.split(".")[0]
            if module and not module.startswith(".") and (root in sys.stdlib_module_names or root in dependencies):
                found.update(_TOKEN.findall(match.group("what") or match.group("plain") or ""))
                found.update(module.split("."))
    return found - {"as", "type", "import", "from"}


def private_names(files: dict[str, str], extra: tuple[str, ...] = (), dependencies: set[str] | None = None) -> set[str]:
    """Every word of the code that is not the language's or a published package's: definitions, imports of
    local modules, object properties, words in strings and comments, path parts. A property such as
    `memberTier` that comes from the team's own API types reveals the domain as much as a function name does."""
    public = public_names(files, dependencies or set()) | JS_WORDS | PY_WORDS | COMMON
    names: set[str] = set(extra)
    for path, text in files.items():
        parts = PurePosixPath(path)
        names.update(p for p in parts.parent.parts if p not in (".", ""))
        names.add(parts.stem)
        names.update(_TOKEN.findall(text))
    return {n for n in names if len(n) >= 3 and n not in public and not n.isdigit() and not n.startswith("__")}


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
        return "/".join(
            self._apply(p, self.forward) if "." not in p else self._apply_stem(p, self.forward) for p in path.split("/")
        )

    def path_to_real(self, path: str) -> str:
        return "/".join(
            self._apply(p, self.backward) if "." not in p else self._apply_stem(p, self.backward)
            for p in path.split("/")
        )

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
