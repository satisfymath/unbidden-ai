from __future__ import annotations

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
    repo = commit(tmp_path, {"go.mod": "module x\n", "web/Gemfile": "gem 'rails'\n"})
    stack = detect_stack(repo)
    assert stack.languages == []
    assert any(b.startswith("Go (go.mod) is not analyzed") for b in stack.blind_spots)
    assert any(b.startswith("Ruby (Gemfile)") for b in stack.blind_spots)


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
