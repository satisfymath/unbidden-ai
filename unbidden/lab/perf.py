"""PerfLab: measure a performance opportunity on both sides, with criteria fixed before measuring.

1. The local model writes a candidate (the schema change, as this repository makes schema changes).
2. The local model writes a workload: synthetic data and one request to an affected endpoint.
3. Our fixed driver runs it at the base and at the candidate, each side in its own sandbox with fresh
   services, after the repository's own CI setup steps (migrations included): warm-up, then samples.
4. Mann-Whitney, effect size and a bootstrap interval decide; the CI test job runs on both sides too.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
from unbidden.lab.fixlab import Candidate, unified_patch
from unbidden.lab.perfstats import PERF_CRITERIA, judge
from unbidden.lab.testsuite import TestPlan, run_suite, test_plan
from unbidden.observe.ci import ci_test_plan
from unbidden.observe.stack import Stack
from unbidden.sandbox.provision import DependencyImage, link_dependencies, sandbox_spec
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.sandbox.sidecars import data_services
from unbidden.sandbox.tools import tools_for

ACTOR = "lab"
LAB_DIR = ".unbidden-lab"
SAMPLES = 20
WARMUP = 3
SEED_ROWS = 200_000
SEED_OWNERS = 2_000
Progress = Callable[[str], None]

DRIVER_TEST = "test_unbidden_workload"
DRIVER = f'''"""Unbidden's measurement driver: fixed code, never written by a model.

It runs as one more test inside the repository's own CI test command, so it gets exactly the environment,
fixtures and configuration the team's tests get.
"""
import importlib.util, inspect, json, time
from pathlib import Path


def {DRIVER_TEST}(request):
    spec = importlib.util.spec_from_file_location("unbidden_workload", "/work/{LAB_DIR}/workload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # build()'s parameters are the suite's own fixtures, by name (`def build(api_client, unique_user)`).
    fixtures = {{name: request.getfixturevalue(name) for name in inspect.signature(module.build).parameters}}
    call = module.build(**fixtures)
    for _ in range({WARMUP}):
        status = call()
        assert status == 200, f"warm-up returned HTTP {{status}}"
    latencies = []
    for _ in range({SAMPLES}):
        started = time.perf_counter()
        status = call()
        latencies.append((time.perf_counter() - started) * 1000)
        assert status == 200, f"sample returned HTTP {{status}}"
    Path("/work/{LAB_DIR}/result.json").write_text(json.dumps({{"latencies_ms": latencies}}))
'''
_REVISION = re.compile(r"^revision\s*(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*['\"]?([^'\"\n]*)['\"]?", re.MULTILINE)


_PARALLEL = re.compile(r"\s(?:-n|--numprocesses)(?:\s+|=)\S+|\s--dist(?:\s+|=)\S+")


def serial(argv: tuple[str, ...]) -> tuple[str, ...]:
    """The team's test command without pytest-xdist's workers: the lab times one selected test, which parallel
    workers cannot speed up, and each worker imports the whole application (mealie's `-n auto` exceeded the
    sandbox's memory before any test ran)."""
    return tuple(
        "\n".join(_PARALLEL.sub("", line) if "pytest" in line else line for line in arg.splitlines()) for arg in argv
    )


def failure_excerpt(output: str, limit: int = 2500) -> str:
    """The lines that say what went wrong (pytest's `E` lines, tracebacks' last frames), not the noise around."""
    lines = output.splitlines()
    keep = [ln for ln in lines if ln.startswith(("E ", "FAILED", "ERROR")) or "Error:" in ln or "error:" in ln]
    tail = "\n".join(lines[-25:])
    excerpt = "\n".join(dict.fromkeys(keep)) + "\n...\n" + tail if keep else tail
    return excerpt[-limit:]


@dataclass
class PerfResult:
    experiment: Experiment | None = None
    verdict: Verdict | None = None
    candidate: Candidate | None = None
    notes: list[str] = field(default_factory=list[str])
    blocked: str | None = None  # what Unbidden lacks to run the experiment at all: not an experiment, not a negative


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def alembic_head(repo: Path, rev: str) -> tuple[str, str, str] | None:
    """(migrations directory, head revision, head file) of an Alembic history, read from git."""
    files = [
        f
        for f in _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()
        if "/versions/" in f and f.endswith(".py")
    ]
    revisions: dict[str, tuple[str, str]] = {}
    for path in files:
        text = _git(repo, "show", f"{rev}:{path}")
        revision, down = _REVISION.search(text), _DOWN.search(text)
        if revision:
            revisions[revision.group(1)] = (path, down.group(1) if down else "")
    referenced = {down for _, down in revisions.values()}
    heads = [r for r in revisions if r not in referenced]
    if len(heads) != 1:
        return None
    path = revisions[heads[0]][0]
    return str(Path(path).parent), heads[0], path


_COLUMN_CALL = re.compile(r"(mapped_column|Column|Field)\(")


def index_candidate(
    show: Callable[[str], str], table: str, column: str, models_file: str, head: tuple[str, str, str]
) -> dict[str, str] | None:
    """The change an unindexed foreign key asks for, written without a model: `index=True` on the column of the
    class mapped to `table`, and an Alembic migration that creates the index after the current head. None when the
    column is not declared on one line, where an edit by pattern would be a guess."""
    source = show(models_file)
    lines = source.splitlines(keepends=True)
    mapped = next(
        (i for i, x in enumerate(lines) if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(table)}[\"']", x)), None
    )
    if mapped is None:
        return None
    start = max((i for i in range(mapped) if lines[i].startswith("class ")), default=0)
    end = next((i for i in range(mapped, len(lines)) if lines[i].startswith("class ")), len(lines))
    declared = [
        i
        for i in range(start, end)
        if re.match(rf"\s+{re.escape(column)}\s*(:|=)", lines[i]) and _COLUMN_CALL.search(lines[i])
    ]
    if len(declared) != 1:
        return None
    line = lines[declared[0]].rstrip("\n")
    if "index=" in line or not line.rstrip().endswith(")") or line.count("(") != line.count(")"):
        return None
    stripped = line.rstrip()
    lines[declared[0]] = f"{stripped[:-1]}, index=True)\n"
    migrations_dir, head_rev, _ = head
    revision = hashlib.sha256(f"{table}.{column}:{head_rev}".encode()).hexdigest()[:12]
    name = f"ix_{table}_{column}"
    migration = f'''"""add index on {table}.{column}

Revision ID: {revision}
Revises: {head_rev}

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "{revision}"
down_revision: str | None = "{head_rev}"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade():
    with op.batch_alter_table("{table}", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("{name}"), ["{column}"], unique=False)


def downgrade():
    with op.batch_alter_table("{table}", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("{name}"))
'''
    return {models_file: "".join(lines), f"{migrations_dir}/{revision}_add_index_{table}_{column}.py": migration}


