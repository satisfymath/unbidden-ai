"""Build a dependency-only image per lockfile, the one step that may reach a package registry.

The build context holds only manifests and lockfiles copied from git, never repository code or local files,
and install scripts are disabled where the package manager allows it. Network access during the build is
authorised by the mandate's registry allowlist; it is a policy check, not a firewall, and is reported so.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

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
    notes: tuple[str, ...] = ()  # what the install had to do differently from the repository's own instructions


class ProvisionError(RuntimeError):
    pass


class ProvisionDenied(ProvisionError):
    """The mandate does not allow this install."""


def static_version(data: bytes) -> bytes:
    """`static_metadata` for the version alone (no file can be read)."""
    return static_metadata(data, lambda _: None)


def static_metadata(data: bytes, read: Callable[[str], str | None]) -> bytes:
    """The build context's copy of a pyproject.toml whose metadata is computed, made static: installing the
    dependencies needs the project's metadata, and the context holds no code to compute it from.

    - A computed version (from the package's code, a file or git) becomes "0.0.0": the dependencies do not depend on it.
    - Dependencies setuptools reads from requirement files (`[tool.setuptools.dynamic] dependencies = {file = [...]}`)
      are written in, read from those files in git. A file with options (`-r`, `-e`, `--index-url`) is left alone.

    The repository is never changed; if an edit does not read back as intended, the original is kept."""
    try:
        text = data.decode()
        pyproject = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return data
    project = pyproject.get("project", {})
    dynamic = list(project.get("dynamic", []))
    static: dict[str, object] = {}
    if "version" in dynamic:
        static["version"] = "0.0.0"
    declared = pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("dependencies", {})
    if "dependencies" in dynamic and isinstance(declared, dict) and declared.get("file"):
        names = declared["file"] if isinstance(declared["file"], list) else [declared["file"]]
        requirements: list[str] | None = []
        for name in names:
            content = read(str(name))
            lines = [ln.split("#", 1)[0].strip() for ln in (content or "").splitlines()]
            if content is None or any(ln.startswith("-") for ln in lines):
                requirements = None
                break
            requirements += [ln for ln in lines if ln]
        if requirements is not None:
            static["dependencies"] = requirements
    if not static:
        return data
    header = re.search(r"^\[project\][ \t]*$", text, re.MULTILINE)
    if header is None:
        return data
    end = re.search(r"^\[", text[header.end() :], re.MULTILINE)
    table_end = header.end() + (end.start() if end else len(text) - header.end())
    pattern = "|".join(re.escape(k) for k in static)
    table = re.sub(
        r"^(dynamic\s*=\s*\[)(.*?)(\])",
        lambda m: m.group(1) + re.sub(rf"[\"']({pattern})[\"']\s*,?\s*", "", m.group(2)) + m.group(3),
        text[header.end() : table_end],
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    added = "".join(f"\n{key} = {json.dumps(value)}" for key, value in static.items())
    edited = text[: header.end()] + added + table + text[table_end:]
    try:
        checked = tomllib.loads(edited).get("project", {})
    except tomllib.TOMLDecodeError:
        return data
    if any(checked.get(k) != v or k in checked.get("dynamic", []) for k, v in static.items()):
        return data
    return edited.encode()


def _copy_from_git(repo: Path, rev: str, paths: list[str], dest: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        data = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, check=True).stdout
        if path.endswith("pyproject.toml"):
            base = path.removesuffix("pyproject.toml")

            def read(name: str, base: str = base) -> str | None:
                shown = subprocess.run(
                    ["git", "-C", str(repo), "show", f"{rev}:{base}{name}"], capture_output=True, text=True, check=False
                )
                return shown.stdout if shown.returncode == 0 else None

            data = static_metadata(data, read)
        target = dest / "ctx" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest.update(path.encode() + b"\0" + data)
    return digest.hexdigest()[:16]


def node_dockerfile(stack: NodeStack) -> str:
    install = {
        "npm": "npm ci --ignore-scripts --no-audit --no-fund",
        "pnpm": f"corepack enable && corepack prepare pnpm@{stack.manager_version or '9'} --activate "
        "&& pnpm install --frozen-lockfile --ignore-scripts",
        # bun's binary comes from its official image (below); the project's lifecycle scripts are not run either.
        "bun": "bun install --frozen-lockfile --ignore-scripts",
        # Yarn classic, from npm's registry through corepack, at the declared version when there is one.
        "yarn": f"corepack enable && corepack prepare yarn@{stack.manager_version or '1.22.22'} --activate "
        "&& yarn install --frozen-lockfile --ignore-scripts --non-interactive",
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
    bun = f"FROM oven/bun:{stack.manager_version or 'latest'} AS bun\n" if stack.manager == "bun" else ""
    copy_bun = "COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun\n" if stack.manager == "bun" else ""
    return f"""{bun}FROM node:{stack.major}-slim
{copy_bun}ENV CI=1 COREPACK_ENABLE_DOWNLOAD_PROMPT=0 COREPACK_HOME=/opt/corepack
WORKDIR /deps
COPY ctx/ /deps/
RUN {install}{generate} \\
 && mkdir -p /opt/corepack && chmod -R a+rX /opt/corepack
"""


LOCK_STALE = "/deps/UNBIDDEN_LOCK_STALE"


def _uv_sync(stack: PythonStack, scope: str) -> str:
    """One `uv sync` for the project's groups, minus those that need another Python and the packages installed from a
    directory of the repository (their code is not in the build context; tests import them from the snapshot)."""
    flags = "".join(f" --no-install-package {name}" for name, _ in stack.path_sources)
    if stack.sync_flags is not None:  # what the CI installs, as it installs it
        groups = "".join(f" {f}" for f in stack.sync_flags)
        return f"uv sync {scope}{groups}{flags} --project /deps"
    flags = "".join(f" --no-group {g}" for g in stack.skip_groups) + flags
    return f"uv sync {scope} --all-groups{flags} --project /deps"


def seeded(stack: PythonStack) -> bool:
    """Before Python 3.12, a virtual environment always carried setuptools (`pkg_resources`), and projects of that
    time import it without declaring it; uv's environments omit it unless seeded. Seeded the way that era did."""
    return stack.manifest in ("setup.py", "poetry.lock", "requirements.txt") and int(stack.version.split(".")[1]) < 12


def _seed(stack: PythonStack) -> str:
    """pip and setuptools as they were when the project's lockfile was committed (uv's `--exclude-newer`): today's
    setuptools has no `pkg_resources` (81) or warns on importing it (67.3), which an old suite may treat as an error.
    Without a date, the newest setuptools that still ships `pkg_resources`."""
    if not seeded(stack):
        return ""
    era = f" --exclude-newer {stack.lock_date}" if stack.lock_date else ""
    tools = "setuptools pip" if stack.lock_date else '"setuptools<81" pip'
    return f" && uv pip install --python /deps/.venv/bin/python{era} {tools}"


def _own(stack: PythonStack) -> str:
    """The project itself, installed the way `uv sync` installs it, editable: its metadata in the environment and its
    source (the run's snapshot, at /work) on the path. Its code is not in the image; the metadata is enough for
    `importlib.metadata.version(...)` and entry points that the project reads at import."""
    if stack.own is None:
        return ""
    name, version = stack.own
    dist = re.sub(r"[-_.]+", "_", name)
    if not re.fullmatch(r"\w+", dist) or not re.fullmatch(r"[\w.+!-]+", version):
        return ""
    info = f'"$SP/{dist}-{version}.dist-info"'
    roots = "\\n".join(f"/work/{r}".rstrip("/.") or "/work" for r in stack.source_roots)
    return (
        " && SP=$(/deps/.venv/bin/python -c \"import sysconfig; print(sysconfig.get_paths()['purelib'])\")"
        f" && mkdir -p {info}"
        f" && printf 'Metadata-Version: 2.1\\nName: {name}\\nVersion: {version}\\n' > {info}/METADATA"
        f" && echo unbidden > {info}/INSTALLER && printf '{roots}\\n' > \"$SP/_unbidden_{dist}.pth\""
    )


def python_dockerfile(stack: PythonStack, *, system_build_tools: bool = False, headers: tuple[str, ...] = ()) -> str:
    if stack.lockfile == "uv.lock":
        scope = "--no-install-workspace --all-packages" if stack.members else "--no-install-project"
        # The lockfile first, as the team installs; one out of date with pyproject.toml is resolved again, and that is
        # recorded in the image so the run can say so.
        install = f"({_uv_sync(stack, '--frozen ' + scope)} || (touch {LOCK_STALE} && {_uv_sync(stack, scope)}))"
    elif stack.manifest in ("setup.py", "poetry.lock"):
        # The requirements were read statically (setup.py's install_requires, poetry.lock's pins) and written
        # into the build context.
        install = (
            f"uv venv /deps/.venv{_seed(stack)} && uv pip install --python /deps/.venv/bin/python "
            "-r /deps/unbidden-requirements.txt"
        )
    elif stack.manifest == "requirements.txt":
        install = (
            f"uv venv /deps/.venv{_seed(stack)} && uv pip install --python /deps/.venv/bin/python "
            "-r /deps/requirements.txt"
        )
    else:
        install = _uv_sync(stack, "--no-install-project")
    uv = (
        f"uv{stack.uv_version if stack.uv_version[0] in '=<>!~' else '==' + stack.uv_version}"
        if stack.uv_version
        else "uv"
    )
    build_tools = (
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        + " ".join(("build-essential", *headers))
        + " && rm -rf /var/lib/apt/lists/*\n"
        if system_build_tools
        else ""
    )
    return f"""{_own_build(stack, uv)}FROM node:22-slim AS node
FROM python:{stack.version}-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \\
 && npm install -g pyright@{PYRIGHT_VERSION} \\
 && pip install --no-cache-dir "{uv}" \\
 && uv venv /opt/tools \\
 && (uv pip install --python /opt/tools/bin/python ruff=={RUFF_VERSION} pytest=={PYTEST_VERSION} \\
     || uv pip install --python /opt/tools/bin/python ruff=={RUFF_VERSION} pytest)
{build_tools}ENV UV_PROJECT_ENVIRONMENT=/deps/.venv UV_LINK_MODE=copy
# The interpreter is the one Unbidden chose and records: uv may neither pick another nor download one.
ENV UV_PYTHON=/usr/local/bin/python{stack.version} UV_PYTHON_DOWNLOADS=never
# Projects that take their version from git (setuptools-scm, hatch-vcs) cannot read it here: only manifests are
# copied, never .git. Their dependencies do not depend on the version.
ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
WORKDIR /deps
COPY ctx/ /deps/
RUN {install}{_own(stack)} \\
 && (/deps/.venv/bin/python -c "import pytest" 2>/dev/null \\
     || uv pip install --python /deps/.venv/bin/python pytest=={PYTEST_VERSION} \\
     || uv pip install --python /deps/.venv/bin/python pytest) \\
 && (/deps/.venv/bin/python -c "import hypothesis" 2>/dev/null \\
     || uv pip install --python /deps/.venv/bin/python hypothesis=={HYPOTHESIS_VERSION} \\
     || uv pip install --python /deps/.venv/bin/python hypothesis)
{"COPY --from=own /generated/ /deps/generated/" + chr(10) if stack.build_writes else ""}"""


OWN_TREE = "own"  # the repository at the commit, in the build context, only when its build writes files


def _own_build(stack: PythonStack, uv: str) -> str:
    """A stage that builds the project's wheel, as `uv sync` builds it, and keeps only the files its build writes into
    the source tree (a version or build-info module the code imports). A build that fails leaves them absent, as
    before, and the checks say what the import then raised."""
    if not stack.build_writes:
        return ""
    # The full image, not slim: it has git, which version plugins call even where there is no repository (Prefect's
    # versioningit), and nothing need be installed from the distribution's registry.
    return f"""FROM python:{stack.version} AS own
ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
COPY {OWN_TREE}/ /src/
COPY {OWN_EXTRACT} /{OWN_EXTRACT}
RUN pip install --no-cache-dir "{uv}" \\
 && (uv build --wheel --out-dir /wheel /src || true) \\
 && python /{OWN_EXTRACT}
"""


OWN_EXTRACT = "unbidden-own-extract.py"


def own_extract_script(stack: PythonStack) -> str:
    """Copies each file the build writes out of the built wheel to /generated, at its path in the repository: inside
    the wheel it sits under the package, without the source root (src/prefect/_build_info.py is prefect/...)."""
    inside = {p: [p.removeprefix(f"{r.rstrip('/')}/") for r in stack.source_roots if r not in (".", "")] + [p]
              for p in stack.build_writes}  # fmt: skip
    return f"""import glob, os, zipfile
os.makedirs("/generated", exist_ok=True)
wheels = glob.glob("/wheel/*.whl")
z = zipfile.ZipFile(wheels[0]) if wheels else None
names = set(z.namelist()) if z else set()
for path, candidates in {inside!r}.items():
    hit = next((n for n in candidates if n in names), None)
    if z and hit:
        os.makedirs(os.path.dirname(os.path.join("/generated", path)), exist_ok=True)
        with open(os.path.join("/generated", path), "wb") as out:
            out.write(z.read(hit))
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
        wanted += [f for f in declared_patches(repo, rev) if f in files]
        # Packages vendored under node_modules are never tracked in sane repos; skip them if they are.
        return sorted({f for f in wanted if "node_modules/" not in f})
    if stack.manifest in ("setup.py", "poetry.lock"):
        return []
    wanted = [stack.manifest] + ([stack.lockfile] if stack.lockfile else [])
    wanted += [f"{m}/pyproject.toml" for m in stack.members]
    # Build backends read the documents a manifest declares (hatchling refuses a missing `readme`) even when only the
    # metadata is built. Documents, never code.
    wanted += [f"{d}/{name}" for _, d in stack.path_sources for name in ("pyproject.toml", "setup.cfg")
               if f"{d}/{name}" in files]  # fmt: skip
    for directory in ["", *(f"{m}/" for m in stack.members), *(f"{d}/" for _, d in stack.path_sources)]:
        wanted += [f for f in files if f.startswith(directory) and METADATA_DOC.match(f.removeprefix(directory))]
    return sorted(set(wanted))


METADATA_DOC = re.compile(r"^(README|LICEN[CS]E|COPYING|NOTICE|AUTHORS|CHANGELOG|CHANGES)[\w.-]*$", re.IGNORECASE)


def declared_patches(repo: Path, rev: str) -> list[str]:
    """Patch files a package manager applies to dependencies (`patchedDependencies` in package.json, at the top level
    or under `pnpm`, and in pnpm-workspace.yaml): diffs of third-party packages, needed to install, not the project's
    code."""
    found: list[str] = []
    for path in ("package.json", "pnpm-workspace.yaml"):
        shown = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True)
        if shown.returncode != 0:
            continue
        try:
            data = json.loads(shown.stdout) if path.endswith(".json") else yaml.safe_load(shown.stdout)
        except (ValueError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        for table in (data.get("patchedDependencies"), (data.get("pnpm") or {}).get("patchedDependencies")):
            if isinstance(table, dict):
                found += [str(v) for v in table.values() if isinstance(v, str) and ".." not in v]
    return found


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
    # The installer's first error and the lines that explain it (uv's "Because ... depends on ...", hints, npm's code
    # and reason): without them a failure says what happened but not why.
    first = next((i for i, ln in enumerate(cause) if re.match(r"\s*(error|npm error|ERR!)", ln, re.I)), None)
    explained = [ln for ln in cause[first : first + keep]] if first is not None else []
    return "\n".join(dict.fromkeys([*explained, *picked, *lines[-2:]]))


def needs_system_build(error: str) -> bool:
    """A package built from source that needs something from the system: a C compiler, a config tool (pg_config),
    or C headers. Each is what the retry with build tools can provide."""
    return bool(NEEDS_COMPILER.search(error) or MISSING_TOOL.search(error) or MISSING_HEADER.search(error))


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
    stack: Any,
    *,
    policy: PolicyEngine,
    docker: str = "docker",
) -> DependencyImage:
    """Build (or reuse) the dependency image, once the mandate allows installing from the language's registries:
    every path that provisions (scans, subprojects, the lab's images) passes here, so none can skip that check.

    When the mandate also allows Debian's archive, a Python install that needs a C compiler retries with one, then
    with the Debian packages of the C headers the build names (`lber.h` is `libldap2-dev`); without it the failure
    says that is what is missing."""
    from unbidden.contracts.guardian import ActionRequest
    from unbidden.languages import adapter_of

    lang = adapter_of(stack)
    request = ActionRequest(
        capability="sandbox.provision", purpose=f"install {lang.name} dependencies", destinations=list(lang.registries)
    )
    verdict = policy.evaluate(request)
    if not verdict.allowed:
        raise ProvisionDenied(f"sandbox.provision: {'; '.join(verdict.reasons)}")
    system_build_tools = system_tools_allowed(policy)
    if isinstance(stack, NodeStack) and ".pnpmfile.cjs" in tracked_files(repo, rev):
        # pnpm runs that file (repository code) during the install, with network access: not done here.
        raise ProvisionError(
            "node dependencies were not installed: the lockfile depends on .pnpmfile.cjs, repository code that pnpm "
            "runs during install with network access; Unbidden does not run repository code outside the sandbox"
        )
    try:
        return _provision(repo, rev, stack, docker=docker, system_build_tools=False)
    except ProvisionError as exc:
        if isinstance(stack, PythonStack) and needs_system_build(str(exc)):
            if not system_build_tools:
                raise ProvisionError(
                    f"{exc}\nA package is built from source and needs a C compiler; system packages come from "
                    f"{', '.join(SYSTEM_REGISTRIES)}, which the mandate's package registries do not list."
                ) from exc
            headers: tuple[str, ...] = ()
            for _ in range(MAX_SYSTEM_RETRIES):
                try:
                    built = _provision(repo, rev, stack, docker=docker, system_build_tools=True, headers=headers)
                    if not isinstance(built, DependencyImage):
                        return built
                    from dataclasses import replace

                    why = "build-essential" + (f", {', '.join(headers)}" if headers else "")
                    note = f"a package is built from source: system build tools installed from Debian ({why})"
                    return replace(built, notes=(*built.notes, note))
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
    stack: Any,
    *,
    docker: str,
    system_build_tools: bool,
    headers: tuple[str, ...] = (),
) -> DependencyImage:
    from unbidden.languages import adapter_of

    lang = adapter_of(stack)
    language = lang.name
    build = Path(tempfile.mkdtemp(prefix="unbidden-build-"))
    try:
        digest = _copy_from_git(repo, rev, lang.manifests(repo, rev, stack), build)
        for name, generated in sorted(lang.generated(stack).items()):
            (build / "ctx").mkdir(parents=True, exist_ok=True)
            (build / "ctx" / name).write_text(generated)
            digest = hashlib.sha256((digest + generated).encode()).hexdigest()[:16]
        if getattr(stack, "build_writes", ()):
            own = build / OWN_TREE
            own.mkdir(parents=True)
            (build / OWN_EXTRACT).write_text(own_extract_script(stack))
            archive = subprocess.run(["git", "-C", str(repo), "archive", rev], capture_output=True, check=True).stdout
            subprocess.run(["tar", "-x", "-C", str(own)], input=archive, check=True)
            tree = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{rev}^{{tree}}"], capture_output=True,
                                  text=True, check=True).stdout.strip()  # fmt: skip
            digest = hashlib.sha256((digest + tree).encode()).hexdigest()[:16]
        dockerfile = lang.dockerfile(stack, system_build_tools=system_build_tools, headers=headers)
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
    return lang.image(tag, stack, docker)


def _python_notes(tag: str, stack: PythonStack, docker: str) -> tuple[str, ...]:
    # The environment, recorded so base and candidate can be shown to run under the same one: the interpreter and why,
    # the image's architecture, what was installed from the system.
    arch = subprocess.run([docker, "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", tag],
                          capture_output=True, text=True, check=False).stdout.strip()  # fmt: skip
    notes = [*stack.version_notes, f"image {tag} on {arch or 'an unknown platform'}"]
    if seeded(stack):
        notes.append(
            f"the environment is seeded with pip and setuptools as of {stack.lock_date or 'before setuptools 81'} "
            f"(the lockfile's era), as virtualenvs on Python {stack.version} were"
        )
    notes += [
        f"dependency group {g} needs another Python than {stack.version}; not installed" for g in stack.skip_groups
    ]
    notes += [f"{name} is installed from {path} in the repository; its code comes from the snapshot, not the image"
              for name, path in stack.path_sources]  # fmt: skip
    if stack.lockfile == "uv.lock":
        stale = subprocess.run([docker, "run", "--rm", "--network", "none", tag, "test", "-e", LOCK_STALE],
                               capture_output=True, check=False).returncode == 0  # fmt: skip
        if stale:
            notes.append("uv.lock is out of date with pyproject.toml: dependencies resolved at provisioning time")
    return tuple(notes)


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
    # Pyright runs on Node in a Python image too: on a large project (Prefect, stage 10) it ran out of Node's default
    # heap (about 1 GB) and its report was lost.
    node = image.language == "node" or any("pyright" in a for a in argv[:3])
    if node:
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
        memory=NODE_MEMORY if node else DEFAULT_MEMORY,
    )
