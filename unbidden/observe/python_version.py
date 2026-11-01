"""Which Python reproduces a project: chosen from what the project declares, with the rule and the evidence recorded.

Sources, read from the repository (never the host's Python, never a silent default when the project says something):
- **constraints** (which versions it admits): PEP 621 `requires-python`; Poetry's `tool.poetry.dependencies.python`;
  `poetry.lock`'s `[metadata] python-versions`; Pipfile's `[requires] python_version`;
- **concrete versions** (where it actually runs): the CI's `python-version` values (its checks run there), the
  project's Dockerfile `FROM python:X.Y` (how it is deployed), `.python-version` and `runtime.txt` (a developer's
  pin).

Rule: the admissible versions are the supported minors (3.8-3.13: images and wheels exist) that every constraint
admits. The choice is the first concrete source, in that order of authority, with a version in that set; inside CI,
the version its Dockerfile also uses, else the oldest in its matrix (old pins have wheels for old interpreters).
With no concrete version, a range alone does not name one: the oldest admissible minor is taken and said to be a
choice. With nothing declared, the default is used and said so. A concrete version outside the constraints, or two
concrete sources that disagree, is recorded as a conflict.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from typing import Any

# 3.14 since stage 10: mealie requires it (>=3.14,<3.15), and the default could not match.
SUPPORTED = tuple(f"3.{m}" for m in range(8, 15))
DEFAULT = "3.12"


@dataclass(frozen=True)
class Choice:
    version: str
    rule: str
    evidence: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = field(default=())

    def notes(self) -> tuple[str, ...]:
        return (f"python {self.version}: {self.rule}", *self.evidence, *(f"conflict: {c}" for c in self.conflicts))


def _minor(text: str) -> str | None:
    found = re.match(r"\s*(3)\.(\d+)", str(text))
    return f"3.{found.group(2)}" if found else None


def admits(spec: str, version: str) -> bool:
    """PEP 440 and Poetry forms over minor versions: >=, >, <=, <, ==, !=, ~=, ^, ~, `*`, and `||` alternatives."""
    spec = str(spec).strip()
    if not spec or spec == "*":
        return True
    if "||" in spec:
        return any(admits(part, version) for part in spec.split("||"))
    minor = int(version.split(".")[1])
    for clause in re.split(r",|\s+(?=[<>=!~^])", spec):
        clause = clause.strip()
        found = re.match(r"(\^|~=|~|>=|<=|==|!=|>|<)?\s*3(?:\.(\d+|\*))?(?:\.(\d+))?", clause)
        if not found:
            continue
        op, raw = found.group(1) or "==", found.group(2)
        if raw in (None, "*"):
            continue  # "3" or "3.*": any Python 3
        bound, patch = int(raw), found.group(3)
        ok = {
            "^": minor >= bound,
            "~": minor == bound,
            "~=": minor >= bound if patch is None else minor == bound,
            ">=": minor >= bound,
            ">": minor > bound or (minor == bound and patch is not None),
            "<=": minor <= bound,
            "<": minor < bound or (minor == bound and patch is not None and int(patch) > 0),
            "==": minor == bound,
            "!=": minor != bound or patch is not None,
        }[op]
        if not ok:
            return False
    return True


def _ci_versions(text: str) -> list[str]:
    """`python-version` values in a CI file: `[3.9, "3.10"]`, `"3.11"`, or a block list."""
    found: list[str] = []
    for m in re.finditer(r"python-versions?:\s*(\[[^\]]*\]|['\"]?[\d.x]+['\"]?)", text):
        found += [v for v in (_minor(x) for x in re.findall(r"3\.\d+", m.group(1))) if v]
    for m in re.finditer(r"python-versions?:\s*\n((?:\s+-\s*['\"]?3\.\d+['\"]?\s*\n)+)", text):
        found += [v for v in (_minor(x) for x in re.findall(r"3\.\d+", m.group(1))) if v]
    return sorted(set(found), key=lambda v: int(v.split(".")[1]))


def choose(read: Any, files: set[str]) -> Choice:
    """`read(path)` returns a tracked file's text. Returns the version, the rule that chose it, and the evidence."""
    constraints: list[tuple[str, str]] = []
    evidence: list[str] = []
    if "pyproject.toml" in files:
        try:
            project = tomllib.loads(read("pyproject.toml"))
        except tomllib.TOMLDecodeError:
            project = {}
        if spec := project.get("project", {}).get("requires-python"):
            constraints.append(("pyproject requires-python", str(spec)))
        if spec := project.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python"):
            constraints.append(("pyproject tool.poetry python", str(spec)))
    if "poetry.lock" in files:
        found = re.search(r'^python-versions\s*=\s*"([^"]+)"', read("poetry.lock").split("[metadata]")[-1], re.M)
        if found:
            constraints.append(("poetry.lock metadata python-versions", found.group(1)))
    if "Pipfile" in files:
        found = re.search(r'python_version\s*=\s*"([\d.]+)"', read("Pipfile"))
        if found:
            constraints.append(("Pipfile python_version", f"=={found.group(1)}"))
    admissible = [v for v in SUPPORTED if all(admits(spec, v) for _, spec in constraints)]
    evidence += [f"{src}: {spec}" for src, spec in constraints]
    concrete: list[tuple[str, list[str]]] = []
    ci = sorted({v for f in files if re.match(r"\.github/workflows/[^/]+\.ya?ml$", f) for v in _ci_versions(read(f))},
                key=lambda v: int(v.split(".")[1]))  # fmt: skip
    if ci:
        concrete.append(("the CI's python-version", ci))
    froms = [m for f in files if re.match(r"(.*/)?Dockerfile[^/]*$", f)
             for m in re.findall(r"^FROM\s+python:(3\.\d+)", read(f), re.M)]  # fmt: skip
    docker = sorted({v for v in (_minor(m) for m in froms) if v}, key=lambda v: int(v.split(".")[1]))
    if docker:
        concrete.append(("the project's Dockerfile", docker))
    for name in (".python-version", "runtime.txt"):
        if name in files:
            pinned = _minor(re.sub(r"^python-", "", read(name).strip()))
            if pinned:
                concrete.append((name, [pinned]))
    evidence += [f"{src}: {', '.join(vs)}" for src, vs in concrete]
    conflicts = [
        f"{src} uses {v}, which {', '.join(s for s, spec in constraints if not admits(spec, v))} excludes"
        for src, vs in concrete for v in vs if v not in admissible and v in SUPPORTED
    ]  # fmt: skip
    distinct = {v for _, vs in concrete for v in vs}
    if len(concrete) > 1 and len(distinct) > 1:
        conflicts.append("concrete sources disagree: " + "; ".join(f"{s} {', '.join(vs)}" for s, vs in concrete))
    for src, versions in concrete:
        usable = [v for v in versions if v in admissible]
        if not usable:
            continue
        if src == "the CI's python-version" and docker and set(docker) & set(usable):
            pick = sorted(set(docker) & set(usable), key=lambda v: int(v.split(".")[1]))[0]
            return Choice(pick, "where the CI runs the checks and the project's Dockerfile both use it",
                          tuple(evidence), tuple(conflicts))  # fmt: skip
        rule = f"from {src}" + (" (the oldest in its matrix)" if len(usable) > 1 else "")
        return Choice(usable[0], rule, tuple(evidence), tuple(conflicts))
    if constraints and admissible:
        return Choice(admissible[0], "no concrete version declared; the oldest the constraints admit (a choice, "
                      "not something the project names)", tuple(evidence), tuple(conflicts))  # fmt: skip
    if constraints:
        return Choice(DEFAULT, "the constraints admit no supported version; the default is used and cannot match",
                      tuple(evidence), (*conflicts, "no supported version satisfies the constraints"))  # fmt: skip
    return Choice(DEFAULT, "the project declares no Python version; the default", tuple(evidence), tuple(conflicts))
