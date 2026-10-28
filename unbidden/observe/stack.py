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

NodeManager = Literal["npm", "pnpm", "yarn", "bun"]


@dataclass(frozen=True)
class NodePackage:
    """One package of a JavaScript workspace (monorepo), analyzed in its own directory."""

    path: str
    name: str
    typescript: bool
    typecheck: tuple[str, ...] | None  # the package's own tsc command, if its typecheck script is plain tsc
    eslint: bool
    biome: bool
    prisma_schema: str | None = None  # tracked schema whose client must be generated first


@dataclass(frozen=True)
class NodeStack:
    manager: NodeManager
    lockfile: str | None  # None: resolved by npm at provisioning time, said as a blind spot
    major: int
    major_assumed: bool  # true when the repo declares no Node version and we picked one; reported, never hidden
    typescript: bool
    eslint: bool
    biome: bool
    prettier: bool
    test_script: str | None
    packages: tuple[NodePackage, ...] = ()
    manager_version: str | None = None  # from package.json's packageManager ("bun@1.3.14" -> "1.3.14")


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
    mypy: tuple[str, ...] | None = None  # mypy's targets when the repository uses it; empty: its config names them
    uv_version: str | None = None  # [tool.uv] required-version: the project's uv refuses any other
    skip_groups: tuple[str, ...] = ()  # dependency groups whose own requires-python excludes `version`
    path_sources: tuple[tuple[str, str], ...] = ()  # (package, directory) installed from a path in the repository


@dataclass(frozen=True)
class Stack:
    node: NodeStack | None = None
    python: PythonStack | None = None
    blind_spots: list[str] = field(default_factory=list[str])
    others: dict[str, Any] = field(default_factory=dict[str, Any])  # languages added through an adapter (go, ...)

    def part(self, language: str) -> Any:
        """This language's description, whichever adapter detected it."""
        return {"node": self.node, "python": self.python}.get(language, self.others.get(language))

    @property
    def languages(self) -> list[str]:
        from unbidden.languages import adapters

        return [a.name for a in adapters() if self.part(a.name) is not None]


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


def _workspace_globs(repo: Path, rev: str, files: set[str], package: dict[str, Any]) -> list[str]:
    globs: list[str] = []
    if "pnpm-workspace.yaml" in files:
        import yaml

        data = yaml.safe_load(_read(repo, rev, "pnpm-workspace.yaml")) or {}
        globs += [str(g) for g in data.get("packages", []) if not str(g).startswith("!")]
    workspaces = package.get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages", [])  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if isinstance(workspaces, list):
        globs += [str(g) for g in workspaces]  # pyright: ignore[reportUnknownVariableType]
    return globs


def _workspace_packages(repo: Path, rev: str, files: set[str], root: dict[str, Any]) -> tuple[NodePackage, ...]:
    packages: list[NodePackage] = []
    for glob in _workspace_globs(repo, rev, files, root):
        for manifest in sorted(f for f in files if f.endswith("/package.json") and "node_modules/" not in f):
            directory = manifest.removesuffix("/package.json")
            if not fnmatch.fnmatch(directory, glob.rstrip("/")):
                continue
            data = json.loads(_read(repo, rev, manifest))
            deps = _deps(data) | _deps(root)
            scripts = data.get("scripts", {}) if isinstance(data.get("scripts"), dict) else {}
            typecheck = str(scripts.get("typecheck", ""))
            plain_tsc = re.fullmatch(r"tsc(?:\s+-{1,2}[\w-]+)*", typecheck.strip())
            packages.append(
                NodePackage(
                    path=directory,
                    name=str(data.get("name", directory)),
                    typescript="typescript" in deps and f"{directory}/tsconfig.json" in files,
                    typecheck=tuple(typecheck.split()) if plain_tsc else None,
                    eslint="eslint" in _deps(data),
                    biome="@biomejs/biome" in _deps(data),
                    prisma_schema=next(
                        (
                            f
                            for f in (f"{directory}/prisma/schema.prisma", f"{directory}/schema.prisma")
                            if f in files and "prisma" in deps
                        ),
                        None,
                    ),
                )
            )
    return tuple(dict.fromkeys(packages))


