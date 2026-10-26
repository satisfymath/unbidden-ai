"""Build a dependency-only image per lockfile, the one step that may reach a package registry.

The build context holds only manifests and lockfiles copied from git, never repository code or local files,
and install scripts are disabled where the package manager allows it. Network access during the build is
authorised by the mandate's registry allowlist; it is a policy check, not a firewall, and is reported so.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from unbidden.observe.stack import NodeStack, PythonStack, tracked_files

NODE_REGISTRIES = ["registry.npmjs.org"]
PYTHON_REGISTRIES = ["pypi.org", "files.pythonhosted.org"]
PYRIGHT_VERSION = "1.1.414"
RUFF_VERSION = "0.17.2"
PYTEST_VERSION = "9.1.1"


@dataclass(frozen=True)
class DependencyImage:
    tag: str
    language: str
    registries: list[str]
    env: dict[str, str]
    links: dict[str, str]  # path inside /work -> target inside the image, created as symlinks in each snapshot


class ProvisionError(RuntimeError):
    pass


def _copy_from_git(repo: Path, rev: str, paths: list[str], dest: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        data = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, check=True).stdout
        target = dest / "ctx" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest.update(path.encode() + b"\0" + data)
    return digest.hexdigest()[:16]


def node_dockerfile(stack: NodeStack) -> str:
    install = {
        "npm": "npm ci --ignore-scripts --no-audit --no-fund",
        "pnpm": "corepack enable && pnpm install --frozen-lockfile --ignore-scripts",
    }[stack.manager]
    return f"""FROM node:{stack.major}-slim
ENV CI=1 COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /deps
COPY ctx/ /deps/
RUN {install}
"""


def python_dockerfile(stack: PythonStack) -> str:
    if stack.lockfile == "uv.lock":
        install = "uv sync --frozen --no-install-project --all-groups --project /deps"
    elif stack.manifest == "requirements.txt":
        install = "uv venv /deps/.venv && uv pip install --python /deps/.venv/bin/python -r /deps/requirements.txt"
    else:
        install = "uv sync --no-install-project --all-groups --project /deps"
    return f"""FROM node:22-slim AS node
FROM python:{stack.version}-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \\
 && npm install -g pyright@{PYRIGHT_VERSION} \\
 && pip install --no-cache-dir uv \\
 && uv venv /opt/tools && uv pip install --python /opt/tools/bin/python ruff=={RUFF_VERSION} pytest=={PYTEST_VERSION}
ENV UV_PROJECT_ENVIRONMENT=/deps/.venv UV_LINK_MODE=copy
WORKDIR /deps
COPY ctx/ /deps/
RUN {install} \\
 && (/deps/.venv/bin/python -c "import pytest" 2>/dev/null \\
     || uv pip install --python /deps/.venv/bin/python pytest=={PYTEST_VERSION})
"""


def _manifests(repo: Path, rev: str, stack: NodeStack | PythonStack) -> list[str]:
    files = tracked_files(repo, rev)
    if isinstance(stack, NodeStack):
        wanted = [f for f in files if f == "package.json" or f.endswith("/package.json")]
        wanted += [stack.lockfile]
        wanted += [f for f in ("pnpm-workspace.yaml", ".npmrc") if f in files]
        # Packages vendored under node_modules are never tracked in sane repos; skip them if they are.
        return sorted({f for f in wanted if "node_modules/" not in f})
    wanted = [stack.manifest] + ([stack.lockfile] if stack.lockfile else [])
    return sorted(set(wanted))


def provision(repo: Path, rev: str, stack: NodeStack | PythonStack, *, docker: str = "docker") -> DependencyImage:
    language = "node" if isinstance(stack, NodeStack) else "python"
    build = Path(tempfile.mkdtemp(prefix="unbidden-build-"))
    try:
        digest = _copy_from_git(repo, rev, _manifests(repo, rev, stack), build)
        dockerfile = node_dockerfile(stack) if isinstance(stack, NodeStack) else python_dockerfile(stack)
        tag = f"unbidden-deps-{language}:{hashlib.sha256((dockerfile + digest).encode()).hexdigest()[:16]}"
        exists = subprocess.run([docker, "image", "inspect", tag], capture_output=True, check=False).returncode == 0
        if not exists:
            (build / "Dockerfile").write_text(dockerfile)
            result = subprocess.run([docker, "build", "-q", "-t", tag, str(build)], capture_output=True, text=True)
            if result.returncode != 0:
                tail = "\n".join(result.stderr.strip().splitlines()[-15:])
                raise ProvisionError(f"dependency image for {language} failed to build:\n{tail}")
    finally:
        shutil.rmtree(build, ignore_errors=True)
    if language == "node":
        return DependencyImage(
            tag=tag,
            language="node",
            registries=NODE_REGISTRIES,
            env={"PATH": "/deps/node_modules/.bin:/usr/local/bin:/usr/bin:/bin"},
            links={"node_modules": "/deps/node_modules"},
        )
    return DependencyImage(
        tag=tag,
        language="python",
        registries=PYTHON_REGISTRIES,
        env={
            "PATH": "/deps/.venv/bin:/opt/tools/bin:/usr/local/bin:/usr/bin:/bin",
            "VIRTUAL_ENV": "/deps/.venv",
            "PYTHONPATH": "/work/src:/work",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        links={},
    )


def link_dependencies(work: Path, image: DependencyImage) -> None:
    for name, target in image.links.items():
        path = work / name
        if path.is_symlink() or path.exists():
            continue
        path.symlink_to(target)
