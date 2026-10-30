from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from unbidden.observe.compose import interpolate, load_compose, parse_dotenv
from unbidden.observe.stack import _setup_requirements, detect_stack  # pyright: ignore[reportPrivateUsage]
from unbidden.sandbox.runner import SandboxResult
from unbidden.sandbox.tools import TOOLS, tools_for

pytestmark = pytest.mark.unit


def commit(repo: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return repo


def test_setup_py_is_read_not_run() -> None:
    assert _setup_requirements("setup(install_requires=['pandas>=0.24', 'matplotlib'])") == (
        "pandas>=0.24",
        "matplotlib",
    )
    assert _setup_requirements("setup(install_requires=open('r.txt').read().split())") is None
    assert _setup_requirements("setup(name='x')") == ()


def test_uv_workspace_members_and_test_paths(tmp_path: Path) -> None:
    repo = commit(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname="root"\n[tool.uv.workspace]\nmembers=["backend"]\n',
            "uv.lock": "",
            "backend/pyproject.toml": '[project]\nname="app"\n[dependency-groups]\ndev=["pytest","ruff"]\n',
            "backend/tests/test_a.py": "def test_a(): pass\n",
        },
    )
    py = detect_stack(repo).python
    assert py is not None
    assert py.members == ("backend",) and py.ruff and py.pytest
    assert py.source_roots[0] == "backend" and py.test_paths == ("backend/tests",)


def test_baseline_tool_when_no_linter_is_declared(tmp_path: Path) -> None:
    repo = commit(tmp_path, {"setup.py": "setup(install_requires=['x'])", "pkg/a.py": "y = undefined\n"})
    stack = detect_stack(repo)
    assert [t.name for t in tools_for(stack)] == ["ruff-baseline"]
    out = '[{"code": "F821", "filename": "/work/pkg/a.py", "location": {"row": 1}, "message": "Undefined name"}]'
    report = TOOLS["ruff-baseline"].report(SandboxResult(0, out, "", False, 0.1, False, False), [])
    assert report.tool == "ruff-baseline"
    assert report.findings[0].tool == "ruff-baseline" and report.findings[0].category == "bugs"


def test_compose_interpolates_only_from_the_tracked_env(tmp_path: Path) -> None:
    compose = (
        "services:\n  db:\n    image: postgres:18\n    environment:\n"
        "      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?x}\n"
        "  api:\n    build: {context: ., dockerfile: api/Dockerfile}\n    depends_on: [db]\n"
        "    environment:\n      DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/app\n"
        "      MISSING: ${NOPE}\n      DEFAULTED: ${NOPE:-fallback}\n"
    )
    repo = commit(tmp_path, {"compose.yml": compose, ".env": "POSTGRES_PASSWORD=changethis\n"})
    (repo / ".env.local").write_text("POSTGRES_PASSWORD=real-secret\n")
    loaded = load_compose(repo)
    assert loaded is not None
    assert [s.name for s in loaded.data_services()] == ["db"]
    api = loaded.app_service_for("api")
    assert api is not None and api.environment["DATABASE_URL"] == "postgresql://postgres:changethis@db:5432/app"
    assert api.environment["DEFAULTED"] == "fallback" and loaded.unresolved == ["NOPE"]


def test_dotenv_references() -> None:
    env = parse_dotenv('A=1\nB="x${A}y"\n# c\n')
    assert env == {"A": "1", "B": "x1y"}
    assert interpolate("${A:-z}${Q-d}", env, []) == "1d"


def test_a_node_library_without_a_lockfile_is_resolved_at_provisioning(tmp_path: Path) -> None:
    from unbidden.sandbox.provision import node_dockerfile

    repo = commit(tmp_path, {"package.json": '{"name": "lib", "devDependencies": {"typescript": "5"}}'})
    stack = detect_stack(repo)
    assert stack.node is not None and stack.node.lockfile is None
    assert any("without a lockfile" in b for b in stack.blind_spots)
    dockerfile = node_dockerfile(stack.node)
    assert "npm install --ignore-scripts" in dockerfile and "npm ci" not in dockerfile


def test_languages_not_analyzed_are_named(tmp_path: Path) -> None:
    repo = commit(tmp_path, {"Cargo.toml": "[package]\n", "web/Gemfile": "gem 'rails'\n"})
    stack = detect_stack(repo)
    assert stack.languages == []
    assert any(b.startswith("Rust (Cargo.toml) is not analyzed") for b in stack.blind_spots)
    assert any(b.startswith("Ruby (Gemfile)") for b in stack.blind_spots)
    # Go has an adapter now: detected, not named as a blind spot.
    go = detect_stack(commit(tmp_path / "go", {"go.mod": "module x\n\ngo 1.22\n"}))
    assert go.languages == ["go"] and not any("Go (go.mod)" in b for b in go.blind_spots)


