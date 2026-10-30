"""Python: uv, poetry, requirements files and setup.py read statically; workspace members installed with the root."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from unbidden.languages import Syntax, register
from unbidden.observe.stack import PythonStack, _detect_python  # pyright: ignore[reportPrivateUsage]
from unbidden.sandbox.provision import (
    PYTHON_REGISTRIES,
    DependencyImage,
    _manifests,  # pyright: ignore[reportPrivateUsage]
    _python_notes,  # pyright: ignore[reportPrivateUsage]
    python_dockerfile,
)
from unbidden.sandbox.tools import TOOLS, Tool


class PythonAdapter:
    name = "python"
    part_type = PythonStack
    syntax = Syntax("Python", "#", "`# type: ignore`, `# noqa`", (".py", ".pyi"))
    registries = tuple(PYTHON_REGISTRIES)
    capabilities = frozenset({"analyze", "test", "fix", "probe", "perf"})
    test_report = "junit"

    def detect(self, repo: Path, rev: str, files: set[str], blind: list[str]) -> PythonStack | None:
        return _detect_python(repo, rev, files, blind)

    def manifests(self, repo: Path, rev: str, part: PythonStack) -> list[str]:
        return _manifests(repo, rev, part)

    def generated(self, part: PythonStack) -> dict[str, str]:
        # The requirements were read statically (setup.py's install_requires, poetry.lock's pins).
        if part.manifest in ("setup.py", "poetry.lock"):
            return {"unbidden-requirements.txt": "\n".join(part.requirements) + "\n"}
        return {}

    def dockerfile(self, part: PythonStack, *, system_build_tools: bool, headers: tuple[str, ...]) -> str:
        return python_dockerfile(part, system_build_tools=system_build_tools, headers=headers)

    def image(self, tag: str, part: PythonStack, docker: str) -> DependencyImage:
        return DependencyImage(
            tag=tag,
            language="python",
            registries=list(self.registries),
            env={
                "PATH": "/deps/.venv/bin:/opt/tools/bin:/usr/local/bin:/usr/bin:/bin",
                "VIRTUAL_ENV": "/deps/.venv",
                "PYTHONPATH": ":".join("/work" if r == "." else f"/work/{r}" for r in part.source_roots),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            links={path: f"/deps/generated/{path}" for path in part.build_writes},
            notes=_python_notes(tag, part, docker),
        )

    def tools(self, part: PythonStack) -> list[Tool]:
        selected: list[Tool] = []
        if part.ruff:
            selected.append(TOOLS["ruff"])
        else:
            # A repository that declares no linter still deserves a look for plain bugs.
            selected.append(TOOLS["ruff-baseline"])
        if part.pyright:
            selected.append(TOOLS["pyright"])
        if part.mypy is not None:
            mypy = TOOLS["mypy"]
            selected.append(replace(mypy, argv=(*mypy.argv, *part.mypy)))
        return selected

    def test_argv(self, part: PythonStack) -> list[str] | None:
        return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *part.test_paths] if part.pytest else None


ADAPTER = register(PythonAdapter())
