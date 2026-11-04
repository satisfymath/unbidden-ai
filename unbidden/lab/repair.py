"""RepairLab: tests the team wrote that fail on its own commit, in its own CI too, repaired in the code they test.

David's rule (campaign 13): Unbidden repairs a failing test only when the failure is the repository's, never its own
environment's. So an opportunity opens only when (1) the test fails in the project's own checks here, (2) the team's
CI fails the same way (its test job, run here as GitHub runs it, failed at a test step; or its CI on GitHub is red and
was not contradicted here), and (3) the environment is sound (the suite ran and collected tests). The lab then
requires (4) the test to fail in every one of three base rounds: a flaky test is another opportunity.

The tests are the specification: the candidate may change only code the failures' tracebacks pass through, never a
test, a conftest, a skip, an xfail, an assertion or an exception handler that hides the failure. It is proven by the
targeted tests passing in three of three rounds and the team's suite with no regression on both sides.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError, ProviderUnauthorized
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.common import EvidenceLevel, EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import SUITE, Experiment, TestOutcome, TestSummary, Verdict
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.contracts.metric import FAILING_TESTS, Measurement, relative
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.lab.evaluator import classify_tests, level_for, validates
from unbidden.lab.fixlab import Candidate, added_suppressions, unified_patch
from unbidden.lab.testsuite import TestPlan, run_suite, test_plan
from unbidden.observe.stack import Stack
from unbidden.provenance import provenance
from unbidden.sandbox.provision import DependencyImage, link_dependencies
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.store import Store

SOURCE = "repair"
ROUNDS = 3
MAX_SOURCES = 3  # code files shown to the model: the deepest frames of the repository's own code
SOURCE_CHARS = 60_000
MAX_TESTS = 10  # failing tests per opportunity (one per test file)
Progress = Callable[[str], None]
TEST_PATH = re.compile(r"(?:^|/)(?:tests?|testing)/|(?:^|/)(?:test_[^/]*|[^/]*_tests?|conftest)\.py$")
_PY_PATH = re.compile(r"[\w./\\-]+\.py")
# What hides a failure instead of fixing it (beyond lint suppressions): a skip or an expected failure.
_SKIPS = re.compile(r"^\+.*(?:pytest\.(?:skip|xfail|importorskip)|mark\.(?:skip|skipif|xfail)|unittest\.skip|"
                    r"SkipTest)", re.MULTILINE)  # fmt: skip
_EXCEPT = re.compile(r"^\+\s*except\b", re.MULTILINE)
# A report that names a missing piece of the environment, not a defect of the code: a browser or executable not
# installed, a service not reachable, a module not installed, the network. Red in the team's CI too, these are its
# runner's (recruitops-agent, campaign 13: Playwright's browser was never installed in its job); a code change
# cannot fix them, so they are never repaired.
ENVIRONMENT = re.compile(
    r"Executable doesn't exist|playwright install|No such file or directory: '[\w.+-]+'|command not found|"
    r"Connection refused|could not connect to server|Can't connect to|Name or service not known|"
    r"Temporary failure in name resolution|getaddrinfo failed|Network is unreachable|ModuleNotFoundError|"
    r"No module named|Permission denied|Read-only file system|No space left on device|Timeout(?:Error)?\b"
)


def environments(text: str) -> bool:
    """Whether a failure's report is the environment's, not the code's."""
    return bool(ENVIRONMENT.search(text))


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH.search(path))


def tracked_files(repo: Path, rev: str) -> list[str]:
    listed = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", rev], capture_output=True,
                            text=True, check=False)  # fmt: skip
    return listed.stdout.split()


def frames(text: str, tracked: list[str]) -> list[str]:
    """The repository's files a traceback passes through, in order, each once. A path in a report is absolute in
    the sandbox (`/w/src/pkg/mod.py`, `/home/runner/work/x/x/pkg/mod.py`) or relative: matched by its tail against
    the tracked files, never guessed."""
    known = set(tracked)
    seen: list[str] = []
    for raw in _PY_PATH.findall(text):
        parts = raw.replace("\\", "/").lstrip("./").split("/")
        hit = next(("/".join(parts[i:]) for i in range(len(parts)) if "/".join(parts[i:]) in known), None)
        if hit is not None and hit not in seen:
            seen.append(hit)
    return seen


