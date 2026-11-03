"""The dependency lab: a vulnerable package bumped to the lowest version that fixes its advisories, proven by the
advisories gone, none new, and the team's suite with no regression (campaign 13, WS5).

The candidate is the manifest or lock the team keeps, changed the way the team would change it: a pin in a
requirements file is rewritten; a `uv.lock` is re-resolved by `uv lock --upgrade-package` inside a build container
(the only place that reaches a registry, under the same `sandbox.provision` check as every image). The candidate is
committed on a scratch branch only to build its dependency image, then the branch is removed; the suite runs offline
on both sides. Poetry locks and unpinned transitive packages are declared, not guessed.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from unbidden.contracts.common import EvidenceLevel, EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, TestOutcome, Verdict
from unbidden.contracts.metric import ADVISORIES, Measurement, relative
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.guardian.policy import PolicyEngine
from unbidden.lab.evaluator import classify_tests, level_for
from unbidden.lab.fixlab import Candidate, unified_patch
from unbidden.lab.testsuite import run_suite, test_plan
from unbidden.observe.advisories import Fetch, advisory_report, installed, pypi_vulnerabilities
from unbidden.observe.stack import Stack
from unbidden.sandbox.provision import DependencyImage, ProvisionError, link_dependencies, provision
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.store import Store

ACTOR = "lab"
Progress = Callable[[str], None]


@dataclass
class DepsResult:
    experiment: Experiment | None = None
    verdict: Verdict | None = None
    candidate: Candidate | None = None
    notes: list[str] = field(default_factory=list[str])
    blocked: str | None = None
    absent: str | None = None


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def bump_requirements(text: str, package: str, version: str) -> str:
    """A requirements file with `package` pinned to `version`: an existing `==` pin rewritten in place, otherwise a
    line added (a transitive package constrained where the team lists its dependencies)."""
    pattern = re.compile(rf"^(\s*)({'[-_.]'.join(re.escape(p) for p in re.split(r'[-_.]', package))})(\[[^\]]*\])?"
                         r"\s*==\s*[^\s;#]+", re.IGNORECASE | re.MULTILINE)  # fmt: skip
    if pattern.search(text):
        return pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or ''}=={version}", text, count=1)
    return text.rstrip("\n") + f"\n{package}>={version}  # security: known advisories fixed (Unbidden)\n"


def relock_uv(repo: Path, rev: str, files: list[str], package: str, version: str, docker: str = "docker") -> str:
    """`uv.lock` re-resolved with `package` upgraded to `version`, in a build container (registries only)."""
    with tempfile.TemporaryDirectory(prefix="unbidden-relock-") as tmp:
        ctx = Path(tmp)
        for path in files:
            data = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True,
                                  check=True).stdout  # fmt: skip
            (ctx / "p" / path).parent.mkdir(parents=True, exist_ok=True)
            (ctx / "p" / path).write_bytes(data)
        (ctx / "Dockerfile").write_text(
            "FROM python:3.12-slim\nRUN pip install --no-cache-dir uv\nCOPY p/ /p/\nWORKDIR /p\n"
            f"RUN uv lock --upgrade-package '{package}=={version}'\n"
        )
        tag = f"unbidden-relock:{_norm(package)}-{version}".replace("+", "-")[:120]
        built = subprocess.run([docker, "build", "-q", "-t", tag, str(ctx)], capture_output=True, text=True)
        if built.returncode != 0:
            raise ProvisionError(f"uv lock --upgrade-package {package}=={version} failed:\n{built.stderr[-1200:]}")
        out = subprocess.run([docker, "run", "--rm", "--network", "none", tag, "cat", "/p/uv.lock"],
                             capture_output=True, text=True)  # fmt: skip
        subprocess.run([docker, "image", "rm", "-f", tag], capture_output=True, check=False)
        if out.returncode != 0 or not out.stdout:
            raise ProvisionError(f"the re-resolved uv.lock could not be read: {out.stderr[-400:]}")
        return out.stdout


class DepsLab:
    def __init__(
        self,
        repo: Path,
        store: Store,
        stack: Stack,
        image: DependencyImage,
        policy: PolicyEngine,
        *,
        runner: SandboxRunner | None = None,
        progress: Progress = lambda _: None,
        fetch: Fetch = pypi_vulnerabilities,
        rounds: int = 3,
    ) -> None:
        self.repo, self.store, self.stack, self.image, self.policy = repo, store, stack, image, policy
        self.runner = runner or SandboxRunner()
        self.progress, self.fetch, self.rounds = progress, fetch, rounds

    def _candidate(self, rev: str, manifest: str, package: str, version: str) -> dict[str, str]:
        python = self.stack.python
        assert python is not None
        if manifest.endswith(".txt"):
            text = subprocess.run(["git", "-C", str(self.repo), "show", f"{rev}:{manifest}"], capture_output=True,
                                  text=True, check=True).stdout  # fmt: skip
            return {manifest: bump_requirements(text, package, version)}
        if manifest == "uv.lock":
            from unbidden.sandbox.provision import _manifests  # pyright: ignore[reportPrivateUsage]

            files = [f for f in _manifests(self.repo, rev, python) if not f.endswith(".txt") or "requirements" in f]
            return {"uv.lock": relock_uv(self.repo, rev, files, package, version)}
        raise ProvisionError(f"bumping a dependency in {manifest} is not supported yet (declared)")

    async def run(self, opp: Opportunity) -> DepsResult:
        result = DepsResult()
        rev: str = opp.details["rev"]
        first = (opp.details.get("findings") or [{}])[0]
        extra = first.get("extra") or {}
        package, current, fix = extra.get("package"), extra.get("version"), extra.get("lowest_fix")
        targeted = {f["extra"]["advisory"] for f in opp.details.get("findings", []) if f.get("extra")}
        manifest = str(first.get("path") or "")
        if not package or not fix:
            result.blocked = f"no published version of {package} fixes every advisory ({', '.join(sorted(targeted))})"
            return self._done(opp, result)
        self.progress(f"bumping {package} {current} → {fix} in {manifest}")
        try:
            files = self._candidate(rev, manifest, package, fix)
        except (ProvisionError, subprocess.CalledProcessError) as exc:
            result.blocked = f"cannot write the bump: {str(exc)[-400:]}"
            return self._done(opp, result)
        base_tree = snapshot(self.repo, rev)
        candidate = Candidate("rule", files, unified_patch(base_tree, files))
        discard(base_tree)
        result.candidate = candidate

        from unbidden.publish.git_writer import commit_files

        branch = f"unbidden/lab-deps-{opp.id}-{utc_now():%Y%m%d%H%M%S}"
        sha = commit_files(self.repo, rev, files, f"lab: {package} {fix}", branch)
        try:
            self.progress("building the candidate's dependency image")
            try:
                image = provision(self.repo, sha, self.stack.part("python"), policy=self.policy)
            except ProvisionError as exc:
                result.blocked = f"the bumped dependencies do not install: {str(exc)[-400:]}"
                return self._done(opp, result)
            after = installed(self.runner, self.repo, sha, image)
            report = advisory_report(after or [], manifest, self.fetch)
            remaining = {str(f.extra.get("advisory")) for f in report.findings}
            before_all = {f["extra"]["advisory"] for f in opp.details.get("all_advisories", [])} or targeted
            plan = test_plan(self.repo, rev, self.stack, "python")
            sides = []
            if plan is not None:
                for side_rev, side_image in ((rev, self.image), (sha, image)):
                    self.progress(f"running the test suite on the {'base' if side_rev == rev else 'candidate'}")
                    work = snapshot(self.repo, side_rev)
                    try:
                        link_dependencies(work, side_image)
                        sides.append(run_suite(self.runner, work, side_image, plan, rounds=self.rounds))
                    finally:
                        discard(work)
        finally:
            subprocess.run(["git", "-C", str(self.repo), "branch", "-D", branch], capture_output=True, check=False)
        tests, notes = classify_tests(sides[0], sides[1]) if len(sides) == 2 else (TestOutcome.INCONCLUSIVE, [])
        gone = targeted - remaining
        new = remaining - before_all - targeted
        clean = after is not None and report.can_resolve and gone == targeted and not new
        improved = clean and tests is not TestOutcome.REGRESSION
        level = level_for(improved, tests, suite_ran=len(sides) == 2)
        base_n, head_n = float(len(targeted)), float(len(targeted & remaining) + len(new))
        experiment = Experiment(
            opportunity_id=opp.id, base_sha=rev, candidate_patch_sha256=candidate.sha256, rounds=self.rounds,
            baseline_tests=sides[0] if sides else None, candidate_tests=sides[1] if len(sides) == 2 else None,
            findings_before=sorted(targeted), findings_after=sorted(remaining),
        )  # fmt: skip
        reasons = [f"{package} {current} → {fix}: advisories {', '.join(sorted(gone)) or 'none'} gone"]
        if new:
            reasons.append(f"new advisories with the bump: {', '.join(sorted(str(n) for n in new))}")
        if not report.can_resolve:
            reasons.append(f"the advisories at the candidate could not all be read: {report.error}")
        verdict = Verdict(
            experiment_id=experiment.id, improved=improved,
            evidence_level=level if improved else EvidenceLevel.REPRODUCTION,
            criteria={"check": "every targeted advisory gone, none new, the team's suite with no regression",
                      "suite_rounds": self.rounds},
            tests=tests, reasons=[*reasons, *(notes if tests is TestOutcome.REGRESSION else [])],
            caveats=[f"lookup: PyPI's advisory data at {utc_now():%Y-%m-%d}", *(n for n in notes
                     if tests is not TestOutcome.REGRESSION)],
            measurements=[Measurement(metric=ADVISORIES, base=base_n, head=head_n,
                                      effect=relative(base_n, head_n, "lower"), met=improved)],
        )  # fmt: skip
        experiment.measurements = verdict.measurements
        result.experiment, result.verdict = experiment, verdict
        self.store.put("experiments", experiment)
        self.store.append_event(
            Event(type=EventType.VERDICT_RECORDED, actor=ACTOR, entity_id=experiment.id, correlation_id=opp.id,
                  payload={"improved": improved, "level": int(verdict.evidence_level), "tests": tests.value,
                           "reasons": verdict.reasons, "origin": "rule"})
        )  # fmt: skip
        return self._done(opp, result)

    def _done(self, opp: Opportunity, result: DepsResult) -> DepsResult:
        if result.verdict is not None and result.verdict.improved:
            opp.evidence_level = max(opp.evidence_level, result.verdict.evidence_level)
            opp.status = OpportunityStatus.EXPERIMENTING
            opp.details = {
                **opp.details,
                "experiment_id": result.experiment.id if result.experiment else None,
                "verdict": result.verdict.model_dump(mode="json"),
                "candidate": {"origin": "rule", "files": result.candidate.files if result.candidate else {}},
            }
            if result.experiment is not None:
                opp.evidence = [*opp.evidence, EvidenceRef(kind="experiment", locator=result.experiment.id)]
        else:
            opp.details = {**opp.details, "lab_notes": [*result.notes, *([result.blocked] if result.blocked else [])]}
        opp.updated_at = utc_now()
        self.store.put("opportunities", opp)
        return result