def _yarn_berry(repo: Path, rev: str, files: set[str], package: dict[str, Any]) -> bool:
    declared = str(package.get("packageManager") or "")
    if re.match(r"yarn@[2-9]", declared) or ".yarnrc.yml" in files:
        return True
    return "yarn lockfile v1" not in _read(repo, rev, "yarn.lock")[:400]


# The newest pnpm major that writes each lockfile format, for projects that do not declare theirs: otherwise corepack
# takes whatever pnpm is newest the day the image is built.
PNPM_FOR_LOCKFILE = {"9.0": "10", "6.0": "8", "6.1": "8", "5.4": "7", "5.3": "6"}


def _pnpm_for_lockfile(text: str) -> str | None:
    found = re.search(r"^lockfileVersion:\s*['\"]?([\d.]+)", text[:300], re.MULTILINE)
    return PNPM_FOR_LOCKFILE.get(found.group(1)) if found else None


def _manager_version(package: dict[str, Any], manager: str) -> str | None:
    declared = package.get("packageManager")
    if isinstance(declared, str) and declared.startswith(f"{manager}@"):
        version = declared.split("@", 1)[1].split("+", 1)[0]
        return version if re.fullmatch(r"[\w.-]+", version) else None
    return None


def _detect_node(repo: Path, rev: str, files: set[str], blind: list[str]) -> NodeStack | None:
    if "package.json" not in files:
        return None
    package = json.loads(_read(repo, rev, "package.json"))
    lock: tuple[NodeManager, str | None] | None = None
    locks = (("pnpm", "pnpm-lock.yaml"), ("bun", "bun.lock"), ("bun", "bun.lockb"), ("npm", "package-lock.json"),
             ("yarn", "yarn.lock"))  # fmt: skip
    for manager, name in locks:
        if name in files:
            lock = (manager, name)  # type: ignore[assignment]
            break
    if lock is None:
        # Many libraries never commit a lockfile. Resolve at provisioning time, as for Python without uv.lock: the
        # image is kept by the manifest's digest, so runs on this machine share one resolution.
        blind.append("package.json without a lockfile: dependencies resolved at provisioning time")
        lock = ("npm", None)
    if lock[0] == "yarn" and _yarn_berry(repo, rev, files, package):
        # Berry's own binary comes from repo.yarnpkg.com, which is not among the registries an install may reach.
        blind.append("yarn 2+ (Berry) projects are not supported: yarn itself would come from repo.yarnpkg.com")
        return None
    packages = _workspace_packages(repo, rev, files, package)
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
        manager_version=_manager_version(package, lock[0])
        or (_pnpm_for_lockfile(_read(repo, rev, lock[1])) if lock[0] == "pnpm" and lock[1] else None),
        lockfile=lock[1],
        major=major,
        major_assumed=assumed,
        typescript="typescript" in deps and "tsconfig.json" in files,
        eslint="eslint" in deps,
        biome="@biomejs/biome" in deps,
        prettier="prettier" in deps,
        test_script=test,
        packages=packages,
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


def mypy_targets(pyproject: str, files: set[str], members: tuple[str, ...]) -> tuple[str, ...]:
    """What mypy checks: nothing to name when its configuration lists `files`; else the package named after the
    project (`mealie`), else the workspace members, else the repository."""
    project = tomllib.loads(pyproject)
    if project.get("tool", {}).get("mypy", {}).get("files"):
        return ()
    name = str(project.get("project", {}).get("name", "")).replace("-", "_")
    for package in (name, f"src/{name}"):
        if name and f"{package}/__init__.py" in files:
            return (package,)
    return members or (".",)


def requires_python(pyproject: str) -> str | None:
    """The lowest minor version `requires-python` admits (`>=3.14,<3.15` is 3.14), when it names one."""
    try:
        spec = str(tomllib.loads(pyproject).get("project", {}).get("requires-python", ""))
    except tomllib.TOMLDecodeError:
        return None
    found = re.search(r"(?:>=|~=|==)\s*(3\.\d+)", spec)
    return found.group(1) if found else None


