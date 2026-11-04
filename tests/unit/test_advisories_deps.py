"""Campaign 13, WS5: known vulnerabilities in what a project installs become security opportunities, and the
dependency lab proves a bump: the advisories gone, none new, the team's suite with no regression."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.experiment import TestSummary
from unbidden.contracts.opportunity import Opportunity
from unbidden.lab import deps as deps_mod
from unbidden.lab.deps import DepsLab, bump_requirements
from unbidden.observe.advisories import TOOL, advisory_report, lowest_fix
from unbidden.observe.analyzers import record_report
from unbidden.observe.stack import detect_stack
from unbidden.sandbox.provision import DependencyImage, ProvisionError
from unbidden.sandbox.runner import SandboxResult, SandboxSpec
from unbidden.store import Store

pytestmark = pytest.mark.unit

ADVISORY = {"id": "GHSA-xxxx", "aliases": ["CVE-2024-1"], "fixed_in": ["2.32.0", "3.0.0"], "summary": "leaks auth"}


def fetch(name: str, version: str) -> list[dict[str, Any]] | None:
    if name == "requests" and version == "2.31.0":
        return [ADVISORY]
    return []


def test_advisories_are_one_finding_each_grouped_per_package_with_the_lowest_fix(store: Store) -> None:
    assert lowest_fix([ADVISORY], "2.31.0") == "2.32.0"
    assert lowest_fix([{"id": "x", "fixed_in": []}], "1.0") is None
    assert lowest_fix([ADVISORY, {"id": "y", "fixed_in": []}], "2.31.0") == "2.32.0"  # the unfixed one stays apart
    report = advisory_report([("requests", "2.31.0"), ("idna", "3.7")], "requirements.txt", fetch)
    assert report.can_resolve and len(report.findings) == 1
    finding = report.findings[0]
    assert finding.category == "security" and finding.rule == "requests" and finding.extra["lowest_fix"] == "2.32.0"
    assert "CVE-2024-1" in finding.message and "fixed in 2.32.0, 3.0.0" in finding.message
    (opp,) = record_report(store, report, "a" * 40).opened
    assert opp.source == TOOL and opp.category == "security"
    unanswered = advisory_report([("requests", "2.31.0")], "requirements.txt", lambda n, v: None)
    assert not unanswered.can_resolve and "did not answer" in (unanswered.error or "")


def test_a_pin_is_rewritten_and_a_transitive_package_is_constrained() -> None:
    text = "flask==3.0.0\nRequests[socks]==2.31.0  # http\n"
    assert bump_requirements(text, "requests", "2.32.0") == "flask==3.0.0\nRequests[socks]==2.32.0  # http\n"
    added = bump_requirements("flask==3.0.0\n", "urllib3", "2.2.2")
    assert added.endswith("urllib3>=2.2.2  # security: known advisories fixed (Unbidden)\n")


class Runner:
    """Lists the installed packages by the requirements in the work tree; the suite passes on both sides."""

    def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
        if spec.argv[:2] == ["/deps/.venv/bin/python", "-c"]:
            pins = (work / "requirements.txt").read_text()
            version = "2.32.0" if "requests==2.32.0" in pins else "2.31.0"
            return SandboxResult(0, json.dumps([["requests", version], ["flask", "3.0.0"]]), "", False, 0.1, False,
                                 False)  # fmt: skip
        return SandboxResult(0, "", "", False, 0.1, False, False)


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "app"
    (repo / "tests").mkdir(parents=True)
    (repo / "requirements.txt").write_text("flask==3.0.0\nrequests==2.31.0\n")
    (repo / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    rev = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return repo, rev


async def test_the_dependency_lab_proves_a_bump(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mandate: Any
) -> None:
    from unbidden.guardian.policy import PolicyEngine

    repo, rev = _repo(tmp_path)
    image = DependencyImage(tag="deps", language="python", registries=[], env={}, links={})
    monkeypatch.setattr(deps_mod, "provision", lambda *a, **k: image)
    suite = TestSummary(rounds=1, failed_per_round=[[]], round_status=["ran"], collected_per_round=[1])
    monkeypatch.setattr(deps_mod, "run_suite", lambda *a, **k: suite)
    report = advisory_report([("requests", "2.31.0")], "requirements.txt", fetch)
    (opp,) = record_report(store, report, rev).opened
    lab = DepsLab(repo, store, detect_stack(repo, rev), image, PolicyEngine(mandate), runner=Runner(),  # type: ignore[arg-type]
                  fetch=fetch, rounds=1)  # fmt: skip
    result = await lab.run(opp)
    assert result.verdict is not None and result.verdict.improved, result
    assert result.candidate is not None and "requests==2.32.0" in result.candidate.files["requirements.txt"]
    (m,) = result.verdict.measurements
    assert (m.metric.name, m.base, m.head, m.met) == ("advisories", 1.0, 0.0, True)
    kept = store.get("opportunities", opp.id, Opportunity)
    assert kept is not None and kept.details["candidate"]["origin"] == "rule"
    branches = subprocess.run(["git", "-C", str(repo), "branch"], capture_output=True, text=True).stdout
    assert "lab-deps" not in branches  # the scratch branch is gone


async def test_no_published_fix_is_a_declared_block(store: Store, tmp_path: Path, mandate: Any) -> None:
    from unbidden.guardian.policy import PolicyEngine

    repo, rev = _repo(tmp_path)
    image = DependencyImage(tag="deps", language="python", registries=[], env={}, links={})
    nofix = lambda n, v: [{"id": "PYSEC-1", "fixed_in": []}] if n == "requests" else []  # noqa: E731
    (opp,) = record_report(store, advisory_report([("requests", "2.31.0")], "requirements.txt", nofix), rev).opened
    result = await DepsLab(repo, store, detect_stack(repo, rev), image, PolicyEngine(mandate), runner=Runner(),  # type: ignore[arg-type]
                           fetch=nofix).run(opp)  # fmt: skip
    assert result.verdict is None and result.blocked and "no published version of requests fixes" in result.blocked


def test_a_security_opportunity_and_its_pull_request_say_what_they_are(store: Store) -> None:
    from unbidden.contracts.common import EvidenceLevel
    from unbidden.contracts.experiment import TestOutcome, Verdict
    from unbidden.publish.proposal import proposal_title

    (opp,) = record_report(store, advisory_report([("requests", "2.31.0")], "requirements.txt", fetch), "a" * 40).opened
    assert opp.title == "requests 2.31.0: 1 known vulnerability, fixed in 2.32.0"
    verdict = Verdict(experiment_id="e", improved=True, evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
                      criteria={}, tests=TestOutcome.PASSED,
                      reasons=["requests 2.31.0 → 2.32.0: advisories GHSA-xxxx gone"])  # fmt: skip
    assert proposal_title(opp, verdict) == "fix(deps): bump requests 2.31.0 → 2.32.0 (security)"


def test_a_requirement_in_pyproject_is_raised_to_the_fixed_version() -> None:
    """pyjwt, campaign 13: pytest's advisory was found, but pyproject.toml could not be bumped."""
    from unbidden.lab.deps import bump_pyproject

    text = '[project]\noptional-dependencies.dev = [\n    "pytest>=8.4.2,<9.0.0",\n]\n[dependency-groups]\n' \
        'test = ["Pytest[extra]>=8,<10,!=9.0.1 ; python_version >= \'3.9\'", "pytest-cov"]\n'  # fmt: skip
    out = bump_pyproject(text, "pytest", "9.0.3")
    assert out is not None and '"pytest>=9.0.3"' in out and "pytest-cov" in out
    assert "\"Pytest[extra]>=9.0.3,<10,!=9.0.1 ; python_version >= '3.9'\"" in out
    assert bump_pyproject(text, "urllib3", "2.5.0") is None


