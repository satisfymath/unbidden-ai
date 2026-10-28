"""The development scenarios of evaluation v2: each one a small project in its own git repository, and an oracle
kept outside it.

    uv run python -m bench.eval2.scenarios <out dir>

Writes `<out>/repos/<id>/` (what the agent sees: code, the project's tests, its CI declaration, neutral history) and
`<out>/oracle/<id>.json` plus `<out>/oracle/<id>_hidden.py` (what only the scorer reads). Nothing in a repository
names what was planted. Deterministic: the same commit of this file writes the same scenarios.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PYPROJECT = """[project]
name = "pantry"
version = "0.3.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100
extend-exclude = ["vendor"]

[tool.ruff.lint]
select = ["E", "F"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
"""
REQUIREMENTS = "pytest==8.3.3\n"
CI = """name: ci
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt ruff
      - run: ruff check src tests
      - run: pytest
"""
INVENTORY = '''"""Stock kept per item, in units."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Inventory:
    stock: dict[str, int] = field(default_factory=dict)

    def add(self, item: str, units: int) -> int:
        if units <= 0:
            raise ValueError("units must be positive")
        self.stock[item] = self.stock.get(item, 0) + units
        return self.stock[item]

    def take(self, item: str, units: int) -> int:
        have = self.stock.get(item, 0)
        if units > have:
            raise ValueError(f"only {have} of {item}")
        self.stock[item] = have - units
        return self.stock[item]

    def low(self, threshold: int) -> list[str]:
        return sorted(i for i, n in self.stock.items() if n < threshold)
'''
FORMAT = '''"""How quantities are shown."""

from __future__ import annotations


def units(n: int) -> str:
    return f"{n} unit" if n == 1 else f"{n} units"
'''
HANDLERS = '''"""Requests against the pantry, by kind."""

from __future__ import annotations

from pantry import format
from pantry.inventory import Inventory


def handle(store: Inventory, kind: str, item: str, n: int = 0) -> str:
    if kind == "add":
        return format.units(store.add(item, n))
    if kind == "take":
        return format.units(store.take(item, n))
    if kind == "low":
        return ", ".join(store.low(n)) or "nothing"
    raise ValueError(f"unknown request {kind!r}")
'''
TESTS = """from pantry.handlers import handle
from pantry.inventory import Inventory
import pytest


class TestInventory:
    def test_add_and_take(self):
        store = Inventory()
        store.add("rice", 3)
        assert store.take("rice", 2) == 1

    def test_cannot_take_more_than_there_is(self):
        with pytest.raises(ValueError):
            Inventory().take("rice", 1)


class TestHandlers:
    def test_low(self):
        store = Inventory()
        store.add("salt", 1)
        assert handle(store, "low", "", 5) == "salt"
"""


@dataclass(frozen=True)
class Scenario:
    id: str
    kind: str
    files: dict[str, str]  # the update commit, over the base
    oracle: dict[str, Any]
    hidden: str = ""  # a pytest file only the scorer runs
    removed: tuple[str, ...] = field(default_factory=tuple)


BASE = {
    "pyproject.toml": PYPROJECT,
    "requirements.txt": REQUIREMENTS,
    ".github/workflows/ci.yml": CI,
    "src/pantry/__init__.py": "",
    "src/pantry/inventory.py": INVENTORY,
    "src/pantry/format.py": FORMAT,
    "src/pantry/handlers.py": HANDLERS,
    "tests/test_pantry.py": TESTS,
}

SHADOWED = HANDLERS.replace(
    """    if kind == "low":
        return ", ".join(store.low(n)) or "nothing"
""",
    """    if kind == "low":
        return ", ".join(store.low(n)) or "nothing"
    if kind == "report":
        from pantry import format

        return "; ".join(f"{i}: {format.units(c)}" for i, c in sorted(store.stock.items()))
""",
)
DUPLICATE = (
    TESTS
    + """

class TestInventory:
    def test_low_lists_items_under_the_threshold(self):
        store = Inventory()
        store.add("oil", 1)
        assert store.low(2) == ["oil"]
"""
)
VENDORED = """# Copied from an upstream helper library, kept as it was.
import os, sys
def slugify(text,sep = "-"):
    l = text.lower()
    return sep.join(w for w in l.split() if w)
"""
SCRIPT = """import json,sys
def main():
    data=json.load(open(sys.argv[1]))
    print( len(data) )
main()
"""


def scenarios() -> list[Scenario]:
    line = SHADOWED.splitlines().index('    if kind == "add":') + 1
    return [
        Scenario(
            "crash-shadowed-import",
            "planted_defect",
            {"src/pantry/handlers.py": SHADOWED},
            {
                "truth": [
                    {"path": "src/pantry/handlers.py", "line": line, "what": "UnboundLocalError on every request"}
                ],
                "acceptable": ["run_experiment"],
                "promotion_valid": True,
            },
            hidden="""from pantry.handlers import handle
from pantry.inventory import Inventory


def test_add_still_works():
    assert handle(Inventory(), "add", "rice", 2) == "2 units"


def test_report():
    store = Inventory()
    store.add("rice", 2)
    assert handle(store, "report", "") == "rice: 2 units"
""",
        ),
        Scenario(
            "hidden-duplicate-test",
            "planted_defect",
            {"tests/test_pantry.py": DUPLICATE},
            {
                "truth": [
                    {
                        "path": "tests/test_pantry.py",
                        "line": DUPLICATE.splitlines().index("class TestInventory:", 10) + 1,
                        "what": "the first TestInventory never runs",
                    }
                ],
                "acceptable": ["run_experiment"],
                "promotion_valid": True,
                "min_collected": 4,
            },
        ),
        Scenario("healthy", "healthy", {}, {"truth": [], "acceptable": ["wait", "decline"]}),
        Scenario(
            "vendored-noise",
            "environment",
            {"vendor/slug.py": VENDORED},
            {"truth": [], "acceptable": ["wait", "decline"], "note": "the project excludes vendor/ from its linting"},
        ),
        Scenario(
            "low-value-style",
            "low_value",
            {"scripts/count.py": SCRIPT},
            {"truth": [], "acceptable": ["decline", "wait"], "note": "style in a directory the CI never checks"},
        ),
    ]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=dev", "-c", "user.email=dev@example.com", *args],
        check=True,
        capture_output=True,
    )


def write(out: Path) -> list[str]:
    (out / "repos").mkdir(parents=True, exist_ok=True)
    (out / "oracle").mkdir(parents=True, exist_ok=True)
    written = []
    for s in scenarios():
        repo = out / "repos" / s.id
        if repo.exists():
            raise SystemExit(f"{repo} exists; scenarios are written once, into an empty directory")
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        for path, text in BASE.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "initial import")
        if s.files:
            for path, text in s.files.items():
                (repo / path).parent.mkdir(parents=True, exist_ok=True)
                (repo / path).write_text(text)
            _git(repo, "add", ".")
            _git(repo, "commit", "-qm", "update")
        (out / "oracle" / f"{s.id}.json").write_text(json.dumps({"id": s.id, "kind": s.kind, **s.oracle}, indent=2))
        if s.hidden:
            (out / "oracle" / f"{s.id}_hidden.py").write_text(s.hidden)
        written.append(s.id)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    print(json.dumps(write(Path(parser.parse_args().out).expanduser())))


if __name__ == "__main__":
    main()
