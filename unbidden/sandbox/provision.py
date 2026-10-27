"""Build a dependency-only image per lockfile, the one step that may reach a package registry.

The build context holds only manifests and lockfiles copied from git, never repository code or local files,
and install scripts are disabled where the package manager allows it. Network access during the build is
authorised by the mandate's registry allowlist; it is a policy check, not a firewall, and is reported so.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from unbidden.observe.stack import NodeStack, PythonStack, tracked_files
from unbidden.sandbox.runner import SandboxSpec

if TYPE_CHECKING:
    from unbidden.guardian.policy import PolicyEngine

NODE_REGISTRIES = ["registry.npmjs.org"]
PYTHON_REGISTRIES = ["pypi.org", "files.pythonhosted.org"]
PYRIGHT_VERSION = "1.1.414"
RUFF_VERSION = "0.17.2"
PYTEST_VERSION = "9.1.1"
HYPOTHESIS_VERSION = "6.170.12"  # for robustness probes; installed only when the project does not bring it


@dataclass(frozen=True)
class DependencyImage:
    tag: str
    language: str
    registries: list[str]
    env: dict[str, str]
    links: dict[str, str]  # path inside /work -> target inside the image, created as symlinks in each snapshot
    setup: tuple[str, ...] = ()  # shell steps run in the container before each command


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
    if stack.lockfile is None:
        install = "npm install --ignore-scripts --no-audit --no-fund"
    # Code generation a type check depends on, from trusted tools only (never arbitrary install scripts): Prisma's
    # client is generated from the tracked schema, the one step besides installing that may use the network.
    generate = "".join(
        f" \\\n && (cd /deps/{p.path} && ./node_modules/.bin/prisma generate --schema "
        f"{(p.prisma_schema or '').removeprefix(p.path + '/')})"
        for p in stack.packages
        if p.prisma_schema
    )
    # The package manager corepack fetches here is kept where the sandbox user (uid 1000, no network) can run it.
    return f"""FROM node:{stack.major}-slim
ENV CI=1 COREPACK_ENABLE_DOWNLOAD_PROMPT=0 COREPACK_HOME=/opt/corepack
WORKDIR /deps
COPY ctx/ /deps/
RUN {install}{generate} \\
 && mkdir -p /opt/corepack && chmod -R a+rX /opt/corepack
"""


def python_dockerfile(stack: PythonStack, *, system_build_tools: bool = False, headers: tuple[str, ...] = ()) -> str:
    if stack.lockfile == "uv.lock" and stack.members:
        install = "uv sync --frozen --no-install-workspace --all-packages --all-groups --project /deps"
    elif stack.lockfile == "uv.lock":
        install = "uv sync --frozen --no-install-project --all-groups --project /deps"
    elif stack.manifest in ("setup.py", "poetry.lock"):
        # The requirements were read statically (setup.py's install_requires, poetry.lock's pins) and written
        # into the build context.
        install = (
            "uv venv /deps/.venv && uv pip install --python /deps/.venv/bin/python -r /deps/unbidden-requirements.txt"
        )
    elif stack.manifest == "requirements.txt":
        install = "uv venv /deps/.venv && uv pip install --python /deps/.venv/bin/python -r /deps/requirements.txt"
    else:
        install = "uv sync --no-install-project --all-groups --project /deps"
    build_tools = (
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        + " ".join(("build-essential", *headers))
        + " && rm -rf /var/lib/apt/lists/*\n"
        if system_build_tools
        else ""
    )
    return f"""FROM node:22-slim AS node
FROM python:{stack.version}-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \\
 && npm install -g pyright@{PYRIGHT_VERSION} \\
 && pip install --no-cache-dir uv \\
 && uv venv /opt/tools && uv pip install --python /opt/tools/bin/python ruff=={RUFF_VERSION} pytest=={PYTEST_VERSION}
{build_tools}ENV UV_PROJECT_ENVIRONMENT=/deps/.venv UV_LINK_MODE=copy
# Projects that take their version from git (setuptools-scm, hatch-vcs) cannot read it here: only manifests are
# copied, never .git. Their dependencies do not depend on the version.
ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
WORKDIR /deps
COPY ctx/ /deps/
RUN {install} \\
 && (/deps/.venv/bin/python -c "import pytest" 2>/dev/null \\
     || uv pip install --python /deps/.venv/bin/python pytest=={PYTEST_VERSION} \\
     || uv pip install --python /deps/.venv/bin/python pytest) \\
 && (/deps/.venv/bin/python -c "import hypothesis" 2>/dev/null \\
     || uv pip install --python /deps/.venv/bin/python hypothesis=={HYPOTHESIS_VERSION} \\
     || uv pip install --python /deps/.venv/bin/python hypothesis)
