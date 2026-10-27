"""Robustness probes: find crashes by running property-based tests the local model writes, offline.

Only a crash that ends inside the package, with an exception type that signals a bug, counts. A ValueError or
TypeError may be the library validating its input, and a failed assertion may be a wrong property; neither
becomes an opportunity.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.contracts.opportunity import Opportunity
from unbidden.sandbox.provision import DependencyImage, link_dependencies
from unbidden.sandbox.runner import SandboxRunner, SandboxSpec, discard, snapshot
from unbidden.store import Store

PROBE_FILE = "tests/test_unbidden_robustness.py"
BUG_EXCEPTIONS = (
    "IndexError",
    "KeyError",
    "RecursionError",
    "ZeroDivisionError",
    "UnboundLocalError",
    "AttributeError",
)
MAX_FUNCTIONS = 80
PER_MODULE = 5


@dataclass(frozen=True)
class Crash:
    test: str
    exception: str
    message: str
    frame: str  # "path:line in function", the innermost frame inside the package
    example: str  # Hypothesis's falsifying example
    excerpt: str


_TEXTY = ("text", "markup", "string", "str", "s", "line", "content", "source", "value", "chars", "character")


def _texty(args: ast.arguments) -> bool:
    """Takes user text: a parameter annotated str or named like text."""
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        annotation = ast.unparse(arg.annotation) if arg.annotation else ""
        if "str" in annotation or arg.arg in _TEXTY:
            return True
    return False


def public_functions(repo: Path, rev: str, package: str) -> list[str]:
    """Public module-level functions and public methods of public classes, with signature and first docstring line.
    Those that take user text come first: that is where inputs nobody anticipated arrive."""
    files = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", rev, package],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    texty: dict[str, list[str]] = {}
    other: dict[str, list[str]] = {}
    for path in sorted(f for f in files if f.endswith(".py") and not Path(f).name.startswith("_")):
        source = subprocess.run(
            ["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True
        ).stdout
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        module = path.removesuffix(".py").replace("/", ".")
        for node in tree.body:
            entries: list[tuple[str, ast.FunctionDef]] = []
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                entries.append((f"from {module} import {node.name}  # def {node.name}", node))
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                        entries.append((f"from {module} import {node.name}  # {node.name}.{item.name}", item))
            for head, fn in entries:
                doc = (ast.get_docstring(fn) or "").strip().splitlines()[:1]
                line = f"{head}({ast.unparse(fn.args)})" + (f" — {doc[0]}" if doc else "")
                (texty if _texty(fn.args) else other).setdefault(module, []).append(line)
    # A few per module, in turns, so one large module (a console) does not crowd out the rest.
    picked = [line for lines in texty.values() for line in lines[:PER_MODULE]]
    picked += [line for lines in other.values() for line in lines[:2]]
    return picked[:MAX_FUNCTIONS]


def property_violations(output: str) -> list[tuple[str, str]]:
    """(test, assertion) for tests that failed on an assertion: a possible bug, or a property stated too strictly."""
    found: list[tuple[str, str]] = []
    for line in output.splitlines():
        match = re.match(r"^FAILED \S+::(test_\w+) - AssertionError: (.*)$", line)
        if match:
            found.append((match.group(1), match.group(2)[:300]))
    return found


_FAIL_HEADER = re.compile(r"^_{3,} (test_\w+) _{3,}$", re.MULTILINE)


_GROUP_PART = re.compile(r"^\s*\+?-+\+?-* \d+ -+$", re.MULTILINE)
_PY_FRAME = re.compile(r'File "(?:/work/)?(?P<path>[\w/.-]+\.py)", line (?P<line>\d+), in (?P<fn>\w+)')
_PY_EXC = re.compile(r"^\s*\|?\s*(?P<exc>\w+(?:Error|Exception)): (?P<msg>.*)$", re.MULTILINE)
_PY_CASE = re.compile(r"Failing test case: (?P<case>.+?)\n\s*\|?\s*\n", re.DOTALL)


def _group_crashes(name: str, body: str, package: str) -> list[Crash]:
    """Hypothesis reports several distinct failures as an ExceptionGroup, in Python's traceback format."""
    crashes: list[Crash] = []
    for part in _GROUP_PART.split(body)[1:]:
        frames = [m for m in _PY_FRAME.finditer(part) if m.group("path").startswith(f"{package}/")]
        excs = [m for m in _PY_EXC.finditer(part) if m.group("exc") != "ExceptionGroup"]
        if not frames or not excs or excs[-1].group("exc") not in BUG_EXCEPTIONS:
            continue
        frame = frames[-1]
        case = _PY_CASE.search(part)
        example = re.sub(r"\n\s*\|\s*", " ", case.group("case")).strip() if case else ""
        crashes.append(
            Crash(
                name,
                excs[-1].group("exc"),
                excs[-1].group("msg").strip()[:300],
                f"{frame.group('path')}:{frame.group('line')} in {frame.group('fn')}",
                example[:600],
                part[-2500:],
            )
        )
    return crashes


