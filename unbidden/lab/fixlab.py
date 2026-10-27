"""FixLab: reproduce a finding at the base commit, produce a candidate, and judge it with the same checks.

Both sides run in fresh offline sandboxes: every tool the repository uses (a lint fix must not break types),
and the test suite three rounds per side. A candidate that silences a tool instead of fixing the cause is
quarantined before anything is measured.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.bridge.service import PrivacyBridge
from unbidden.contracts.common import EvidenceLevel, EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, TestSummary, Verdict
from unbidden.contracts.finding import AnalyzerReport, Finding
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.lab.evaluator import CRITERIA, evaluate_fix
from unbidden.lab.testsuite import TestPlan, run_suite, test_plan
from unbidden.observe.stack import Stack
from unbidden.sandbox.provision import DependencyImage, link_dependencies
from unbidden.sandbox.runner import SandboxRunner, SandboxSpec, discard, snapshot
from unbidden.sandbox.tools import TOOLS, Tool, tools_for
from unbidden.store import Store

ACTOR = "lab"
MAX_PROMPT_FILE_BYTES = 60_000
SUPPRESSION = re.compile(
    r"@ts-ignore|@ts-expect-error|@ts-nocheck|eslint-disable|biome-ignore|#\s*type:\s*ignore|#\s*noqa"
    r"|pyright:\s*ignore|#\s*pragma:\s*no\s*cover"
)
Progress = Callable[[str], None]


@dataclass
class Candidate:
    origin: str  # "tool" | "model"
    files: dict[str, str]
    patch: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.patch.encode()).hexdigest()


@dataclass
class LabResult:
    experiment: Experiment | None
    verdict: Verdict | None
    candidate: Candidate | None
    notes: list[str] = field(default_factory=list[str])


def unified_patch(base: Path, files: dict[str, str]) -> str:
    chunks: list[str] = []
    for path, new in sorted(files.items()):
        old_path = base / path
        old = old_path.read_text() if old_path.exists() else ""
        chunks.extend(
            difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), f"a/{path}", f"b/{path}")
        )
    return "".join(chunks)


def added_suppressions(patch: str) -> list[str]:
    return [
        line[1:].strip()
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++") and SUPPRESSION.search(line)
    ]


def _fingerprints(reports: list[AnalyzerReport]) -> list[str]:
    return [f.fingerprint for r in reports for f in r.findings]


class FixLab:
    def __init__(
        self,
        repo: Path,
        store: Store,
        brain: Brain | None,
        stack: Stack,
        images: dict[str, DependencyImage],
        *,
        runner: SandboxRunner | None = None,
        bridge: PrivacyBridge | None = None,
        bridge_first: bool = False,
        rounds: int = 3,
        repairs: int = 1,
        progress: Progress = lambda _: None,
    ) -> None:
        self.repo = repo
        self.store = store
        self.brain = brain
        self.stack = stack
        self.images = images
        self.runner = runner or SandboxRunner()
        self.bridge = bridge
        self.bridge_first = bridge_first
        self.rounds = rounds
        self.repairs = repairs
        self.progress = progress

    # Sandbox helpers -----------------------------------------------------------------------------------

    def _work(self, rev: str, image: DependencyImage, files: dict[str, str] | None = None) -> Path:
        work = snapshot(self.repo, rev)
        for path, content in (files or {}).items():
            target = work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        link_dependencies(work, image)
        return work

    def _run_tools(self, work: Path, tools: list[Tool], image: DependencyImage) -> list[AnalyzerReport]:
        reports: list[AnalyzerReport] = []
        for tool in tools:
            result = self.runner.run(SandboxSpec(image=image.tag, argv=list(tool.argv), env=image.env), work)
            reports.append(tool.report(result, list(tool.argv)))
        return reports

    # Candidates ----------------------------------------------------------------------------------------

    def _tool_candidate(self, rev: str, tool: Tool, image: DependencyImage, paths: list[str]) -> Candidate | None:
        if tool.fix_argv is None:
            return None
        work = self._work(rev, image)
        base = snapshot(self.repo, rev)
        try:
            self.runner.run(SandboxSpec(image=image.tag, argv=list(tool.fix_argv), env=image.env), work)
            files = {
                p: (work / p).read_text()
                for p in paths
                if (work / p).exists() and (work / p).read_text() != (base / p).read_text()
            }
            if not files:
                return None
            return Candidate("tool", files, unified_patch(base, files))
        finally:
            discard(work)
            discard(base)

    async def _model_candidate(
        self, opp: Opportunity, rev: str, findings: list[Finding], feedback: str | None
    ) -> Candidate | None:
        if self.brain is None:
            return None
        base = snapshot(self.repo, rev)
        try:
            paths = sorted({f.path for f in findings})
            blocks: list[str] = []
            size = 0
            for path in paths:
                text = (base / path).read_text(errors="replace")
                size += len(text)
                if size > MAX_PROMPT_FILE_BYTES:
                    return None
                blocks.append(f"`{path}`:\n```\n{text}```")
            language = "Python" if paths[0].endswith(".py") else "TypeScript/JavaScript"
            prompt = load_prompt("fix_findings")
            content = prompt.render(
                language=language,
                suppressions="`# type: ignore`, `# noqa`" if language == "Python" else "`@ts-ignore`, `eslint-disable`",
                comment="#" if language == "Python" else "//",
                tool=opp.source,
                findings="\n".join(f"- {f.path}:{f.line or '?'} {f.rule}: {f.message}" for f in findings[:50]),
                files="\n\n".join(blocks),
            )
            messages = [Message(role="user", content=content)]
            if feedback:
                messages.append(Message(role="user", content=f"A previous attempt failed: {feedback}. Try again."))
            response = await self.brain.complete(
                LLMRequest(
                    purpose="lab.fix_candidate",
                    tier=Tier.LOCAL,
                    messages=messages,
                    max_tokens=min(8000, 1000 + size // 2),
                    prompt_sha256=prompt.sha256,
                    correlation_id=opp.id,
                )
            )
            try:
                files = parse_files(response.content)
            except CodeBlockError:
                return None
            files = {p: c for p, c in files.items() if p in paths}
            if not files:
                return None
            return Candidate("model", files, unified_patch(base, files))
        finally:
            discard(base)

    async def _bridge_candidate(
        self, opp: Opportunity, rev: str, findings: list[Finding]
    ) -> tuple[Candidate | None, list[str]]:
        if self.bridge is None:
            return None, []
        base = snapshot(self.repo, rev)
        try:
            result = await self.bridge.solve(base, findings, correlation_id=opp.id)
            if result.files is None:
                return None, [f"bridge: {n}" for n in result.notes]
            return Candidate("bridge", result.files, unified_patch(base, result.files)), [
                f"bridge: {n}" for n in result.notes
            ]
        finally:
            discard(base)

    # The experiment ------------------------------------------------------------------------------------

    async def run(self, opp: Opportunity) -> LabResult:
        tool = TOOLS[opp.source]
        image = self.images[tool.language]
        rev: str = opp.details["rev"]
        siblings = [t for t in tools_for(self.stack) if t.language == tool.language]
        targeted: list[str] = list(opp.details["fingerprints"])
        findings = [Finding.model_validate(f) for f in opp.details["findings"]]
        paths: list[str] = list(opp.details["paths"])
        suite = test_plan(self.repo, rev, self.stack, tool.language)
        result = LabResult(None, None, None)

        self.progress(f"reproducing {opp.title}")
        base_work = self._work(rev, image)
        try:
            before = self._run_tools(base_work, siblings, image)
            incomplete = [r.tool for r in before if not r.can_resolve]
            if incomplete:
                result.notes.append(f"cannot judge: incomplete reports from {', '.join(incomplete)}")
                return result
            present = set(_fingerprints([r for r in before if r.tool == tool.name]))
            if not set(targeted) <= present:
                result.notes.append("the targeted findings no longer reproduce at this commit")
                return result
            baseline_tests = None
            if suite is not None:
                self.progress("running the test suite on the base")
                baseline_tests = run_suite(self.runner, base_work, image, suite, rounds=self.rounds)
        finally:
            discard(base_work)
        if opp.evidence_level < EvidenceLevel.REPRODUCTION:
            opp.evidence_level = EvidenceLevel.REPRODUCTION

        feedback: str | None = None
        attempts = self.repairs + 1 if self.bridge_first else 0
        bridged = False
        candidate = self._tool_candidate(rev, tool, image, paths)
        while True:
            if candidate is None and attempts > self.repairs and not bridged and self.bridge is not None:
                # The local model could not prove a fix: ask Muse Spark, through the privacy bridge.
                bridged = True
                self.progress("asking Muse Spark through the privacy bridge")
                candidate, notes = await self._bridge_candidate(opp, rev, findings)
                result.notes.extend(notes)
                if candidate is None:
                    break
            if candidate is None:
                if attempts > self.repairs:
                    break
                attempts += 1
                self.progress("asking the local model for a candidate")
                try:
                    candidate = await self._model_candidate(opp, rev, findings, feedback)
                except (BrainError, ProviderError) as exc:
                    result.notes.append(f"model: {exc}")
                    break
                if candidate is None:
                    feedback = "the answer had no usable `file:` blocks for the listed files"
                    continue
            suppressions = added_suppressions(candidate.patch)
            if suppressions:
                result.notes.append(f"{candidate.origin} candidate quarantined: adds {suppressions[0]!r}")
                feedback = "you added a suppression comment instead of fixing the cause"
                candidate = None
                continue
            judged = await self._measure(opp, rev, candidate, image, siblings, before, targeted, suite, baseline_tests)
            result.experiment, result.verdict, result.candidate = judged
            if judged[1].improved:
                break
            feedback = "; ".join(judged[1].reasons)
            result.notes.append(f"{candidate.origin} candidate rejected: {feedback}")
            candidate = None

        self._finish(opp, result)
        return result

    async def _measure(
        self,
        opp: Opportunity,
        rev: str,
        candidate: Candidate,
        image: DependencyImage,
        siblings: list[Tool],
        before: list[AnalyzerReport],
        targeted: list[str],
        suite: TestPlan | None,
        baseline_tests: TestSummary | None,
    ) -> tuple[Experiment, Verdict, Candidate]:
        experiment = Experiment(
            opportunity_id=opp.id, base_sha=rev, candidate_patch_sha256=candidate.sha256, rounds=self.rounds,
            baseline_tests=baseline_tests, findings_before=_fingerprints(before),
        )  # fmt: skip
        self.store.append_event(
            Event(type=EventType.EXPERIMENT_STARTED, actor=ACTOR, entity_id=experiment.id, correlation_id=opp.id,
                  payload={"origin": candidate.origin, "files": sorted(candidate.files),
                           "patch_sha256": candidate.sha256})
        )  # fmt: skip
        self.progress(f"measuring the {candidate.origin} candidate")
        work = self._work(rev, image, candidate.files)
        try:
            after = self._run_tools(work, siblings, image)
            candidate_tests = None
            if suite is not None:
                self.progress("running the test suite on the candidate")
                candidate_tests = run_suite(self.runner, work, image, suite, rounds=self.rounds)
        finally:
            discard(work)
        experiment.findings_after = _fingerprints(after)
        experiment.candidate_tests = candidate_tests
        incomplete = [r.tool for r in after if not r.can_resolve]
        judgement = evaluate_fix(
            targeted=targeted, before=experiment.findings_before, after=experiment.findings_after,
            baseline_tests=baseline_tests, candidate_tests=candidate_tests, has_test_suite=suite is not None,
        )  # fmt: skip
        reasons = list(judgement.reasons)
        improved = judgement.improved
        if incomplete:
            improved = False
            reasons.append(f"incomplete reports on the candidate from {', '.join(incomplete)}")
        verdict = Verdict(
            experiment_id=experiment.id,
            improved=improved,
            evidence_level=judgement.evidence_level if improved else EvidenceLevel.REPRODUCTION,
            criteria=CRITERIA,
            tests=judgement.tests,
            reasons=reasons or ["all targeted findings are gone, none appeared, no test regressed"],
            caveats=judgement.caveats,
        )
        self.store.put("experiments", experiment)
        artifacts = self.store.path.parent / "artifacts" if self.store.path else None
        if artifacts is not None:
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / f"{experiment.id}.patch").write_text(candidate.patch)
        self.store.append_event(
            Event(type=EventType.VERDICT_RECORDED, actor=ACTOR, entity_id=experiment.id, correlation_id=opp.id,
                  payload={"improved": improved, "level": int(verdict.evidence_level), "tests": verdict.tests.value,
                           "reasons": verdict.reasons, "caveats": verdict.caveats, "origin": candidate.origin})
        )  # fmt: skip
        return experiment, verdict, candidate

    def _finish(self, opp: Opportunity, result: LabResult) -> None:
        if result.verdict is not None and result.verdict.improved:
            opp.evidence_level = max(opp.evidence_level, result.verdict.evidence_level)
            opp.status = OpportunityStatus.EXPERIMENTING
            opp.details = {
                **opp.details,
                "experiment_id": result.experiment.id if result.experiment else None,
                "verdict": result.verdict.model_dump(mode="json"),
                "candidate": {"origin": result.candidate.origin if result.candidate else None,
                              "files": result.candidate.files if result.candidate else {}},
            }  # fmt: skip
            if result.experiment is not None:
                opp.evidence = [*opp.evidence, EvidenceRef(kind="experiment", locator=result.experiment.id)]
        else:
            opp.details = {**opp.details, "lab_notes": result.notes}
        opp.updated_at = utc_now()
        self.store.put("opportunities", opp)