def test_versions_from_git_do_not_break_the_dependency_image() -> None:
    from unbidden.observe.stack import PythonStack
    from unbidden.sandbox.provision import python_dockerfile

    stack = PythonStack(version="3.12", lockfile=None, manifest="pyproject.toml", ruff=True, pyright=False, pytest=True)
    assert "SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0" in python_dockerfile(stack)


def test_documents_a_manifest_declares_go_into_the_build_context(tmp_path: Path) -> None:
    from unbidden.sandbox.provision import _manifests  # pyright: ignore[reportPrivateUsage]

    repo = commit(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname="x"\nreadme="README.md"\n',
            "README.md": "x\n",
            "LICENSE": "MIT\n",
            "src/x/__init__.py": "",
            "docs/README.md": "not at the root\n",
        },
    )
    stack = detect_stack(repo)
    assert stack.python is not None
    assert _manifests(repo, "HEAD", stack.python) == ["LICENSE", "README.md", "pyproject.toml"]


def test_a_version_module_the_build_would_generate_exists_in_the_snapshot(tmp_path: Path) -> None:
    from unbidden.sandbox.runner import discard, snapshot

    repo = commit(
        tmp_path / "repo",
        {
            "pyproject.toml": '[tool.hatch.build.hooks.vcs]\nversion-file = "src/x/_version.py"\n',
            "src/x/__init__.py": "from x._version import __version__\n",
        },
    )
    work = snapshot(repo, "HEAD")
    try:
        assert '__version__ = version = "0.0.0"' in (work / "src/x/_version.py").read_text()
    finally:
        discard(work)


def test_unbiddens_tools_install_on_the_oldest_python_a_project_supports() -> None:
    from unbidden.observe.stack import PythonStack
    from unbidden.sandbox.provision import python_dockerfile

    stack = PythonStack(version="3.9", lockfile=None, manifest="pyproject.toml", ruff=True, pyright=False, pytest=True)
    # pytest's pinned version needs 3.10; the newest that installs is taken instead of failing the image.
    assert "|| uv pip install --python /opt/tools/bin/python ruff==" in python_dockerfile(stack)


def test_a_computed_version_becomes_static_in_the_build_contexts_copy_only() -> None:
    import tomllib

    from unbidden.sandbox.provision import static_version

    original = (
        b'[project]\nname = "x"\ndynamic = ["version", "readme"]\n\n'
        b'[tool.setuptools.dynamic]\nversion = {attr = "x.__version__"}\n'
    )
    project = tomllib.loads(static_version(original).decode())["project"]
    assert project["version"] == "0.0.0" and project["dynamic"] == ["readme"]
    static = b'[project]\nname = "x"\nversion = "1.2"\n'
    assert static_version(static) == static


def test_the_default_branch_comes_from_the_remote_after_a_shallow_fetch(tmp_path: Path) -> None:
    from unbidden.workspace import default_branch

    upstream = commit(tmp_path / "up", {"a": "1\n"})
    subprocess.run(["git", "-C", str(upstream), "branch", "-m", "dev"], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", str(upstream)], check=True)
    subprocess.run(["git", "-C", str(clone), "fetch", "-q", "--depth", "1", "origin", "dev"], check=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", "FETCH_HEAD"], check=True)
    assert default_branch(clone) == "dev"


def test_uv_projects_install_with_their_own_uv_python_groups_and_path_sources(tmp_path: Path) -> None:
    from unbidden.sandbox.provision import python_dockerfile

    repo = commit(
        tmp_path,
        {
            "pyproject.toml": "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'requires-python = ">=3.11"',
                    "[tool.uv]",
                    'required-version = "==0.12.6"',
                    "[tool.uv.dependency-groups]",
                    'py312 = { requires-python = ">=3.12" }',
                    "[tool.uv.sources]",
                    'shim = { path = "src/shim" }',
                    "",
                ]
            ),
            "uv.lock": "version = 1\n",
            "src/shim/pyproject.toml": '[project]\nname = "shim"\n',
        },
    )
    python = detect_stack(repo).python
    assert python is not None
    assert (python.version, python.uv_version, python.skip_groups) == ("3.11", "==0.12.6", ("py312",))
    assert python.path_sources == (("shim", "src/shim"),)
    dockerfile = python_dockerfile(python)
    assert 'pip install --no-cache-dir "uv==0.12.6"' in dockerfile
    assert "UV_PYTHON=/usr/local/bin/python3.11 UV_PYTHON_DOWNLOADS=never" in dockerfile
    assert "--no-group py312" in dockerfile and "--no-install-package shim" in dockerfile
    # The lockfile first; one out of date is resolved again, and the image says so.
    assert "uv sync --frozen --no-install-project" in dockerfile and "touch /deps/UNBIDDEN_LOCK_STALE" in dockerfile