async def test_beside_a_ci_jobs_environment_the_bump_is_read_from_unbiddens_own(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mandate: Any
) -> None:
    """marshmallow, campaign 13: the advisories were gone and the suite passed, yet "no proven fix": the candidate's
    packages were read from the CI job's image, which has no `/deps/.venv`. Unread is now said, never a silent no."""
    from dataclasses import replace

    from unbidden.guardian.policy import PolicyEngine

    repo, rev = _repo(tmp_path)
    own = DependencyImage(tag="deps", language="python", registries=[], env={}, links={})
    ci = DependencyImage(tag="ci", language="python", registries=[], env={}, links={}, runner_like=True, own=own)
    read: list[str] = []

    class Seen(Runner):
        def run(self, spec: SandboxSpec, work: Path) -> SandboxResult:
            read.append(spec.image)
            return super().run(spec, work)

    monkeypatch.setattr(deps_mod, "provision", lambda *a, **k: ci)
    suite = TestSummary(rounds=1, failed_per_round=[[]], round_status=["ran"], collected_per_round=[1])
    monkeypatch.setattr(deps_mod, "run_suite", lambda *a, **k: suite)
    report = advisory_report([("requests", "2.31.0")], "requirements.txt", fetch)
    (opp,) = record_report(store, report, rev).opened
    lab = DepsLab(repo, store, detect_stack(repo, rev), ci, PolicyEngine(mandate), runner=Seen(),  # type: ignore[arg-type]
                  fetch=fetch, rounds=1)  # fmt: skip
    result = await lab.run(opp)
    assert result.verdict is not None and result.verdict.improved and set(read) == {"deps"}, (result, read)
    monkeypatch.setattr(deps_mod, "provision", lambda *a, **k: replace(ci, own=None))
    result = await DepsLab(repo, store, detect_stack(repo, rev), ci, PolicyEngine(mandate), runner=Seen(),  # type: ignore[arg-type]
                           fetch=fetch, rounds=1).run(opp)  # fmt: skip
    assert result.verdict is not None and not result.verdict.improved
    assert any("could not be read" in r for r in result.verdict.reasons)


