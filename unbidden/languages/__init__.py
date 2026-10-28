"""Languages Unbidden reads, each behind one contract.

A `LanguageAdapter` says how to recognise a project in its language, which registries installing its dependencies may
reach, how to build the dependency image (from data only: manifests and lockfiles, never the project's code), which
of the repository's own tools run on it and how their output becomes findings, how its tests run offline and report
failures, and what the lab needs to edit it. The rest of Unbidden (the sandbox, the Director, the lab's evaluator,
the evidence and Guardian) does not know which language it is looking at.

An adapter declares its capabilities instead of having them assumed: `analyze` (its tools run and their findings are
read), `test` (its tests run offline and failures are named), `fix` (the lab may edit its files), `probe` and `perf`
(robustness probes, performance experiments). What an adapter does not declare is a blind spot, said as such.

Order matters only for reporting: languages are listed in registry order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from unbidden.sandbox.provision import DependencyImage
    from unbidden.sandbox.tools import Tool


@dataclass(frozen=True)
class Syntax:
    display: str  # how the lab names the language to a model
    comment: str  # line comment, for `# file:` headers
    suppressions: str  # what silencing the tool looks like, so the lab can refuse it
    suffixes: tuple[str, ...]


class LanguageAdapter(Protocol):
    name: str
    part_type: type  # the description its `detect` returns
    syntax: Syntax
    registries: tuple[str, ...]
    capabilities: frozenset[str]
    # How test failures are read: "junit" (a JUnit XML report), "go-test-json", or "exit" (pass or fail only).
    test_report: str

    def detect(self, repo: Path, rev: str, files: set[str], blind: list[str]) -> Any | None:
        """The project's description in this language, or None. Blind spots go into `blind`."""
        ...

    def manifests(self, repo: Path, rev: str, part: Any) -> list[str]:
        """Tracked files copied into the dependency build: data (manifests, lockfiles, patches), never code."""
        ...

    def generated(self, part: Any) -> dict[str, str]:
        """Files written into the build context besides the tracked ones (requirements read statically)."""
        ...

    def dockerfile(self, part: Any, *, system_build_tools: bool, headers: tuple[str, ...]) -> str: ...

    def image(self, tag: str, part: Any, docker: str) -> DependencyImage:
        """The built image as the sandbox uses it: environment, links into the snapshot, setup steps, notes."""
        ...

    def tools(self, part: Any) -> list[Tool]:
        """The repository's own tools for this language that apply to it."""
        ...

    def test_argv(self, part: Any) -> list[str] | None:
        """The test command when the CI does not say one."""
        ...


_REGISTRY: dict[str, LanguageAdapter] = {}
_LOADED = False
# The order languages are listed and run in, by adapter name, whatever order their modules were imported in.
ORDER = ("node", "python", "go")
MODULES = ("node", "python", "golang")


def register(adapter: LanguageAdapter) -> LanguageAdapter:
    _REGISTRY[adapter.name] = adapter
    return adapter


def adapters() -> list[LanguageAdapter]:
    _load()
    ordered = [_REGISTRY[n] for n in ORDER if n in _REGISTRY]
    return ordered + [a for n, a in _REGISTRY.items() if n not in ORDER]


def adapter(name: str) -> LanguageAdapter:
    _load()
    return _REGISTRY[name]


def adapter_of(part: Any) -> LanguageAdapter:
    """The adapter a detected description belongs to."""
    for a in adapters():
        if isinstance(part, a.part_type):
            return a
    raise KeyError(f"no language adapter for {type(part).__name__}")


def adapter_for_path(path: str) -> LanguageAdapter | None:
    return next((a for a in adapters() if path.endswith(a.syntax.suffixes)), None)


def _load() -> None:
    """Every adapter module, once, however the first one was reached (a direct import registers only itself)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    import importlib

    for module in MODULES:
        importlib.import_module(f"unbidden.languages.{module}")  # each registers itself
