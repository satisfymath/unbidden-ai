"""Preparation as a capability of the product (campaign to v1.0, C1): from a repository and a mandate to an
isolated copy, the stack with its provenance, the dependency image, the CI's test plan, the project's own checks,
and a record of coverage and blocks. The same code the daemon's `observe.checks` runs; `bench/checks_only.py` and
`bench/level_a.py` call it, so the benchmark measures the product's path, not a second one.

Provisioning (the image: network to the mandate's package registries) and the checks (offline, in the sandbox) stay
apart. A CI step left out says how its function is met. An exit code without a test report is not checks reproduced.
What only a person can give (a credential, a permission) is said as such; a technical choice is made and recorded.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from unbidden.contracts.guardian import Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.lab.testsuite import run_suite, test_plan
from unbidden.observe.stack import detect_stack
from unbidden.sandbox.provision import link_dependencies, provision
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot

CHECKS_TIMEOUT_S = 3600.0


def isolated_copy(source: str, into: Path, rev: str | None) -> tuple[Path, str]:
    """A clone of `source` (a local path, or a URL the mandate's egress allows: checked by the caller) at `rev`
    (a commit, tag or branch; the default branch's head when None), detached. Returns (path, commit)."""
    into.parent.mkdir(parents=True, exist_ok=True)
    if not (into / ".git").exists():
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", source, str(into)], check=True)
    if rev:
        subprocess.run(["git", "-C", str(into), "checkout", "-q", "--detach", rev], check=True)
    commit = subprocess.run(["git", "-C", str(into), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()  # fmt: skip
    return into, commit


def checks_record(repo: Path, rev: str, mandate: Mandate, *, timeout_s: float = CHECKS_TIMEOUT_S) -> dict[str, Any]:
    """The record `observe.checks` keeps: the stack (with why each version was chosen), the image and its notes,
    the plan (its source, scope, what was left out and why), and the checks' outcome with the evidence (tests
    collected, failed, or why none ran). A block is the finding, never an exception."""
    started = time.monotonic()
    record: dict[str, Any] = {"rev": rev}
    try:
        stack = detect_stack(repo, rev)
        if stack.python is None:
            record |= {"status": "out_of_scope", "why": "no Python project at the repository's root",
                       "languages": list(stack.languages), "blind_spots": list(stack.blind_spots)}  # fmt: skip
            record["wall_s"] = round(time.monotonic() - started, 1)
            return record
        py = stack.python
        record["stack"] = {
            "python": py.version, "why": list(py.version_notes), "manifest": py.manifest, "lockfile": py.lockfile,
            "members": list(py.members), "source_roots": list(py.source_roots), "test_paths": list(py.test_paths),
            "extra_requirements": list(py.extra_requirements), "build_writes": list(py.build_writes),
            "blind_spots": list(stack.blind_spots),
        }  # fmt: skip
        image = provision(repo, rev, py, policy=PolicyEngine(mandate))
        record["image"] = {"tag": image.tag, "notes": list(image.notes)}
        plan = test_plan(repo, rev, stack, "python")
        if plan is None:
            record |= {"status": "no_plan", "why": "no test job to run (no CI job and no test files found)"}
        else:
            record["plan"] = {"source": plan.source, "scope": plan.scope, "partial": plan.partial,
                              "notes": list(plan.notes), "services": [s.name for s in plan.services],
                              "command": " ".join(plan.argv)[:2000]}  # fmt: skip
            work = snapshot(repo, rev)
            try:
                link_dependencies(work, image)
                summary = run_suite(SandboxRunner(), work, image, plan, rounds=1, timeout_s=timeout_s)
            finally:
                discard(work)
            ran = summary.status(0)
            record |= {
                "status": ("failed" if summary.failed_per_round[0] else "passed") if ran == "ran" else ran,
                "collected": summary.collected_per_round[0] if summary.collected_per_round else None,
                "failed": summary.failed_per_round[0][:50],
                "why": summary.infra_why[0] if summary.infra_why else None,
                "failures": summary.failure_messages,
                # the environment's, apart from the code's failures: how many tests, which tools the image lacks
                "could_not_run": {
                    "tests": len(summary.could_not_run),
                    "lacks": sorted(set(summary.could_not_run.values())),
                },
            }
    except Exception as exc:  # the environment could not be built: that is the finding
        record |= {"status": "blocked", "why": f"{type(exc).__name__}: {str(exc)[-1500:]}"}
    record["wall_s"] = round(time.monotonic() - started, 1)
    return record


def prepare(source: str, into: Path, mandate: Mandate, rev: str | None = None) -> dict[str, Any]:
    """The ordinary entry: a repository (path or URL), a mandate; an isolated copy and the checks record."""
    repo, commit = isolated_copy(source, into, rev)
    record = checks_record(repo, commit, mandate)
    return {"source": source, "copy": str(repo), **record}
