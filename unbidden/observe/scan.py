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
    SYSTEM_REGISTRIES,
    DependencyImage,
    ProvisionError,
    link_dependencies,
    provision,
    sandbox_spec,
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
            system = policy.evaluate(
                ActionRequest(
                    capability="sandbox.provision", purpose="system build tools", destinations=SYSTEM_REGISTRIES
                )
            ).allowed
            images[language] = provision(repo, rev, lang_stack, system_build_tools=system)
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
    store.set_value("last_scan", {"rev": rev, "tools": [r.tool for r in result.reports]})
    if not result.reports:
        store.append_event(
            Event(type=EventType.ANALYZER_RAN, actor="observer", payload={"rev": rev, "problems": result.problems})
        )
    return result