"""


# The pinned version first; when the repository's own uv settings exclude it (mealie's `exclude-newer`, a
# supply-chain cooling period), the newest one they allow.


def _manifests(repo: Path, rev: str, stack: NodeStack | PythonStack) -> list[str]:
    files = tracked_files(repo, rev)
    if isinstance(stack, NodeStack):
        wanted = [f for f in files if f == "package.json" or f.endswith("/package.json")]
        wanted += [stack.lockfile] if stack.lockfile else []
        wanted += [f for f in ("pnpm-workspace.yaml", ".npmrc") if f in files]
        wanted += [p.prisma_schema for p in stack.packages if p.prisma_schema]
        # Packages vendored under node_modules are never tracked in sane repos; skip them if they are.
        return sorted({f for f in wanted if "node_modules/" not in f})
    if stack.manifest in ("setup.py", "poetry.lock"):
        return []
    wanted = [stack.manifest] + ([stack.lockfile] if stack.lockfile else [])
    wanted += [f"{m}/pyproject.toml" for m in stack.members]
    # Build backends read the documents a manifest declares (hatchling refuses a missing `readme`) even when only the
    # metadata is built. Documents, never code.
    for directory in ["", *(f"{m}/" for m in stack.members)]:
        wanted += [f for f in files if f.startswith(directory) and METADATA_DOC.match(f.removeprefix(directory))]
    return sorted(set(wanted))


METADATA_DOC = re.compile(r"^(README|LICEN[CS]E|COPYING|NOTICE|AUTHORS|CHANGELOG|CHANGES)[\w.-]*$", re.IGNORECASE)


def build_error(stderr: str, keep: int = 12) -> str:
    """The lines that say why a build failed. Docker ends with the Dockerfile excerpt and a summary; the installer's
    own error (an unsatisfiable lock, a missing system library) comes before them and was being cut off."""
    lines = stderr.strip().splitlines()
    cut = next((i for i, ln in enumerate(lines) if ln.startswith("Dockerfile:")), len(lines))
    # Plain progress prefixes each line with its step and time ("#8 1.234 "); the text after it is the tool's own.
    cause = [re.sub(r"^#\d+ (\d+\.\d+ )?", "", ln) for ln in lines[:cut] if ln.strip()]
    cause = [ln for ln in cause if not ln.startswith(("DONE", "CACHED", "[", "sha256:", "naming to", "writing image"))]
    signal = [ln for ln in cause if any(w in ln.lower() for w in ("error", "err!", "failed", "not found", "cannot"))]
    picked = (signal or cause)[-keep:]
    return "\n".join([*picked, *lines[-2:]])


NEEDS_COMPILER = re.compile(
    r"No such file or directory: '(gcc|cc|g\+\+)'|command '(gcc|cc)' failed|unable to execute 'gcc'"
)
SYSTEM_REGISTRIES = ["deb.debian.org"]
MISSING_HEADER = re.compile(r"(?:fatal error: |provides `)(?P<header>[\w/.+-]+\.h)")
MISSING_TOOL = re.compile(
    r"(?P<tool>pg_config|mysql_config|xslt-config|xml2-config) executable not found|"
    r"(?P<tool2>pg_config|mysql_config): not found"
)
# The Debian package that provides a header (or config tool) Python packages commonly build against.
HEADER_PACKAGES = {
    "lber.h": "libldap2-dev",
    "ldap.h": "libldap2-dev",
    "sasl/sasl.h": "libsasl2-dev",
    "sasl.h": "libsasl2-dev",
    "libpq-fe.h": "libpq-dev",
    "pg_config": "libpq-dev",
    "mysql.h": "default-libmysqlclient-dev",
    "mysql_config": "default-libmysqlclient-dev",
    "ffi.h": "libffi-dev",
    "openssl/ssl.h": "libssl-dev",
    "libxml/xmlversion.h": "libxml2-dev",
    "xml2-config": "libxml2-dev",
    "libxslt/xsltconfig.h": "libxslt1-dev",
    "xslt-config": "libxslt1-dev",
    "jpeglib.h": "libjpeg-dev",
    "zlib.h": "zlib1g-dev",
    "krb5.h": "libkrb5-dev",
    "gssapi/gssapi.h": "libkrb5-dev",
    "yaml.h": "libyaml-dev",
    "sqlite3.h": "libsqlite3-dev",
    "bzlib.h": "libbz2-dev",
    "lzma.h": "liblzma-dev",
    "Python.h": "python3-dev",
}
MAX_SYSTEM_RETRIES = 4


def system_tools_allowed(policy: PolicyEngine) -> bool:
    """Whether the mandate allows system packages (a compiler, C headers) from Debian's archive."""
    from unbidden.contracts.guardian import ActionRequest

    request = ActionRequest(
        capability="sandbox.provision", purpose="system build tools", destinations=SYSTEM_REGISTRIES
    )
    return policy.evaluate(request).allowed


