"""Detect what a repository is built with, from its tracked files only."""

from __future__ import annotations

import ast
import fnmatch
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
    manifest: str  # pyproject.toml, requirements.txt or setup.py
    ruff: bool
    pyright: bool
    pytest: bool
    members: tuple[str, ...] = ()  # uv workspace members (directories), installed with the root
    requirements: tuple[str, ...] = ()  # read statically from setup.py; setup.py itself is never executed
    source_roots: tuple[str, ...] = ("src", ".")  # directories put on PYTHONPATH, relative to the repository
    test_paths: tuple[str, ...] = ()  # where pytest should look; empty means its own discovery


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


def poetry_requirements(lock_text: str) -> tuple[str, ...]:
    """Exact versions from a poetry.lock, read as data: poetry is never run, the project is never built."""
    lock = tomllib.loads(lock_text)
    pins: list[str] = []
    for package in lock.get("package", []):
        source = package.get("source", {})
        if source.get("type") in ("directory", "file", "git", "url"):
            continue
        pins.append(f"{package['name']}=={package['version']}")
    return tuple(sorted(pins))


def _setup_requirements(source: str) -> tuple[str, ...] | None:
    """`install_requires` from setup.py, only when it is a literal list. setup.py is parsed, never run."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "install_requires":
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            if isinstance(value, list | tuple) and all(isinstance(v, str) for v in value):  # pyright: ignore[reportUnknownVariableType]
                return tuple(value)  # pyright: ignore[reportUnknownArgumentType]
            return None
    return ()


def _workspace_members(repo: Path, rev: str, project: dict[str, Any], files: set[str]) -> tuple[str, ...]:
    workspace = project.get("tool", {}).get("uv", {}).get("workspace", {})
    patterns = workspace.get("members", []) if isinstance(workspace, dict) else []
    members: list[str] = []
    for pattern in patterns:
        for f in sorted(files):
            if f.endswith("/pyproject.toml") and fnmatch.fnmatch(f.removesuffix("/pyproject.toml"), pattern):
                members.append(f.removesuffix("/pyproject.toml"))
    return tuple(dict.fromkeys(members))


def _tests_under(files: set[str], roots: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for root in roots:
        prefix = "" if root == "." else root + "/"
        for name in ("tests", "test"):
            if any(f.startswith(f"{prefix}{name}/") and f.endswith(".py") for f in files):
                found.append(f"{prefix}{name}")
    return tuple(dict.fromkeys(found))


def _detect_python(repo: Path, rev: str, files: set[str], blind: list[str]) -> PythonStack | None:
    version = DEFAULT_PYTHON
    if ".python-version" in files:
        version = _read(repo, rev, ".python-version").strip() or DEFAULT_PYTHON
    if "pyproject.toml" in files and "poetry.lock" in files:
        project = tomllib.loads(_read(repo, rev, "pyproject.toml"))
        if "poetry" in project.get("tool", {}):
            text = json.dumps(project)
            return PythonStack(
                version=version,
                lockfile="poetry.lock",
                manifest="poetry.lock",
                ruff="ruff" in text,
                pyright="pyright" in text,
                pytest="pytest" in text or bool(_tests_under(files, (".",))),
                requirements=poetry_requirements(_read(repo, rev, "poetry.lock")),
            )
    if "pyproject.toml" in files:
        project = tomllib.loads(_read(repo, rev, "pyproject.toml"))
        members = _workspace_members(repo, rev, project, files)
        texts = [json.dumps(project)] + [
            json.dumps(tomllib.loads(_read(repo, rev, f"{m}/pyproject.toml"))) for m in members
        ]
        text = " ".join(texts)
        lock = "uv.lock" if "uv.lock" in files else None
        if lock is None:
            blind.append("pyproject.toml without uv.lock: dependencies resolved at provisioning time")
        roots = tuple(dict.fromkeys([*members, "src", "."]))
        tests = _tests_under(files, (*members, "."))
        return PythonStack(
            version=version,
            lockfile=lock,
            manifest="pyproject.toml",
            ruff="ruff" in text,
            pyright="pyright" in text,
            pytest="pytest" in text or bool(tests),
            members=members,
            source_roots=roots,
            test_paths=tests if members else (),
        )
    if "requirements.txt" in files:
        return PythonStack(
            version=version,
            lockfile="requirements.txt",
            manifest="requirements.txt",
            ruff=False,
            pyright=False,
            pytest=bool(_tests_under(files, (".",))) or any(f.endswith("_test.py") for f in files),
        )
    if "setup.py" in files:
        requirements = _setup_requirements(_read(repo, rev, "setup.py"))
        if requirements is None:
            blind.append("setup.py computes its dependencies; they cannot be read without running it")
            requirements = ()
        return PythonStack(
            version=version,
            lockfile=None,
            manifest="setup.py",
            ruff=False,
            pyright=False,
            pytest=bool(_tests_under(files, (".",))),
            requirements=requirements,
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