def test_file_of(name: str, tracked: list[str], text: str = "") -> str | None:
    """The test file of a junit name (`tests.unit.test_x::test_a`, `tests.test_x.TestY::test_a`)."""
    dotted = name.split("::")[0].split(".")
    for end in range(len(dotted), 0, -1):
        path = "/".join(dotted[:end]) + ".py"
        hit = next((t for t in tracked if t == path or t.endswith("/" + path)), None)
        if hit is not None:
            return hit
    return next((p for p in frames(text, tracked) if is_test_path(p)), None)


def weakening(patch: str, files: dict[str, str]) -> str | None:
    """Why a candidate hides the failures instead of fixing them, or None."""
    tests = sorted(p for p in files if is_test_path(p))
    if tests:
        return f"it changes test code ({', '.join(tests)}); the team's tests are the specification"
    if added_suppressions(patch):
        return "it adds a suppression"
    if _SKIPS.search(patch):
        return "it skips the test or marks it as an expected failure"
    if _EXCEPT.search(patch):
        return "it adds an exception handler (a caught failure is not a fixed one)"
    return None


def always_failing(summary: TestSummary) -> set[str]:
    """Tests that failed in every round that ran: the deterministic failures."""
    rounds = [set(r) for i, r in enumerate(summary.failed_per_round) if summary.status(i) == "ran"]
    if len(rounds) < summary.rounds:
        return set()
    common = set.intersection(*rounds) if rounds else set()
    return common - {SUITE}


def ci_evidence(github: str | None, ci_tests_failed: bool | None) -> str | None:
    """Why the failure is the repository's and not Unbidden's environment, or None when that is not shown.
    A green CI on GitHub, or the team's job passing its tests here, means the failure is ours: never repaired."""
    if github == "green" or ci_tests_failed is False:
        return None
    if ci_tests_failed:
        return "the team's own CI job, run here as GitHub runs it, fails at its test step"
    if github == "red":
        return "the team's CI on GitHub is red on this commit"
    return None


def repair_opportunities(rev: str, record: dict[str, Any], tracked: list[str], evidence: str) -> list[Opportunity]:
    """One opportunity per test file with failures the code is responsible for (the environment's apart)."""
    lacking = set((record.get("could_not_run") or {}).get("by_test", {}))
    texts: dict[str, str] = record.get("failure_texts") or {}
    by_file: dict[str, list[str]] = {}
    for name in record.get("failed") or []:
        if name == SUITE or name in lacking or environments(texts.get(name, "")):
            continue
        test_file = test_file_of(name, tracked, texts.get(name, ""))
        if test_file is not None:
            by_file.setdefault(test_file, []).append(name)
    opened = []
    for test_file, names in sorted(by_file.items()):
        names = sorted(names)[:MAX_TESTS]
        digest = hashlib.sha256("\n".join(names).encode()).hexdigest()[:12]
        code = [p for n in names for p in frames(texts.get(n, ""), tracked) if not is_test_path(p)]
        opened.append(Opportunity(
            source=SOURCE, category="tests",
            title=f"{len(names)} failing test(s) in {test_file}"[:200],
            summary=f"{', '.join(n.split('::')[-1] for n in names[:5])} fail on this commit, and {evidence}.",
            dedup_key=f"{SOURCE}:{rev[:12]}:{test_file}:{digest}",
            evidence_level=EvidenceLevel.REPRODUCTION,
            evidence=[EvidenceRef(kind="test_run", locator=f"{test_file}@{rev}", note=evidence)],
            details={"rev": rev, "test_file": test_file, "tests": names, "evidence": evidence,
                     "texts": {n: texts[n] for n in names if n in texts},
                     "paths": list(dict.fromkeys(code)) or [test_file]},
        ))  # fmt: skip
    return opened


@dataclass
class RepairResult:
    experiment: Experiment | None = None
    verdict: Verdict | None = None
    candidate: Candidate | None = None
    notes: list[str] = field(default_factory=list[str])
    blocked: str | None = None
    absent: str | None = None