def missing_packages(error: str) -> list[str]:
    """Debian packages for the headers and config tools a failed build names, as far as they are known."""
    names = [m.group("header") for m in MISSING_HEADER.finditer(error)]
    names += [m.group("tool") or m.group("tool2") for m in MISSING_TOOL.finditer(error)]
    return sorted({HEADER_PACKAGES[n] for n in names if n in HEADER_PACKAGES})


def provision(
    repo: Path,
    rev: str,
    stack: NodeStack | PythonStack,
    *,
    docker: str = "docker",
    system_build_tools: bool = False,
) -> DependencyImage:
    """Build (or reuse) the dependency image. `system_build_tools` (the mandate allows Debian's archive) lets a Python
    install that needs a C compiler retry with one, then with the Debian packages of the C headers the build names
    (`lber.h` is `libldap2-dev`); without it the failure says that is what is missing."""
    if isinstance(stack, NodeStack) and ".pnpmfile.cjs" in tracked_files(repo, rev):
        # pnpm runs that file (repository code) during the install, with network access: not done here.
        raise ProvisionError(
            "node dependencies were not installed: the lockfile depends on .pnpmfile.cjs, repository code that pnpm "
            "runs during install with network access; Unbidden does not run repository code outside the sandbox"
        )
    try:
        return _provision(repo, rev, stack, docker=docker, system_build_tools=False)
    except ProvisionError as exc:
        if isinstance(stack, PythonStack) and NEEDS_COMPILER.search(str(exc)):
            if not system_build_tools:
                raise ProvisionError(
                    f"{exc}\nA package is built from source and needs a C compiler; system packages come from "
                    f"{', '.join(SYSTEM_REGISTRIES)}, which the mandate's package registries do not list."
                ) from exc
            headers: tuple[str, ...] = ()
            for _ in range(MAX_SYSTEM_RETRIES):
                try:
                    return _provision(repo, rev, stack, docker=docker, system_build_tools=True, headers=headers)
                except ProvisionError as again:
                    more = [p for p in missing_packages(str(again)) if p not in headers]
                    if not more:
                        unknown = sorted({m.group("header") for m in MISSING_HEADER.finditer(str(again))})
                        if unknown:
                            raise ProvisionError(
                                f"{again}\nThe build needs C headers Unbidden does not know a Debian package for: "
                                f"{', '.join(unknown)}"
                            ) from again
                        raise
                    headers = (*headers, *more)
            raise ProvisionError(
                f"python dependencies still fail to build with build-essential and {', '.join(headers)} installed"
            ) from exc
        raise