def test_dependencies_setuptools_reads_from_a_file_become_static_in_the_context() -> None:
    import tomllib

    from unbidden.sandbox.provision import static_metadata

    original = (
        b'[project]\nname = "x"\ndynamic = ["version", "dependencies"]\n\n'
        b'[tool.setuptools.dynamic]\ndependencies = {file = ["requirements.txt"]}\n'
    )
    files = {"requirements.txt": "httpx>=0.27  # client\n\npyyaml\n"}
    project = tomllib.loads(static_metadata(original, files.get).decode())["project"]
    assert project["dependencies"] == ["httpx>=0.27", "pyyaml"] and project["version"] == "0.0.0"
    with_options = {"requirements.txt": "-r base.txt\nhttpx\n"}
    assert "dependencies" in tomllib.loads(static_metadata(original, with_options.get).decode())["project"]["dynamic"]


def test_bun_projects_install_from_their_lockfile_with_their_declared_bun(tmp_path: Path) -> None:
    from unbidden.sandbox.provision import _manifests, node_dockerfile  # pyright: ignore[reportPrivateUsage]

    repo = commit(
        tmp_path,
        {
            "package.json": '{"name": "a", "packageManager": "bun@1.3.14", '
            '"patchedDependencies": {"left-pad@1.0.0": "patches/left-pad@1.0.0.patch"}}',
            "bun.lock": "{}\n",
            "patches/left-pad@1.0.0.patch": "diff\n",
        },
    )
    node = detect_stack(repo).node
    assert node is not None and (node.manager, node.manager_version, node.lockfile) == ("bun", "1.3.14", "bun.lock")
    dockerfile = node_dockerfile(node)
    assert (
        dockerfile.startswith("FROM oven/bun:1.3.14 AS bun")
        and "bun install --frozen-lockfile --ignore-scripts" in dockerfile
    )
    assert "patches/left-pad@1.0.0.patch" in _manifests(repo, "HEAD", node)


def test_a_build_error_keeps_the_installers_explanation() -> None:
    from unbidden.sandbox.provision import build_error

    stderr = "\n".join(
        [
            "#8 0.27 error: No solution found when resolving dependencies",
            "#8 0.27   cause: Because only shim==0.0.0 is available and shim depends on your project, ...",
            "#8 0.27 hint: The package `shim` depends on the package `app` but the name is shadowed",
            "Dockerfile:12",
            "ERROR: failed to build",
        ]
    )
    text = build_error(stderr)
    assert "cause: Because only shim==0.0.0" in text and "hint: The package" in text


def test_independent_subprojects_are_found_when_the_root_offers_nothing_to_check() -> None:
    from unbidden.observe.scan import subprojects
    from unbidden.observe.stack import Stack

    files = {
        "package.json", "README.md",
        "server/package.json", "server/yarn.lock", "server/index.js", "server/a.js",
        "frontend/package.json", "frontend/yarn.lock", "frontend/src/app.js",
        "tests/fixture/package.json", "tests/fixture/package-lock.json",
        "services/api/requirements.txt", "services/api/main.py",
        "server/plugins/x/package.json", "server/plugins/x/yarn.lock",
    }  # fmt: skip
    assert subprojects(files, Stack()) == ["frontend", "server", "services/api"]
    assert subprojects({*files, "rush.json"}, Stack()) == []


def test_yarn_classic_installs_and_berry_is_named(tmp_path: Path) -> None:
    from unbidden.sandbox.provision import node_dockerfile

    classic = commit(tmp_path / "c", {"package.json": '{"name": "a"}', "yarn.lock": "# yarn lockfile v1\n\n"})
    node = detect_stack(classic).node
    assert node is not None and node.manager == "yarn"
    assert "yarn install --frozen-lockfile --ignore-scripts" in node_dockerfile(node)
    berry = commit(
        tmp_path / "b", {"package.json": '{"name": "a", "packageManager": "yarn@4.1.0"}', "yarn.lock": "x\n"}
    )
    stack = detect_stack(berry)
    assert stack.node is None and any("Berry" in b for b in stack.blind_spots)