def _detect_python(repo: Path, rev: str, files: set[str], blind: list[str]) -> PythonStack | None:
    version = DEFAULT_PYTHON
    if ".python-version" in files:
        version = _read(repo, rev, ".python-version").strip() or DEFAULT_PYTHON
    elif "pyproject.toml" in files:
        version = requires_python(_read(repo, rev, "pyproject.toml")) or DEFAULT_PYTHON
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
        mypy = mypy_targets(_read(repo, rev, "pyproject.toml"), files, members) if '"mypy' in text else None
        uv = uv_settings(tomllib.loads(_read(repo, rev, "pyproject.toml")), version, files)
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
            mypy=mypy,
            **uv,
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


def _admits(spec: str, version: str) -> bool:
    """Whether a requires-python spec (">=3.12", ">=3.10,<3.14") admits a minor version. Unknown forms admit it."""
    minor = int(version.split(".")[1])
    for clause in spec.split(","):
        found = re.match(r"\s*(>=|>|<=|<|==|~=)\s*3\.(\d+)", clause)
        if not found:
            continue
        op, bound = found.group(1), int(found.group(2))
        ok = {">=": minor >= bound, ">": minor > bound, "<=": minor <= bound, "<": minor < bound,
              "==": minor == bound, "~=": minor >= bound}[op]  # fmt: skip
        if not ok:
            return False
    return True


def uv_settings(pyproject: dict[str, Any], version: str, files: set[str]) -> dict[str, Any]:
    """What a uv project declares that changes how its dependencies install: a required uv version, groups that need
    another Python than the one chosen, and packages installed from a directory of the repository."""
    uv = pyproject.get("tool", {}).get("uv", {})
    required = uv.get("required-version")
    groups = uv.get("dependency-groups", {})
    skip = tuple(
        sorted(
            name
            for name, conf in groups.items()
            if isinstance(conf, dict) and conf.get("requires-python") and not _admits(conf["requires-python"], version)
        )
    )
    sources = uv.get("sources", {})
    paths = tuple(
        sorted(
            (name, str(conf["path"]).strip("./"))
            for name, conf in sources.items()
            if isinstance(conf, dict) and isinstance(conf.get("path"), str) and ".." not in conf["path"]
            and any(f.startswith(str(conf["path"]).strip("./") + "/") for f in files)
        )
    )  # fmt: skip
    return {"uv_version": required if isinstance(required, str) else None, "skip_groups": skip, "path_sources": paths}


def detect_stack(repo: Path, rev: str = "HEAD") -> Stack:
    files = tracked_files(repo, rev)
    blind: list[str] = []
    from unbidden.languages import adapters

    parts = {a.name: a.detect(repo, rev, files, blind) for a in adapters()}
    stack = Stack(
        node=parts.pop("node", None),
        python=parts.pop("python", None),
        blind_spots=blind,
        others={name: part for name, part in parts.items() if part is not None},
    )
    if stack.node is None and "rush.json" in files:
        blind.append("Rush monorepo (rush.json): not supported; its packages are not analyzed")
    for manifest, language in UNANALYZED:
        if manifest in files or any(f.endswith(f"/{manifest}") for f in files):  # Go has an adapter; nested modules
            # of a supported language are said by its adapter
            blind.append(f"{language} ({manifest}) is not analyzed: no checks, probes or experiments for that code")
    return stack


# Languages Unbidden does not analyze yet, found by their manifest so they are named rather than silently skipped.
UNANALYZED = (
    ("Cargo.toml", "Rust"),
    ("Gemfile", "Ruby"),
    ("pom.xml", "Java"),
    ("build.gradle", "Java/Kotlin"),
    ("build.gradle.kts", "Kotlin"),
    ("composer.json", "PHP"),
    ("mix.exs", "Elixir"),
    ("Package.swift", "Swift"),
    ("pubspec.yaml", "Dart"),
)