def parse_crashes(output: str, package: str) -> list[Crash]:
    crashes: list[Crash] = []
    sections = _FAIL_HEADER.split(output)
    for name, body in zip(sections[1::2], sections[2::2], strict=False):
        if "ExceptionGroup" in body:
            crashes.extend(_group_crashes(name, body, package))
            continue
        exc = re.findall(r"^E\s+(\w+(?:Error|Exception))\b:?\s*(.*)$", body, re.MULTILINE)
        frames = re.findall(rf"^({re.escape(package)}/[\w/]+\.py):(\d+): in (\w+)", body, re.MULTILINE)
        example = re.search(r"Falsifying example: (.+?)(?:\n\n|\n[A-Z_]{2,})", body, re.DOTALL)
        if not exc or not frames:
            continue
        exception, message = exc[-1]
        if exception not in BUG_EXCEPTIONS:
            continue
        path, line, function = frames[-1]
        crashes.append(
            Crash(
                name,
                exception,
                message.strip()[:300],
                f"{path}:{line} in {function}",
                example.group(1).strip()[:600] if example else "",
                body[-2500:],
            )
        )
    return crashes


class RobustnessProbe:
    def __init__(
        self, repo: Path, store: Store, brain: Brain, image: DependencyImage, *, runner: SandboxRunner | None = None
    ) -> None:
        self.repo, self.store, self.brain, self.image = repo, store, brain, image
        self.runner = runner or SandboxRunner()
        self.last_answer = ""

    async def write_tests(self, rev: str, package: str, count: int = 8) -> str | None:
        prompt = load_prompt("robustness_tests")
        try:
            response = await self.brain.complete(
                LLMRequest(
                    purpose="research.robustness",
                    expect_files=True,
                    tier=Tier.LOCAL,
                    max_tokens=5000,
                    prompt_sha256=prompt.sha256,
                    messages=[
                        Message(
                            role="user",
                            source="repo",
                            content=prompt.render(
                                package=package,
                                count=str(count),
                                path=PROBE_FILE,
                                functions="\n".join(public_functions(self.repo, rev, package)),
                            ),
                        )
                    ],
                )
            )
        except (BrainError, ProviderError):
            return None
        self.last_answer = response.content
        try:
            return parse_files(response.content).get(PROBE_FILE)
        except CodeBlockError:
            # One fenced Python block of Hypothesis tests is the file, even without the `# file:` header.
            blocks = re.findall(r"```(?:python)?\n(.*?)```", response.content, re.DOTALL)
            tests = [b for b in blocks if "@given" in b]
            return tests[0] if len(tests) == 1 else None

    async def refine(self, tests: str, output: str) -> str | None:
        """Send assertion failures back: narrow a property that was too strict, keep one that found a bug."""
        failures = "\n".join(ln for ln in output.splitlines() if ln.startswith(("E ", "FAILED")))[-4000:]
        prompt = load_prompt("robustness_refine")
        try:
            response = await self.brain.complete(
                LLMRequest(
                    purpose="research.robustness",
                    tier=Tier.LOCAL,
                    max_tokens=5000,
                    expect_files=True,
                    prompt_sha256=prompt.sha256,
                    messages=[
                        Message(
                            role="user",
                            source="repo",
                            content=prompt.render(path=PROBE_FILE, failures=failures, tests=tests),
                        )
                    ],
                )
            )
        except (BrainError, ProviderError):
            return None
        return parse_files(response.content).get(PROBE_FILE)

    def run_tests(self, rev: str, tests: str, *, timeout_s: float = 900) -> str:
        work = snapshot(self.repo, rev)
        try:
            (work / PROBE_FILE).parent.mkdir(parents=True, exist_ok=True)
            (work / PROBE_FILE).write_text(tests)
            link_dependencies(work, self.image)
            argv = [
                "python",
                "-m",
                "pytest",
                PROBE_FILE,
                "-q",
                "-p",
                "no:cacheprovider",
                "--tb=long",
                "-o",
                "addopts=",
                "--hypothesis-seed=0",
            ]
            result = self.runner.run(
                SandboxSpec(image=self.image.tag, argv=argv, env=self.image.env, timeout_s=timeout_s), work
            )
            return result.stdout + result.stderr
        finally:
            discard(work)

    def record(self, rev: str, package: str, tests: str, crashes: list[Crash]) -> list[Opportunity]:
        opened: list[Opportunity] = []
        for crash in crashes:
            key = f"robustness:{crash.frame.split(':')[0]}:{crash.exception}:{crash.frame.split(' in ')[-1]}"
            if self.store.get_by_key("opportunities", key, Opportunity) is not None:
                continue
            opp = Opportunity(
                source="robustness",
                category="bugs",
                title=f"{crash.exception} in {crash.frame.split(' in ')[-1]} ({crash.frame.split(':')[0]})",
                summary=f"{crash.exception}: {crash.message}. Found by a property-based test; falsifying example: "
                f"{crash.example[:300]}",
                dedup_key=key,
                evidence_level=EvidenceLevel.REPRODUCTION,
                evidence=[EvidenceRef(kind="test_run", locator=f"{PROBE_FILE}::{crash.test}@{rev}", note=crash.frame)],
                details={
                    "rev": rev,
                    "package": package,
                    "test": crash.test,
                    "tests_source": tests,
                    "frame": crash.frame,
                    "example": crash.example,
                    "excerpt": crash.excerpt,
                    "paths": [crash.frame.split(":")[0]],
                },
            )
            self.store.put("opportunities", opp, key=key)
            self.store.append_event(
                Event(
                    type=EventType.OPPORTUNITY_OPENED,
                    actor="research",
                    entity_id=opp.id,
                    correlation_id=opp.id,
                    payload={"title": opp.title, "frame": crash.frame},
                )
            )
            opened.append(opp)
        return opened