class PerfLab:
    def __init__(
        self,
        repo: Path,
        brain: Brain,
        store: Any,
        stack: Stack,
        images: dict[str, DependencyImage],
        *,
        runner: SandboxRunner | None = None,
        progress: Progress = lambda _: None,
        repairs: int = 4,
    ) -> None:
        self.repo, self.brain, self.store, self.stack, self.images = repo, brain, store, stack, images
        self.runner = runner or SandboxRunner()
        self.progress = progress
        self.repairs = repairs

    # Model-written artifacts ----------------------------------------------------------------------------

    async def _ask_files(
        self, purpose: str, content: str, opp: Opportunity, sha: str, max_tokens: int
    ) -> dict[str, str] | None:
        try:
            response = await self.brain.complete(
                LLMRequest(
                    purpose=purpose,
                    expect_files=True,
                    tier=Tier.LOCAL,
                    messages=[Message(role="user", content=content, source="repo")],
                    max_tokens=max_tokens,
                    prompt_sha256=sha,
                    correlation_id=opp.id,
                )
            )
            return parse_files(response.content)
        except (BrainError, ProviderError, CodeBlockError):
            return None

    def _show(self, rev: str, path: str) -> str:
        return _git(self.repo, "show", f"{rev}:{path}")

    def _handlers(self, opp: Opportunity, rev: str) -> list[tuple[str, str, str]]:
        from unbidden.world.relations import handler_source

        out: list[tuple[str, str, str]] = []
        for code in opp.details.get("code", []):
            if code.get("file"):
                out.append(
                    (
                        code["endpoint"],
                        code["file"],
                        handler_source(self.repo, rev, code["file"], int(code["line"] or 1)),
                    )
                )
        return out

    def _models_file(self, rev: str, table: str) -> str | None:
        for path in _git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines():
            if path.endswith(".py") and not re.search(r"(^|/)(tests|alembic|migrations|versions)/", path):
                text = self._show(rev, path)
                if re.search(rf"class\s+{re.escape(table)}\s*\(", text, re.IGNORECASE) and "table=True" in text:
                    return path
                if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(table)}[\"']", text):  # SQLAlchemy
                    return path
        return None

    def _related_models(self, rev: str, models_file: str, table: str, budget: int = 6000) -> str:
        """The classes of the tables `table` references (its foreign keys): a workload has to create those rows
        first, with their own required columns, and they are often in other files."""
        source = self._show(rev, models_file)
        lines = source.splitlines()
        mapped = next(
            (i for i, x in enumerate(lines) if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(table)}[\"']", x)), None
        )
        block = source
        if mapped is not None:
            start = max((i for i in range(mapped) if lines[i].startswith("class ")), default=0)
            end = next((i for i in range(mapped + 1, len(lines)) if lines[i].startswith("class ")), len(lines))
            block = "\n".join(lines[start:end])
        targets = list(dict.fromkeys(re.findall(r"ForeignKey\(\s*[\"'](\w+)\.", block)))
        out: list[str] = []
        for target in targets:
            path = self._models_file(rev, target)
            if path is None:
                continue
            text = self._show(rev, path).splitlines()
            at = next(
                (i for i, x in enumerate(text) if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(target)}[\"']", x)),
                None,
            )
            if at is None:
                continue
            start = max((i for i in range(at) if text[i].startswith("class ")), default=0)
            end = next((i for i in range(at + 1, len(text)) if text[i].startswith("class ")), len(text))
            out.append(f"`{target}` in `{path}`:\n```python\n" + "\n".join(text[start:end])[:2500] + "\n```")
        return "\n\n".join(out)[:budget] or "(none found)"

    def _test_examples(self, rev: str, endpoint: str = "", table: str = "", budget: int = 20000) -> str:
        """What a workload needs to fit the repository's own tests, most specific first: an existing test that calls
        the endpoint (its imports and calls are real), every pytest fixture the suite defines (name, parameters,
        file), the fixture files about the table, and the conftest."""
        tracked = _git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines()
        tests = [p for p in tracked if p.endswith(".py") and re.search(r"(^|/)tests?/", p)]
        sources = {p: self._show(rev, p) for p in tests}
        blocks: list[str] = []

        # 1. A test that calls the endpoint, by its path or by a constant holding it (`foods_merge = "/api/..."`).
        path = endpoint.partition(" ")[2]
        literal = re.sub(r"\{[^}]*\}.*$", "", path).rstrip("/") if path else ""
        if literal:
            names = {
                m.group(1)
                for text in sources.values()
                for m in re.finditer(rf"^(\w+)\s*=\s*f?[\"']{re.escape(literal)}/?[\"']", text, re.MULTILINE)
            }
            needles = [literal, *(rf"\b{n}\b" for n in names)]
            callers = [
                p
                for p, text in sources.items()
                if Path(p).name.startswith("test_")
                and any(re.search(n if n != literal else re.escape(n), text) for n in needles)
            ]
            callers.sort(
                key=lambda p: (
                    -len(set(re.split(r"[/_.]", literal.lower())) & set(re.split(r"[/_.]", p.lower()))),
                    len(sources[p]),
                )
            )
            for caller in callers[:1]:
                blocks.append(
                    f"An existing test that calls `{endpoint}`, `{caller}`:\n```python\n{sources[caller][:5000]}```"
                )

        # 2. Every fixture the suite defines.
        fixtures = [
            f"- `{m.group(2)}({m.group(3).strip()})` in `{p}`"
            for p, text in sources.items()
            for m in re.finditer(r"@(?:pytest\.)?fixture[^\n]*\n(?:@[^\n]*\n)*(async\s+)?def\s+(\w+)\(([^)]*)\)", text)
        ]
        if fixtures:
            blocks.append(
                "Fixtures the test suite defines (use these; do not invent others):\n" + "\n".join(fixtures[:80])
            )
            # The classes those fixtures are typed with (`unique_user: TestUser`): their attributes are the contract.
            typed = sorted({t for f in fixtures for t in re.findall(r":\s*(?:\w+\.)?([A-Z]\w+)", f)})
            for name in typed[:6]:
                found = next(
                    (
                        (p, m.start())
                        for p, text in sources.items()
                        if (m := re.search(rf"^class {name}\b", text, re.M))
                    ),
                    None,
                )
                if found is not None:
                    path, at = found
                    body = sources[path][at:]
                    end = re.compile(r"^\S", re.M).search(body, body.find("\n") + 1)  # next top-level line
                    definition = body[: end.start()] if end else body
                    blocks.append(f"`{name}` in `{path}`:\n```python\n{definition[:1500]}```")

        # 3. Fixture files about the table, then the conftest.
        words = {w.removesuffix("s") for w in re.split(r"[_.]", table.lower()) if len(w) > 2}
        related = [
            p
            for p in sources
            if re.search(r"(fixture|conftest)", Path(p).name)
            and words & {w.removesuffix("s") for w in re.split(r"[/_.]", p.lower())}
        ]
        for extra in [*related[:2], *[p for p in sources if Path(p).name == "conftest.py"][:1]]:
            blocks.append(f"`{extra}`:\n```python\n{sources[extra][:3000]}```")

        text = "\n\n".join(blocks)
        return text[:budget] if text else "(no test helpers found)"

    # Measurement ----------------------------------------------------------------------------------------

    def _measure(
        self, rev: str, files: dict[str, str], plan: TestPlan, test_dir: str
    ) -> tuple[list[float] | None, str]:
        """Run the workload as a test of the repository's CI test command, selected by name."""
        image = self.images["python"]
        work = snapshot(self.repo, rev)
        try:
            for path, content in {**files, f"{test_dir}/{DRIVER_TEST}.py": DRIVER}.items():
                target = work / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                target.chmod(0o666)
            (work / LAB_DIR).chmod(0o777)
            link_dependencies(work, image)
            env = {**plan.env, "PYTEST_ADDOPTS": f"-k {DRIVER_TEST} -p no:cacheprovider"}
            with data_services(list(plan.services)) as sidecars:
                spec = sandbox_spec(
                    image,
                    list(serial(plan.argv)),
                    public_env=env,
                    timeout_s=900,
                    network=sidecars.network if sidecars else "none",
                )
                result = self.runner.run(spec, work)
            out = work / LAB_DIR / "result.json"
            if out.exists():
                return [float(x) for x in json.loads(out.read_text())["latencies_ms"]], ""
            return None, failure_excerpt(result.stdout + result.stderr)
        finally:
            discard(work)

    def _keep(self, opp: Opportunity, name: str, code: str, output: str) -> None:
        """Failed attempts are evidence too: kept next to the experiments for `unbidden why`."""
        if self.store.path is None:
            return
        folder = self.store.path.parent / "artifacts" / opp.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.py").write_text(code)
        (folder / f"{name}.log").write_text(output)

    def _findings(self, rev: str, files: dict[str, str]) -> Counter[str]:
        """Findings of every check the repository uses, as a multiset of 'tool rule path: message'."""
        image = self.images["python"]
        work = snapshot(self.repo, rev)
        try:
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, image)
            found: Counter[str] = Counter()
            for tool in tools_for(self.stack):
                if tool.language != "python":
                    continue
                result = self.runner.run(sandbox_spec(image, list(tool.argv), cwd=tool.cwd), work)
                for f in tool.report(result, list(tool.argv)).findings:
                    found[f"{f.tool} {f.rule} {f.path}: {f.message}"] += 1
            return found
        finally:
            discard(work)

    # The experiment -------------------------------------------------------------------------------------

    async def run(self, opp: Opportunity) -> PerfResult:
        result = PerfResult()
        rev: str = opp.details["rev"]
        table, endpoints = opp.details["table"], opp.details["endpoints"]
        plan = test_plan(self.repo, rev, self.stack, "python")
        ci = ci_test_plan(self.repo, rev, "python")
        head = alembic_head(self.repo, rev)
        models_file = self._models_file(rev, table)
        handlers = self._handlers(opp, rev)
        missing = [
            what
            for what, have in (
                ("a CI job that runs the tests", plan is not None and ci is not None),
                ("a single Alembic head", head is not None),
                (f"the model of table {table}", models_file is not None),
                ("the handlers of the endpoints that read it", bool(handlers)),
            )
            if not have
        ]
        if opp.details.get("cost_path") == "parent_delete":
            # The cost is the database's own foreign-key check; whether the test database makes it (SQLite only
            # with `PRAGMA foreign_keys`) is not something the lab can tell yet, and a test run without it would
            # report "no effect" for the wrong reason.
            missing.append("test database known to enforce foreign keys")
        if missing:
            result.blocked = "cannot measure: no " + ", no ".join(missing)
            result.notes.append(result.blocked)
            return result
        assert plan is not None and ci is not None and head is not None and models_file is not None
        cwd = ci.steps[-1].cwd if ci.steps else "."
        test_dir = self.stack.python.test_paths[0] if self.stack.python and self.stack.python.test_paths else "tests"
        list_endpoint = next((e for e in endpoints if e.startswith("GET ") and "{" not in e), endpoints[0])
        handler = next((h for h in handlers if h[0] == list_endpoint), handlers[0])

        # Candidate, held to the repository's own checks: a speed-up may not bring new findings with it.
        cand_prompt = load_prompt("perf_candidate")
        migrations_dir, head_rev, head_file = head
        content = cand_prompt.render(
            problem=opp.summary,
            migrations_dir=migrations_dir,
            head=head_rev,
            head_file=head_file,
            head_example=self._show(rev, head_file)[:4000],
            models_file=models_file,
            models=self._show(rev, models_file)[:8000],
            handlers="\n\n".join(f"`{e}` in `{f}`:\n```python\n{c}```" for e, f, c in handlers[:4]),
        )
        before_findings = self._findings(rev, {})
        candidate_files: dict[str, str] | None = None
        origin = ""
        column = str(opp.details.get("column", ""))
        if opp.details.get("check") == "unindexed_foreign_key" and column:
            candidate_files = index_candidate(lambda path: self._show(rev, path), table, column, models_file, head)
            if candidate_files and self._findings(rev, candidate_files) - before_findings:
                result.notes.append("the written index change added findings; asking the local model instead")
                candidate_files = None
            elif candidate_files:
                origin = "rule"  # written by Unbidden from the finding, no model involved
                self.progress(f"candidate: index on {table}.{column}, written from the finding")
        for attempt in range(0 if candidate_files else 2):
            self.progress(f"asking the local model for the schema change (attempt {attempt + 1})")
            candidate_files = await self._ask_files("lab.perf_candidate", content, opp, cand_prompt.sha256, 4000)
            if not candidate_files:
                continue
            new = self._findings(rev, candidate_files) - before_findings
            if not new:
                break
            listed = "\n".join(f"- {f}" for f in sorted(new.elements())[:10])
            result.notes.append(f"candidate attempt {attempt + 1} added {sum(new.values())} finding(s)")
            content += (
                f"\n\nYour previous change added findings from this repository's own checks:\n{listed}\nAvoid them."
            )
            candidate_files = None
        if not candidate_files:
            result.notes.append("the local model gave no schema change that keeps the repository's checks clean")
            return result
        base_dir = snapshot(self.repo, rev)
        candidate = Candidate(
            origin or self.brain.author("lab.perf_candidate"), candidate_files, unified_patch(base_dir, candidate_files)
        )
        discard(base_dir)
        # Workload, repaired against the base until it runs.
        wl_prompt = load_prompt("perf_workload")
        feedback = ""
        before: list[float] | None = None
        workload: dict[str, str] | None = None
        for attempt in range(self.repairs + 1):
            self.progress(f"writing the workload (attempt {attempt + 1})")
            workload = await self._ask_files(
                "lab.workload",
                wl_prompt.render(
                    framework="FastAPI",
                    endpoint=list_endpoint,
                    rows=str(SEED_ROWS),
                    owners=str(SEED_OWNERS),
                    table=table,
                    cwd=f"/work/{cwd}",
                    feedback=feedback,
                    handler_file=handler[1],
                    handler=handler[2],
                    models_file=models_file,
                    models=self._show(rev, models_file)[:8000],
                    related_models=self._related_models(rev, models_file, table),
                    test_examples=self._test_examples(rev, list_endpoint, table),
                ),
                opp,
                wl_prompt.sha256,
                3000,
            )
            workload = {k: v for k, v in (workload or {}).items() if k == f"{LAB_DIR}/workload.py"}
            if not workload:
                feedback = "Your previous answer had no `# file: .unbidden-lab/workload.py` block."
                continue
            self.progress("measuring the base")
            before, error = self._measure(rev, workload, plan, test_dir)
            if before is not None:
                break
            feedback = f"Your previous workload failed when run. The end of its output:\n```\n{error}\n```\nFix it."
            last_line = next((ln for ln in error.splitlines() if ln.startswith("E ") or "Error" in ln), "no output")
            result.notes.append(f"workload attempt {attempt + 1} failed: {last_line[:200]}")
            self._keep(opp, f"workload-attempt-{attempt + 1}", workload[f"{LAB_DIR}/workload.py"], error)
        if before is None or workload is None:
            result.notes.append("no workload ran at the base; nothing was measured")
            return result

        self.progress("measuring the candidate")
        after, error = self._measure(rev, {**candidate.files, **workload}, plan, test_dir)
        if after is None:
            result.notes.append(f"the candidate broke the workload: {error[-300:]}")
            return result
        self.progress("running the CI test job on both sides")
        image = self.images["python"]
        sides = []
        for files in ({}, candidate.files):
            work = snapshot(self.repo, rev)
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, image)
            sides.append(run_suite(self.runner, work, image, plan, rounds=3))
            discard(work)
        tests, test_notes = classify_tests(sides[0], sides[1])
        stats = judge(before, after)
        improved = stats.improved and tests is not TestOutcome.REGRESSION
        level = (
            EvidenceLevel.FUNCTIONAL_VALIDATION
            if improved and tests in (TestOutcome.PASSED, TestOutcome.PRE_EXISTING)
            else EvidenceLevel.LAB_IMPROVEMENT
            if improved
            else EvidenceLevel.REPRODUCTION
        )
        experiment = Experiment(
            opportunity_id=opp.id,
            base_sha=rev,
            candidate_patch_sha256=candidate.sha256,
            rounds=3,
            baseline_tests=sides[0],
            candidate_tests=sides[1],
            samples_before_ms=before,
            samples_after_ms=after,
            workload_sha256=hashlib.sha256(workload[f"{LAB_DIR}/workload.py"].encode()).hexdigest(),
        )
        reasons = [
            f"{list_endpoint}: median {stats.median_before:.1f} ms → {stats.median_after:.1f} ms "
            f"({stats.effect:.0%} faster), one-sided Mann-Whitney p = {stats.p_value:.2g}, "
            f"95% CI of the median difference [{stats.ci_low:.1f}, {stats.ci_high:.1f}] ms",
            *stats.reasons,
            *(n for n in test_notes if tests is TestOutcome.REGRESSION),
        ]
        verdict = Verdict(
            experiment_id=experiment.id,
            improved=improved,
            evidence_level=level,
            criteria=PERF_CRITERIA,
            tests=tests,
            reasons=reasons,
            caveats=[
                f"{SEED_ROWS} synthetic rows over {SEED_OWNERS} owners, measured in-process in a sandbox; "
                "production effect not yet observed",
                *(n for n in test_notes if tests is not TestOutcome.REGRESSION),
            ],
        )
        self.store.put("experiments", experiment)
        if self.store.path is not None:
            artifacts = self.store.path.parent / "artifacts"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / f"{experiment.id}.patch").write_text(candidate.patch)
            (artifacts / f"{experiment.id}.workload.py").write_text(workload[f"{LAB_DIR}/workload.py"])
        self.store.append_event(
            Event(
                type=EventType.VERDICT_RECORDED,
                actor=ACTOR,
                entity_id=experiment.id,
                correlation_id=opp.id,
                payload={
                    "improved": improved,
                    "level": int(level),
                    "p_value": stats.p_value,
                    "median_before_ms": stats.median_before,
                    "median_after_ms": stats.median_after,
                    "effect": stats.effect,
                    "tests": tests.value,
                },
            )
        )
        result.experiment, result.verdict, result.candidate = experiment, verdict, candidate
        if improved:
            opp.evidence_level = max(opp.evidence_level, level)
            opp.status = OpportunityStatus.EXPERIMENTING
            opp.details = {
                **opp.details,
                "experiment_id": experiment.id,
                "verdict": verdict.model_dump(mode="json"),
                "candidate": {"origin": candidate.origin, "files": candidate.files},
            }
            opp.evidence = [*opp.evidence, EvidenceRef(kind="experiment", locator=experiment.id)]
        else:
            opp.details = {**opp.details, "lab_notes": [*result.notes, *verdict.reasons]}
        opp.updated_at = utc_now()
        self.store.put("opportunities", opp)
        return result
