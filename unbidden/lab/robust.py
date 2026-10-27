"""RobustLab: a crash found by a property test becomes a fix proven by that test and the repository's own suite.

The property test that found the crash is the check: it must fail at the base (reproduced) and pass with the
candidate. The suite runs three rounds per side and every check the repository uses runs on both sides. The test
travels with the proposal as a regression test.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.common import EvidenceLevel, EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, TestOutcome, Verdict
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.lab.evaluator import classify_tests
from unbidden.lab.fixlab import Candidate, added_suppressions, unified_patch
from unbidden.lab.testsuite import run_suite, test_plan
from unbidden.observe.stack import Stack
from unbidden.research.robustness import parse_crashes
from unbidden.sandbox.provision import DependencyImage, link_dependencies, sandbox_spec
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.store import Store

Progress = Callable[[str], None]
REGRESSION_FILE = "tests/test_unbidden_regression_{name}.py"


def single_test(source: str, name: str) -> str:
    """The probe file reduced to its imports and one test: the regression test that ships with the fix."""
    tree = ast.parse(source)
    test = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    used = {n.id for n in ast.walk(test) if isinstance(n, ast.Name)} | {
        n.value.id for n in ast.walk(test) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }
    keep: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a for a in node.names if (a.asname or a.name.split(".")[0]) in used]
            if names:
                node.names = names
                keep.append(node)
        elif not isinstance(node, ast.FunctionDef) or node.name == name:
            keep.append(node)
    return ast.unparse(ast.Module(body=keep, type_ignores=[])) + "\n"


@dataclass
class RobustResult:
    experiment: Experiment | None = None
    verdict: Verdict | None = None
    candidate: Candidate | None = None
    notes: list[str] = field(default_factory=list[str])


class RobustLab:
    def __init__(
        self,
        repo: Path,
        store: Store,
        brain: Brain,
        stack: Stack,
        image: DependencyImage,
        *,
        runner: SandboxRunner | None = None,
        progress: Progress = lambda _: None,
        attempts: int = 2,
    ) -> None:
        self.repo, self.store, self.brain, self.stack, self.image = repo, store, brain, stack, image
        self.runner = runner or SandboxRunner()
        self.progress, self.attempts = progress, attempts

    def _run_test(self, rev: str, files: dict[str, str], test_file: str) -> str:
        work = snapshot(self.repo, rev)
        try:
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, self.image)
            argv = [
                "python",
                "-m",
                "pytest",
                test_file,
                "-q",
                "-p",
                "no:cacheprovider",
                "--tb=long",
                "-o",
                "addopts=",
                "--hypothesis-seed=0",
            ]
            result = self.runner.run(sandbox_spec(self.image, argv, timeout_s=900), work)
            return result.stdout + result.stderr
        finally:
            discard(work)

    async def _candidate(self, opp: Opportunity, rev: str, test: str, feedback: str) -> Candidate | None:
        path = opp.details["paths"][0]
        base = snapshot(self.repo, rev)
        try:
            source = (base / path).read_text()
            prompt = load_prompt("robust_fix")
            content = prompt.render(
                test=test,
                failure=f"{opp.details['example']}\n{opp.details['excerpt'][-2000:]}",
                path=path,
                source=source,
            )
            messages = [Message(role="user", content=content, source="repo")]
            if feedback:
                messages.append(Message(role="user", content=f"A previous attempt failed: {feedback}", source="repo"))
            response = await self.brain.complete(
                LLMRequest(
                    purpose="lab.robust_fix",
                    expect_files=True,
                    tier=Tier.LOCAL,
                    messages=messages,
                    prompt_sha256=prompt.sha256,
                    max_tokens=min(12000, 1500 + len(source) // 2),
                    correlation_id=opp.id,
                )
            )
            files = {p: c for p, c in parse_files(response.content).items() if p == path}
            return Candidate(self.brain.author("lab.robust_fix"), files, unified_patch(base, files)) if files else None
        except (BrainError, ProviderError, CodeBlockError):
            return None
        finally:
            discard(base)

    async def run(self, opp: Opportunity) -> RobustResult:
        result = RobustResult()
        rev, package, name = opp.details["rev"], opp.details["package"], opp.details["test"]
        test = single_test(opp.details["tests_source"], name)
        test_file = REGRESSION_FILE.format(name=re.sub(r"\W", "_", name.removeprefix("test_")))
        self.progress("reproducing the crash at the base")
        before = parse_crashes(self._run_test(rev, {test_file: test}, test_file), package)
        if not any(c.frame == opp.details["frame"] for c in before):
            result.notes.append("the crash does not reproduce at this commit with the isolated test")
            return result
        plan = test_plan(self.repo, rev, self.stack, "python")
        feedback = ""
        for attempt in range(self.attempts):
            self.progress(f"asking the local model for a fix (attempt {attempt + 1})")
            candidate = await self._candidate(opp, rev, test, feedback)
            if candidate is None:
                feedback = "the answer had no usable file block"
                continue
            if added_suppressions(candidate.patch) or re.search(r"^\+\s*except\b", candidate.patch, re.MULTILINE):
                feedback = "you silenced the failure (a suppression or a new except) instead of fixing the cause"
                result.notes.append(f"attempt {attempt + 1} quarantined: it hides the exception")
                continue
            self.progress("running the property test on the candidate")
            output = self._run_test(rev, {**candidate.files, test_file: test}, test_file)
            if " passed" not in output or " failed" in output:
                tail = "\n".join(output.strip().splitlines()[-15:])
                feedback = f"with your change the test still fails:\n{tail}"
                result.notes.append(f"attempt {attempt + 1}: the property test still fails")
                continue
            sides = []
            if plan is not None:
                self.progress("running the repository's suite, 3 rounds per side")
                for files in ({}, candidate.files):
                    work = snapshot(self.repo, rev)
                    for path, content in files.items():
                        (work / path).write_text(content)
                    link_dependencies(work, self.image)
                    sides.append(run_suite(self.runner, work, self.image, plan, rounds=3))
                    discard(work)
            tests, notes = classify_tests(sides[0], sides[1]) if sides else (TestOutcome.INCONCLUSIVE, [])
            improved = tests is not TestOutcome.REGRESSION
            level = EvidenceLevel.FUNCTIONAL_VALIDATION if improved and sides else EvidenceLevel.LAB_IMPROVEMENT
            files = {**candidate.files, test_file: test}
            candidate = Candidate(
                candidate.origin, files, candidate.patch + unified_patch(snapshot(self.repo, rev), {test_file: test})
            )
            experiment = Experiment(
                opportunity_id=opp.id,
                base_sha=rev,
                candidate_patch_sha256=candidate.sha256,
                rounds=3,
                baseline_tests=sides[0] if sides else None,
                candidate_tests=sides[1] if sides else None,
            )
            verdict = Verdict(
                experiment_id=experiment.id,
                improved=improved,
                evidence_level=level if improved else EvidenceLevel.REPRODUCTION,
                criteria={"check": f"{name} fails at the base and passes with the candidate", "suite_rounds": 3},
                tests=tests,
                reasons=[
                    f"{opp.details['frame']}: {name} failed at the base and passes with the fix",
                    *(notes if tests is TestOutcome.REGRESSION else []),
                ],
                caveats=[
                    f"the regression test {test_file} is included; Hypothesis seed 0",
                    *(notes if tests is not TestOutcome.REGRESSION else []),
                ],
            )
            self.store.put("experiments", experiment)
            self.store.append_event(
                Event(
                    type=EventType.VERDICT_RECORDED,
                    actor="lab",
                    entity_id=experiment.id,
                    correlation_id=opp.id,
                    payload={"improved": improved, "level": int(verdict.evidence_level)},
                )
            )
            result.experiment, result.verdict, result.candidate = experiment, verdict, candidate
            if improved:
                opp.evidence_level = max(opp.evidence_level, verdict.evidence_level)
                opp.status = OpportunityStatus.EXPERIMENTING
                opp.details = {
                    **opp.details,
                    "experiment_id": experiment.id,
                    "verdict": verdict.model_dump(mode="json"),
                    "candidate": {"origin": candidate.origin, "files": files},
                }
                opp.evidence = [*opp.evidence, EvidenceRef(kind="experiment", locator=experiment.id)]
                opp.updated_at = utc_now()
                self.store.put("opportunities", opp)
            return result
        return result