class RepairLab:
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
        rounds: int = ROUNDS,
    ) -> None:
        self.repo, self.store, self.brain, self.stack, self.image = repo, store, brain, stack, image
        self.runner = runner or SandboxRunner()
        self.progress, self.attempts, self.rounds = progress, attempts, rounds

    def _suite(self, rev: str, plan: TestPlan, files: dict[str, str]) -> TestSummary:
        work = snapshot(self.repo, rev)
        try:
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, self.image)
            return run_suite(self.runner, work, self.image, plan, rounds=self.rounds)
        finally:
            discard(work)

    async def _candidate(self, opp: Opportunity, rev: str, targets: list[str], texts: dict[str, str],
                         feedback: str) -> Candidate | None:  # fmt: skip
        base = snapshot(self.repo, rev)
        try:
            tracked = tracked_files(self.repo, rev)
            code: list[str] = []
            for name in targets:
                code += [p for p in frames(texts.get(name, ""), tracked) if not is_test_path(p) and p not in code]
            # The deepest frames are closest to the cause: the last files a traceback passes through.
            shown: dict[str, str] = {}
            for path in reversed(code):
                text = (base / path).read_text(errors="replace")
                if len(shown) >= MAX_SOURCES or sum(map(len, shown.values())) + len(text) > SOURCE_CHARS:
                    continue
                shown[path] = text
            if not shown:
                return None
            test_path = str(opp.details["test_file"])
            prompt = load_prompt("repair_fix")
            content = prompt.render(
                failures="\n\n".join(f"{n}\n{texts.get(n, '')}" for n in targets)[-12000:],
                test_path=test_path,
                test_source=(base / test_path).read_text(errors="replace")[:20000],
                sources="\n\n".join(f"The code file `{p}`:\n```python\n{t}\n```" for p, t in shown.items()),
            )
            messages = [Message(role="user", content=content, source="repo")]
            if feedback:
                messages.append(Message(role="user", content=f"A previous attempt failed: {feedback}", source="repo"))
            response = await self.brain.complete(LLMRequest(
                purpose="lab.repair_fix", expect_files=True, tier=Tier.LOCAL, messages=messages,
                prompt_sha256=prompt.sha256, max_tokens=min(16000, 2000 + sum(map(len, shown.values())) // 2),
                correlation_id=opp.id,
            ))  # fmt: skip
            answered = parse_files(response.content)
            files = {p: c for p, c in answered.items() if p in shown}
            files |= {p: c for p, c in answered.items() if is_test_path(p)}  # kept to be refused, never applied
            if not files:
                return None
            return Candidate(self.brain.author("lab.repair_fix"), files, unified_patch(base, files))
        except ProviderUnauthorized:
            raise
        except (BrainError, ProviderError, CodeBlockError, OSError):
            return None
        finally:
            discard(base)

    async def run(self, opp: Opportunity) -> RepairResult:
        result = RepairResult()
        rev = str(opp.details["rev"])
        wanted = list(opp.details.get("tests") or [])
        plan = test_plan(self.repo, rev, self.stack, "python")
        if plan is None:
            result.blocked = "no test plan for this commit"
            return self._done(opp, result)
        self.progress(f"running the team's suite at the base, {self.rounds} rounds")
        base = self._suite(rev, plan, {})
        targets = sorted(
            n for n in always_failing(base) & set(wanted) if not environments(base.failure_texts.get(n, ""))
        )
        if not targets:
            result.absent = (f"none of the {len(wanted)} test(s) fails in every one of {self.rounds} base rounds: "
                             "not a deterministic failure (a flaky test is another opportunity)")  # fmt: skip
            return self._done(opp, result)
        texts = {**opp.details.get("texts", {}), **base.failure_texts}
        feedback = ""
        for attempt in range(self.attempts):
            self.progress(f"asking {self.brain.where('lab.repair_fix')} to repair {len(targets)} test(s) "
                          f"(attempt {attempt + 1})")  # fmt: skip
            candidate = await self._candidate(opp, rev, targets, texts, feedback)
            if candidate is None:
                feedback = "the answer had no usable file block for the code files shown"
                result.notes.append(f"attempt {attempt + 1}: no usable change")
                continue
            hides = weakening(candidate.patch, candidate.files)
            if hides:
                feedback = f"the change was refused: {hides}. Fix the code under test."
                result.notes.append(f"attempt {attempt + 1} quarantined: {hides}")
                continue
            self.progress(f"running the team's suite with the repair, {self.rounds} rounds")
            head = self._suite(rev, plan, candidate.files)
            still = sorted(n for n in targets if any(n in r for r in head.failed_per_round))
            tests, notes = classify_tests(base, head)
            # The targets failed before by definition: "fails before the change too" is said only of the others.
            notes = [n for n in notes if not any(n.endswith(f": {t}") for t in targets if t not in still)]
            if still:
                tail = "\n\n".join(f"{n}\n{head.failure_texts.get(n, '')[-1500:]}" for n in still[:3])
                feedback = f"with your change these tests still fail:\n{tail}"
                result.notes.append(f"attempt {attempt + 1}: {len(still)} of {len(targets)} still fail")
                if attempt + 1 < self.attempts:
                    continue
            improved = not still and validates(tests)
            return self._record(opp, result, rev, targets, still, base, head, tests, notes, candidate, improved)
        return self._done(opp, result)

    def _record(self, opp: Opportunity, result: RepairResult, rev: str, targets: list[str], still: list[str],
                base: TestSummary, head: TestSummary, tests: TestOutcome, notes: list[str], candidate: Candidate,
                improved: bool) -> RepairResult:  # fmt: skip
        level = level_for(improved, tests, suite_ran=True)
        measurement = Measurement(metric=FAILING_TESTS, base=float(len(targets)), head=float(len(still)),
                                  effect=relative(len(targets), len(still), "lower"), n_base=self.rounds,
                                  n_head=self.rounds, met=improved)  # fmt: skip
        experiment = Experiment(
            opportunity_id=opp.id, base_sha=rev, candidate_patch_sha256=candidate.sha256, rounds=self.rounds,
            baseline_tests=base, candidate_tests=head, provenance=provenance(self.brain, [self.image]),
            measurements=[measurement],
        )  # fmt: skip
        fixed = len(targets) - len(still)
        verdict = Verdict(
            experiment_id=experiment.id, improved=improved,
            evidence_level=level if improved else EvidenceLevel.REPRODUCTION,
            criteria={"check": "every targeted test fails in every base round and passes in every round with the "
                      "change; no test changed; the team's suite shows no regression", "suite_rounds": self.rounds},
            tests=tests,
            reasons=[f"{fixed} of {len(targets)} test(s) of {opp.details['test_file']} failed in {self.rounds} of "
                     f"{self.rounds} base rounds and pass in {self.rounds} of {self.rounds} with the change",
                     f"why the failure is the repository's: {opp.details.get('evidence')}",
                     *(notes if tests is TestOutcome.REGRESSION else [])],
            caveats=["no test, conftest, skip or assertion was changed; only code the tracebacks pass through",
                     *(notes if tests is not TestOutcome.REGRESSION else [])],
            measurements=[measurement],
        )  # fmt: skip
        self.store.put("experiments", experiment)
        self.store.append_event(Event(
            type=EventType.VERDICT_RECORDED, actor="lab", entity_id=experiment.id, correlation_id=opp.id,
            payload={"improved": improved, "level": int(verdict.evidence_level), "tests": tests.value,
                     "reasons": verdict.reasons, "origin": candidate.origin},
        ))  # fmt: skip
        result.experiment, result.verdict, result.candidate = experiment, verdict, candidate
        return self._done(opp, result)

    def _done(self, opp: Opportunity, result: RepairResult) -> RepairResult:
        if result.verdict is not None and result.verdict.improved and result.candidate is not None:
            opp.evidence_level = max(opp.evidence_level, result.verdict.evidence_level)
            opp.status = OpportunityStatus.EXPERIMENTING
            opp.details = {
                **opp.details,
                "experiment_id": result.experiment.id if result.experiment else None,
                "verdict": result.verdict.model_dump(mode="json"),
                "candidate": {"origin": result.candidate.origin, "files": result.candidate.files},
            }
            if result.experiment is not None:
                opp.evidence = [*opp.evidence, EvidenceRef(kind="experiment", locator=result.experiment.id)]
        else:
            opp.details = {**opp.details, "lab_notes": [*result.notes, *([result.blocked] if result.blocked else []),
                                                         *([result.absent] if result.absent else [])]}  # fmt: skip
        opp.updated_at = utc_now()
        self.store.put("opportunities", opp)
        return result