def test_the_relock_builds_from_the_whole_tree(tmp_path: Path) -> None:
    """sqlmodel, campaign 13: with only the manifests copied, its build backend (pdm) failed on `license-files`, so
    every `uv lock --upgrade-package` failed. The relock's build context now holds the whole tree at the commit."""
    from unbidden.lab.deps import relock_uv

    repo, rev = _repo(tmp_path)
    (repo / "LICENSE").write_text("MIT\n")
    (repo / "uv.lock").write_text("version = 1\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "lock"], check=True)
    rev = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  build) for a; do ctx="$a"; done; test -f "$ctx/p/LICENSE" && test -f "$ctx/p/tests/test_a.py" || exit 1;;\n'
        '  run) echo "relocked";;\n'
        "esac\n"
    )
    docker.chmod(0o755)
    assert relock_uv(repo, rev, ["uv.lock"], "requests", "2.32.0", docker=str(docker)).strip() == "relocked"


async def test_another_packages_standing_advisories_are_not_new_with_the_bump(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mandate: Any
) -> None:
    """marshmallow, campaign 13: certifi's fix was declined because virtualenv's standing advisories, there before the
    bump, were counted as new with it."""
    from unbidden.guardian.policy import PolicyEngine

    flask_advisory = {**ADVISORY, "id": "GHSA-flask-0000", "aliases": [], "fixed_in": ["3.1.0"]}

    def both(name: str, version: str) -> list[dict[str, Any]] | None:
        return fetch(name, version) or ([flask_advisory] if name == "flask" else [])

    repo, rev = _repo(tmp_path)
    image = DependencyImage(tag="deps", language="python", registries=[], env={}, links={})
    monkeypatch.setattr(deps_mod, "provision", lambda *a, **k: image)
    suite = TestSummary(rounds=1, failed_per_round=[[]], round_status=["ran"], collected_per_round=[1])
    monkeypatch.setattr(deps_mod, "run_suite", lambda *a, **k: suite)
    report = advisory_report([("requests", "2.31.0")], "requirements.txt", fetch)
    (opp,) = record_report(store, report, rev).opened
    lab = DepsLab(repo, store, detect_stack(repo, rev), image, PolicyEngine(mandate), runner=Runner(),  # type: ignore[arg-type]
                  fetch=both, rounds=1)  # fmt: skip
    result = await lab.run(opp)
    assert result.verdict is not None and result.verdict.improved, result.verdict
    assert not any("new advisories" in r for r in result.verdict.reasons)


def test_a_failed_relock_says_uvs_own_reason(tmp_path: Path) -> None:
    """harlequin, final pass 0.18.5: the recorded reason was only "did not complete successfully"; uv had said that
    git was missing for a git source. Its `error:` and `cause:` lines are kept."""
    from unbidden.lab.deps import relock_uv

    repo, rev = _repo(tmp_path)
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'echo "#9 1.49 error: Failed to download and build pkg" >&2\n'
        'echo "#9 1.49   cause: Git executable not found." >&2\n'
        'echo "#9 ERROR: process did not complete successfully: exit code: 1" >&2\n'
        "exit 1\n"
    )
    docker.chmod(0o755)
    with pytest.raises(ProvisionError) as raised:
        relock_uv(repo, rev, ["requirements.txt"], "requests", "2.32.0", docker=str(docker))
    assert "Git executable not found" in str(raised.value)


def test_every_pull_request_title_is_a_conventional_commit() -> None:
    """aegra, final pass 0.18.6: its CI lints pull request titles; `security:` is no Conventional Commits type."""
    import re

    from unbidden.contracts.common import EvidenceLevel, EvidenceRef
    from unbidden.contracts.experiment import TestOutcome, Verdict
    from unbidden.publish.proposal import proposal_title

    kinds = r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([\w-]+\))?!?: \S"
    verdict = Verdict(
        experiment_id="e",
        improved=True,
        evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
        criteria={},
        tests=TestOutcome.PASSED,
        reasons=["certifi 1 → 2: advisories X gone"],
    )
    evidence = [EvidenceRef(kind="analyzer_report", locator="x")]
    for source, category in (("pypi-advisories", "security"), ("repair", "bugs"), ("ruff", "lint")):
        opp = Opportunity(
            source=source, category=category, title="t", summary="s", dedup_key=source, details={}, evidence=evidence
        )
        assert re.match(kinds, proposal_title(opp, verdict)), proposal_title(opp, verdict)
