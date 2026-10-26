"""Detect what a repository is built with, from its tracked files only."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

DEFAULT_NODE_MAJOR = 22
DEFAULT_PYTHON = "3.12"

NodeManager = Literal["npm", "pnpm", "yarn"]


@dataclass(frozen=True)
class NodeStack:
    manager: NodeManager
    lockfile: str
    major: int
    major_assumed: bool  # true when the repo declares no Node version and we picked one; reported, never hidden
    typescript: bool
    eslint: bool
    biome: bool
    prettier: bool
    test_script: str | None


@dataclass(frozen=True)
class PythonStack:
    version: str
    lockfile: str | None  # uv.lock or requirements file
    manifest: str  # pyproject.toml or requirements file
    ruff: bool
    pyright: bool
    pytest: bool


@dataclass(frozen=True)
class Stack:
    node: NodeStack | None = None
    python: PythonStack | None = None
    blind_spots: list[str] = field(default_factory=list[str])

    @property
    def languages(self) -> list[str]:
        return [name for name, s in (("node", self.node), ("python", self.python)) if s is not None]


def tracked_files(repo: Path, rev: str = "HEAD") -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", rev], capture_output=True, text=True, check=True
    )
    return set(out.stdout.splitlines())


def _read(repo: Path, rev: str, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True, check=True
    ).stdout


def _node_major(repo: Path, rev: str, files: set[str], package: dict[str, Any]) -> tuple[int, bool]:
    for name in (".nvmrc", ".node-version"):
        if name in files:
            match = re.search(r"(\d+)", _read(repo, rev, name))
            if match:
                return int(match.group(1)), False
    engines = package.get("engines", {})
    node = engines.get("node") if isinstance(engines, dict) else None
    if isinstance(node, str):
        match = re.search(r"(\d+)", node)
        if match:
            return max(int(match.group(1)), 18), False
    return DEFAULT_NODE_MAJOR, True


def _deps(package: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section = package.get(key)
        if isinstance(section, dict):
            names.update(str(k) for k in section)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return names


def _detect_node(repo: Path, rev: str, files: set[str], blind: list[str]) -> NodeStack | None:
    if "package.json" not in files:
        return None
    package = json.loads(_read(repo, rev, "package.json"))
    lock: tuple[NodeManager, str] | None = None
    for manager, name in (("pnpm", "pnpm-lock.yaml"), ("npm", "package-lock.json"), ("yarn", "yarn.lock")):
        if name in files:
            lock = (manager, name)  # type: ignore[assignment]
            break
    if lock is None:
        blind.append("package.json has no lockfile; dependencies cannot be installed reproducibly")
        return None
    if lock[0] == "yarn":
        blind.append("yarn projects are not supported yet")
        return None
    if "pnpm-workspace.yaml" in files or package.get("workspaces"):
        blind.append("workspace (monorepo) packages are analyzed from the root only")
    deps = _deps(package)
    major, assumed = _node_major(repo, rev, files, package)
    scripts = package.get("scripts", {})
    test: str | None = None
    if isinstance(scripts, dict):
        # A unit-test script is preferred: full `test` scripts often bundle builds or networked checks.
        for name in ("test:unit", "test"):
            value = scripts.get(name)
            if isinstance(value, str) and "no test specified" not in value:
                test = name
                break
    return NodeStack(
        manager=lock[0],
        lockfile=lock[1],
        major=major,
        major_assumed=assumed,
        typescript="typescript" in deps and "tsconfig.json" in files,
        eslint="eslint" in deps,
        biome="@biomejs/biome" in deps,
        prettier="prettier" in deps,
        test_script=test,
    )


def _detect_python(repo: Path, rev: str, files: set[str], blind: list[str]) -> PythonStack | None:
    if "pyproject.toml" in files:
        project = tomllib.loads(_read(repo, rev, "pyproject.toml"))
        text = json.dumps(project)
        lock = "uv.lock" if "uv.lock" in files else None
        if lock is None:
            blind.append("pyproject.toml without uv.lock: dependencies resolved at provisioning time")
        version = DEFAULT_PYTHON
        if ".python-version" in files:
            version = _read(repo, rev, ".python-version").strip() or DEFAULT_PYTHON
        return PythonStack(
            version=version,
            lockfile=lock,
            manifest="pyproject.toml",
            ruff="ruff" in text,
            pyright="pyright" in text,
            pytest="pytest" in text or any(f.startswith("tests/") for f in files),
        )
    if "requirements.txt" in files:
        return PythonStack(
            version=DEFAULT_PYTHON,
            lockfile="requirements.txt",
            manifest="requirements.txt",
            ruff=False,
            pyright=False,
            pytest=any(f.startswith("tests/") or f.endswith("_test.py") for f in files),
        )
    return None


def detect_stack(repo: Path, rev: str = "HEAD") -> Stack:
    files = tracked_files(repo, rev)
    blind: list[str] = []
    return Stack(
        node=_detect_node(repo, rev, files, blind),
        python=_detect_python(repo, rev, files, blind),
        blind_spots=blind,
    )
