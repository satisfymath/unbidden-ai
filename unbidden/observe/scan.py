"""One observation pass: detect the stack, provision dependencies, run the trusted tools, record findings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.contracts.events import Event, EventType
from unbidden.contracts.finding import AnalyzerReport
from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.observe.analyzers import Sweep, record_report, run_tool
from unbidden.observe.stack import Stack, detect_stack
from unbidden.sandbox.provision import DependencyImage, ProvisionError, provision
from unbidden.sandbox.runner import SandboxRunner
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
            images[language] = provision(repo, rev, lang_stack)
        except (ScanDenied, ProvisionError) as exc:
            result.problems.append(str(exc))
    _allow(policy, "analyzer.run", "run the repository's own checks")
    for tool in tools_for(stack):
        image = images.get(tool.language)
        if image is None:
            continue
        progress(f"running {tool.name}")
        report = run_tool(runner, repo, rev, tool, image)
        result.reports.append(report)
        result.sweeps.append(record_report(store, report, rev))
    store.set_value("last_scan", {"rev": rev, "tools": [r.tool for r in result.reports]})
    if not result.reports:
        store.append_event(
            Event(type=EventType.ANALYZER_RAN, actor="observer", payload={"rev": rev, "problems": result.problems})
        )
    return result
