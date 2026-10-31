"""Preparation and the project's own checks only, as `observe.checks` makes them, before any full agent cycle.

    uv run --project <frozen worktree> python -m bench.checks_only <repo> <rev> [--registries a,b] --out FILE

The stack detected, the dependency image provisioned under a lab mandate (package registries only), the CI's test
plan read and run for one round in the sandbox, offline, with its services; the record `observe.checks` would keep
(status, tests collected, failed, why, scope, notes, command), and the image's notes. No model is called, nothing is
stored in a workspace. A regression tool of stage 10: the frozen evaluation's checks were never reproduced.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.lab.testsuite import run_suite, test_plan
from unbidden.observe.stack import detect_stack
from unbidden.sandbox.provision import link_dependencies, provision
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot

CHECKS_TIMEOUT_S = 3600


def checks(repo: Path, rev: str, registries: list[str]) -> dict[str, object]:
    """The record `observe.checks` would keep for `repo` at `rev`, from a lab mandate allowing `registries`."""
    started = time.monotonic()
    mandate = Mandate(workspace="checks")
    mandate.autonomy.provision_dependencies = Autonomy.ALLOW
    mandate.egress.package_registries = registries
    record: dict[str, object] = {"repo": str(repo), "rev": rev}
    try:
        stack = detect_stack(repo, rev)
        if stack.python is None:
            record |= {"status": "out_of_scope", "why": "no Python stack detected at the root"}
            record["wall_s"] = round(time.monotonic() - started, 1)
            return record
        image = provision(repo, rev, stack.part("python"), policy=PolicyEngine(mandate))
        record |= {"image": image.tag, "image_notes": list(image.notes), "python": stack.python.version,
                   "blind_spots": list(stack.blind_spots)}  # fmt: skip
        plan = test_plan(repo, rev, stack, "python")
        if plan is None:
            record |= {"status": "no_plan", "why": "no test job to run (no CI job and no test files found)"}
        else:
            work = snapshot(repo, rev)
            try:
                link_dependencies(work, image)
                summary = run_suite(SandboxRunner(), work, image, plan, rounds=1, timeout_s=CHECKS_TIMEOUT_S)
            finally:
                discard(work)
            ran = summary.status(0)
            record |= {
                "status": ("failed" if summary.failed_per_round[0] else "passed") if ran == "ran" else ran,
                "collected": summary.collected_per_round[0] if summary.collected_per_round else None,
                "failed": summary.failed_per_round[0][:50], "why": summary.infra_why[0] if summary.infra_why else None,
                "command": " ".join(plan.argv)[:2000], "source": plan.source, "scope": plan.scope,
                "partial": plan.partial, "notes": list(plan.notes),
            }  # fmt: skip
    except Exception as exc:  # the environment could not be built: that is the finding, as in observe.checks
        record |= {"status": "blocked", "why": f"{type(exc).__name__}: {str(exc)[-1500:]}"}
    record["wall_s"] = round(time.monotonic() - started, 1)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("rev")
    parser.add_argument("--registries", default="pypi.org,files.pythonhosted.org,deb.debian.org,registry.npmjs.org")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    record = checks(Path(args.repo).expanduser(), args.rev, args.registries.split(","))
    Path(args.out).write_text(json.dumps(record, indent=1, default=str))
    print(json.dumps({k: record.get(k) for k in ("status", "collected", "why", "scope")}, default=str)[:1500])


if __name__ == "__main__":
    main()
