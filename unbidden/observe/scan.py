"""One observation pass: detect the stack, provision dependencies, run the trusted tools, record findings."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.contracts.events import Event, EventType
from unbidden.contracts.finding import AnalyzerReport
from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.observe.analyzers import Sweep, record_report, run_tool
from unbidden.observe.stack import NodeStack, Stack, detect_stack
from unbidden.sandbox.provision import (
    DependencyImage,
    ProvisionError,
    link_dependencies,
    provision,
    sandbox_spec,
    system_tools_allowed,
)
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.sandbox.tools import tools_for
from unbidden.store import Store

Progress = Callable[[str], None]


@dataclass
class ScanResult:
    rev: str
    stack: Stack
    reports: list[AnalyzerReport] = field(default_factory=list[AnalyzerReport])
    sweeps: list[Sweep] = field(default_factory=list[Sweep])
    problems: list[str] = field(default_factory=list[str])


class ScanDenied(RuntimeError):
    pass


def _allow(policy: PolicyEngine, capability: str, purpose: str, destinations: list[str] | None = None) -> None:
    verdict = policy.evaluate(ActionRequest(capability=capability, purpose=purpose, destinations=destinations or []))
    if not verdict.allowed:
        raise ScanDenied(f"{capability}: {'; '.join(verdict.reasons)}")


GIT_HOOK_TOOLS = re.compile(r"^\s*(husky|husky install|simple-git-hooks|lefthook install|is-ci \|\| husky)\s*$")


def prepare_node(
    runner: SandboxRunner,
    repo: Path,
    rev: str,
    node: NodeStack,
    image: DependencyImage,
    problems: list[str],
    progress: Progress,
) -> Path | None:
    """Run the repository's root `postinstall` once, in the sandbox and without network, on a snapshot every Node
    analyzer then shares. Dependencies were installed with scripts off (that step has network); monorepos often
    build their own packages there (docusaurus: `pnpm build:packages`), and type checks of the packages that import
    them fail without it. Scripts that only install git hooks are skipped."""
    raw = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:package.json"], capture_output=True, text=True)
    scripts: dict[str, str] = json.loads(raw.stdout or "{}").get("scripts", {}) if raw.returncode == 0 else {}
    command = scripts.get("postinstall")
    if not command or GIT_HOOK_TOOLS.match(command):
        return None
    work = snapshot(repo, rev)
    link_dependencies(work, image)
    progress("running the repository's postinstall in the sandbox")
    # pnpm cannot verify a node_modules linked in from the image; the flag outranks the repository's own settings.
    argv = (
        ["pnpm", "--config.verify-deps-before-run=false", "run", "postinstall"]
        if node.manager == "pnpm"
        else [node.manager, "run", "postinstall"]
    )
    outcome = runner.run(sandbox_spec(image, argv, timeout_s=1800), work)
    if outcome.exit_code != 0:
        tail = (outcome.stderr or outcome.stdout).strip()[-600:]
        problems.append(
            f"the repository's postinstall ({command}) failed in the sandbox; analyzers run anyway:\n{tail}"
        )
    return work


MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml"}
LOCKS = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "requirements.txt", "uv.lock", "poetry.lock"}


def service_dirs(repo: Path, rev: str, stack: Stack) -> list[str]:
    """Directories a compose service is built from that carry their own manifest and lockfile, and that the root's
    stacks do not already cover (a workspace package, the root itself): the services of a polyglot repository."""
    from unbidden.observe.compose import load_compose
    from unbidden.observe.stack import tracked_files

    compose = load_compose(repo, rev)
    if compose is None:
        return []
    files = tracked_files(repo, rev)
    covered = {p.path for p in (stack.node.packages if stack.node else ())}
    found: list[str] = []
    for service in compose.services.values():
        context = (service.build_context or "").strip("./")
        if service.dockerfile and "/" in service.dockerfile:
            context = context or service.dockerfile.rsplit("/", 1)[0].strip("./")
        if not context or context in covered or context in found:
            continue
        own = {
            f.removeprefix(f"{context}/")
            for f in files
            if f.startswith(f"{context}/") and "/" not in f.removeprefix(f"{context}/")
        }
        if own & MANIFESTS and own & LOCKS:
            found.append(context)
    return sorted(found)


def _isolated(repo: Path, rev: str, directory: str) -> Path:
    """The service directory at `rev` as a repository of its own (its tracked files only), for a scan."""
    import tempfile

    target = Path(tempfile.mkdtemp(prefix="unbidden-service-"))
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", f"{rev}:{directory}"], capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
    git = ["git", "-C", str(target), "-c", "user.name=unbidden", "-c", "user.email=unbidden@localhost"]
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", f"{directory} at {rev[:12]}"], check=True)
    return target


def _scan_services(
    repo: Path,
    rev: str,
    store: Store,
    stack: Stack,
    runner: SandboxRunner,
    result: ScanResult,
    progress: Progress,
    system_tools: bool = False,
) -> None:
    """Each service of a polyglot repository, analyzed in isolation with the same trusted tools. Findings are
    recorded against the repository with their paths prefixed; the lab cannot yet run them inside the repository,
    and the Director knows it (their tool reads `tool@dir`)."""
    import shutil

    for directory in service_dirs(repo, rev, stack):
        sub = _isolated(repo, rev, directory)
        try:
            sub_stack = detect_stack(sub, "HEAD")
            images: dict[str, DependencyImage] = {}
            for language in sub_stack.languages:
                try:
                    progress(f"provisioning {language} dependencies of {directory}")
                    images[language] = provision(
                        sub, "HEAD", getattr(sub_stack, language), system_build_tools=system_tools
                    )
                except ProvisionError as exc:
                    result.problems.append(f"{directory}: {exc}")
            for tool in tools_for(sub_stack):
                image = images.get(tool.language)
                if image is None:
                    continue
                progress(f"running {tool.name} in {directory}")
                report = run_tool(runner, sub, "HEAD", tool, image)
                findings = [f.model_copy(update={"path": f"{directory}/{f.path}"}) for f in report.findings]
                report = report.model_copy(update={"tool": f"{report.tool}@{directory}", "findings": findings})
                result.reports.append(report)
                result.sweeps.append(record_report(store, report, rev))
            result.stack.blind_spots.extend(f"{directory}: {b}" for b in sub_stack.blind_spots)
        finally:
            shutil.rmtree(sub, ignore_errors=True)


def scan(
    repo: Path,
    rev: str,
    store: Store,
    mandate: Mandate,
    *,
    runner: SandboxRunner | None = None,
    progress: Progress = lambda _: None,
) -> ScanResult:
    policy = PolicyEngine(mandate)
    _allow(policy, "repo.read", "detect the stack")
    stack = detect_stack(repo, rev)
    result = ScanResult(rev=rev, stack=stack)
    runner = runner or SandboxRunner()
    images: dict[str, DependencyImage] = {}
    for language in stack.languages:
        lang_stack = getattr(stack, language)
        registries = ["registry.npmjs.org"] if language == "node" else ["pypi.org", "files.pythonhosted.org"]
        try:
            _allow(policy, "sandbox.provision", f"install {language} dependencies", registries)
            progress(f"provisioning {language} dependencies")
            images[language] = provision(repo, rev, lang_stack, system_build_tools=system_tools_allowed(policy))
        except (ScanDenied, ProvisionError) as exc:
            result.problems.append(str(exc))
    _allow(policy, "analyzer.run", "run the repository's own checks")
    prepared: dict[str, Path] = {}
    try:
        if stack.node is not None and "node" in images:
            work = prepare_node(runner, repo, rev, stack.node, images["node"], result.problems, progress)
            if work is not None:
                prepared["node"] = work
        for tool in tools_for(stack):
            image = images.get(tool.language)
            if image is None:
                continue
            progress(f"running {tool.name}")
            report = run_tool(runner, repo, rev, tool, image, prepared=prepared.get(tool.language))
            result.reports.append(report)
            result.sweeps.append(record_report(store, report, rev))
    finally:
        for work in prepared.values():
            discard(work)
    _scan_services(repo, rev, store, stack, runner, result, progress, system_tools_allowed(policy))
    store.set_value("last_scan", {"rev": rev, "tools": [r.tool for r in result.reports]})
    if not result.reports:
        store.append_event(
            Event(type=EventType.ANALYZER_RAN, actor="observer", payload={"rev": rev, "problems": result.problems})
        )
    return result