def _provision(
    repo: Path,
    rev: str,
    stack: NodeStack | PythonStack,
    *,
    docker: str,
    system_build_tools: bool,
    headers: tuple[str, ...] = (),
) -> DependencyImage:
    language = "node" if isinstance(stack, NodeStack) else "python"
    build = Path(tempfile.mkdtemp(prefix="unbidden-build-"))
    try:
        digest = _copy_from_git(repo, rev, _manifests(repo, rev, stack), build)
        if isinstance(stack, PythonStack) and stack.manifest in ("setup.py", "poetry.lock"):
            generated = "\n".join(stack.requirements) + "\n"
            (build / "ctx").mkdir(parents=True, exist_ok=True)
            (build / "ctx" / "unbidden-requirements.txt").write_text(generated)
            digest = hashlib.sha256((digest + generated).encode()).hexdigest()[:16]
        dockerfile = (
            node_dockerfile(stack)
            if isinstance(stack, NodeStack)
            else python_dockerfile(stack, system_build_tools=system_build_tools, headers=headers)
        )
        tag = f"unbidden-deps-{language}:{hashlib.sha256((dockerfile + digest).encode()).hexdigest()[:16]}"
        exists = subprocess.run([docker, "image", "inspect", tag], capture_output=True, check=False).returncode == 0
        if not exists:
            (build / "Dockerfile").write_text(dockerfile)
            result = subprocess.run(
                [docker, "build", "--progress=plain", "-t", tag, str(build)], capture_output=True, text=True
            )
            if result.returncode != 0:
                raise ProvisionError(f"dependency image for {language} failed to build:\n{build_error(result.stderr)}")
    finally:
        shutil.rmtree(build, ignore_errors=True)
    if isinstance(stack, NodeStack):
        return DependencyImage(
            tag=tag,
            language="node",
            registries=NODE_REGISTRIES,
            env={
                "PATH": "/deps/node_modules/.bin:/usr/local/bin:/usr/bin:/bin",
                "COREPACK_HOME": "/opt/corepack",
                "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
                # node_modules is the image's, linked in: installed and verified when the image was built.
                "npm_config_verify_deps_before_run": "false",
            },
            links={"node_modules": "/deps/node_modules"},
            # A workspace package's node_modules holds relative links into the store and to sibling packages;
            # copied into /work (links only, cheap) they resolve against the snapshot's real sources.
            setup=tuple(
                f"mkdir -p /work/{p.path} && cp -a /deps/{p.path}/node_modules /work/{p.path}/ 2>/dev/null || true"
                for p in stack.packages
            ),
        )
    return DependencyImage(
        tag=tag,
        language="python",
        registries=PYTHON_REGISTRIES,
        env={
            "PATH": "/deps/.venv/bin:/opt/tools/bin:/usr/local/bin:/usr/bin:/bin",
            "VIRTUAL_ENV": "/deps/.venv",
            "PYTHONPATH": ":".join("/work" if r == "." else f"/work/{r}" for r in stack.source_roots),
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


NODE_HEAP_MB = 4096
NODE_MEMORY = "6g"
DEFAULT_MEMORY = "2g"


def sandbox_spec(
    image: DependencyImage,
    argv: list[str],
    *,
    cwd: str = ".",
    timeout_s: float = 600,
    public_env: dict[str, str] | None = None,
    network: str = "none",
) -> SandboxSpec:
    """The one way to run something against a dependency image: its setup, its environment, and for a workspace
    package, that package's directory with its own node_modules/.bin first on PATH."""
    env = dict(image.env)
    if image.language == "node":
        # Type checks of large monorepos exhaust Node's default heap; the container gets room for a larger one.
        env.setdefault("NODE_OPTIONS", f"--max-old-space-size={NODE_HEAP_MB}")
    workdir = "/work" if cwd in (".", "") else f"/work/{cwd}"
    if cwd not in (".", "") and "PATH" in env:
        env["PATH"] = f"{workdir}/node_modules/.bin:{env['PATH']}"
    return SandboxSpec(
        image=image.tag,
        argv=argv,
        env=env,
        setup=image.setup,
        workdir=workdir,
        timeout_s=timeout_s,
        public_env=public_env or {},
        network=network,
        memory=NODE_MEMORY if image.language == "node" else DEFAULT_MEMORY,
    )