def test_ci_commands_follow_the_package_scripts_a_workflow_calls(tmp_path: Path) -> None:
    from unbidden.observe.ci import ci_commands

    repo = commit(
        tmp_path,
        {
            ".github/workflows/ci.yml": "jobs:\n  c:\n    steps:\n      - run: pnpm check\n",
            "package.json": '{"scripts": {"check": "pnpm run types", "types": "tsc -b tsconfig.json"}}',
        },
    )
    commands = ci_commands(repo, "HEAD")
    assert commands is not None and "tsc -b tsconfig.json" in commands


def test_pnpm_comes_from_the_lockfile_when_the_project_declares_none(tmp_path: Path) -> None:
    from unbidden.sandbox.provision import node_dockerfile

    repo = commit(tmp_path, {"package.json": '{"name": "a"}', "pnpm-lock.yaml": "lockfileVersion: '9.0'\n"})
    node = detect_stack(repo).node
    assert node is not None and (node.manager, node.manager_version) == ("pnpm", "10")
    assert "corepack prepare pnpm@10 --activate" in node_dockerfile(node)


def test_files_the_build_writes_and_the_repository_lacks_are_found_from_pyproject() -> None:
    from unbidden.observe.stack import build_writes

    project = {
        "tool": {
            "versioningit": {"write": {"path": "src/pkg/_build_info.py"}},
            "hatch": {"build": {"artifacts": ["src/pkg/_config.py", "src/pkg/ui", "src/pkg/*.so"]}},
            "setuptools_scm": {"version_file": "src/pkg/_version.py"},
        }
    }
    found = build_writes(project, ["pyproject.toml", "src/pkg/__init__.py", "src/pkg/_version.py"])
    assert found == ("src/pkg/_build_info.py", "src/pkg/_config.py")  # tracked files and non-Python artifacts left
    assert build_writes({}, []) == ()


def test_a_build_that_writes_files_gets_a_stage_that_keeps_only_those_files() -> None:
    from unbidden.observe.stack import PythonStack
    from unbidden.sandbox.provision import own_extract_script, python_dockerfile

    plain = PythonStack(version="3.12", lockfile=None, manifest="pyproject.toml", ruff=True, pyright=False, pytest=True)
    assert " AS own" not in python_dockerfile(plain) and "/deps/generated" not in python_dockerfile(plain)
    writes = PythonStack(
        version="3.12", lockfile=None, manifest="pyproject.toml", ruff=True, pyright=False, pytest=True,
        build_writes=("src/pkg/_build_info.py",),
    )  # fmt: skip
    dockerfile = python_dockerfile(writes)
    assert dockerfile.startswith("FROM python:3.12 AS own")  # the full image: version plugins call git
    assert dockerfile.rstrip().endswith("COPY --from=own /generated/ /deps/generated/")
    assert "'src/pkg/_build_info.py': ['pkg/_build_info.py', 'src/pkg/_build_info.py']" in own_extract_script(writes)


def test_pyright_in_a_python_image_gets_nodes_larger_heap_and_memory() -> None:
    from unbidden.sandbox.provision import DEFAULT_MEMORY, NODE_HEAP_MB, NODE_MEMORY, sandbox_spec
    from unbidden.sandbox.provision import DependencyImage as Image

    image = Image(tag="img", language="python", registries=[], env={}, links={})
    pyright = sandbox_spec(image, ["pyright", "--outputjson"])
    assert pyright.env["NODE_OPTIONS"] == f"--max-old-space-size={NODE_HEAP_MB}" and pyright.memory == NODE_MEMORY
    mypy = sandbox_spec(image, ["mypy", "."])
    assert "NODE_OPTIONS" not in mypy.env and mypy.memory == DEFAULT_MEMORY


def test_the_lab_keeps_every_finding_where_the_scan_keeps_the_cap() -> None:
    from unbidden.sandbox.tools import MAX_FINDINGS, every_finding, parse_pyright

    diagnostics = [
        {"file": f"/work/m{i}.py", "severity": "error", "message": "x", "rule": "r", "range": {"start": {"line": 1}}}
        for i in range(MAX_FINDINGS + 5)
    ]
    result = SandboxResult(1, json.dumps({"generalDiagnostics": diagnostics}), "", False, 1.0, False, False)
    capped = parse_pyright(result, ["pyright"])
    assert capped.completeness.value == "partial" and capped.dropped == 5
    with every_finding():
        whole = parse_pyright(result, ["pyright"])
    assert whole.can_resolve and len(whole.findings) == MAX_FINDINGS + 5
