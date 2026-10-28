"""Measure a recorded performance change again with today's lab and evaluator, from its saved workload and commits.

    uv run python -m bench.revalidate_perf <repo> <base> <candidate> <workload.py> --workspace <dir> --linked <exp id>

The workload is the file the original experiment recorded (its SHA-256 is printed, to compare with the record); the
candidate is the files the candidate commit changes, laid over the base, as the lab lays a patch. The fixed driver
measures both sides; the team's CI test job runs 3 rounds on each side; the current `classify_tests`, `judge` and
`level_for` decide. A new experiment and verdict are written to the workspace's store, linked to the original by
`provenance.revalidates`. Nothing of the original record is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, Verdict
from unbidden.guardian.policy import PolicyEngine
from unbidden.lab.evaluator import classify_tests, level_for
from unbidden.lab.perf import LAB_DIR, PerfLab
from unbidden.lab.perfstats import PERF_CRITERIA, judge
from unbidden.lab.testsuite import run_suite, test_plan
from unbidden.observe.stack import detect_stack
from unbidden.provenance import provenance
from unbidden.sandbox.provision import link_dependencies, provision
from unbidden.sandbox.runner import discard, snapshot
from unbidden.workspace import Workspace


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("repo", "base", "candidate", "workload"):
        parser.add_argument(name)
    parser.add_argument("--workspace", required=True, help="repository whose workspace records it")
    parser.add_argument("--linked", required=True, help="the experiment this re-measures")
    args = parser.parse_args()
    repo, base = Path(args.repo).expanduser(), _git(Path(args.repo).expanduser(), "rev-parse", args.base).strip()
    candidate = _git(repo, "rev-parse", args.candidate).strip()
    workspace = Workspace(Path(args.workspace).expanduser())
    store, mandate = workspace.store(), workspace.mandate()
    workload_text = Path(args.workload).read_text()
    workload = {f"{LAB_DIR}/workload.py": workload_text}
    changed = _git(repo, "diff", "--name-only", base, candidate).split()
    files = {path: _git(repo, "show", f"{candidate}:{path}") for path in changed}
    stack = detect_stack(repo, base)
    images = {"python": provision(repo, base, stack.part("python"), policy=PolicyEngine(mandate))}
    lab = PerfLab(repo, None, store, stack, images)  # type: ignore[arg-type]  # no model: nothing is written here
    plan = test_plan(repo, base, stack, "python")
    assert plan is not None
    test_dir = stack.python.test_paths[0] if stack.python and stack.python.test_paths else "tests"
    before, error_b = lab._measure(base, workload, plan, test_dir)  # pyright: ignore[reportPrivateUsage]
    after, error_a = lab._measure(base, {**files, **workload}, plan, test_dir)  # pyright: ignore[reportPrivateUsage]
    sides = []
    for overlay in ({}, files):
        work = snapshot(repo, base)
        for path, content in overlay.items():
            (work / path).write_text(content)
        link_dependencies(work, images["python"])
        sides.append(run_suite(lab.runner, work, images["python"], plan, rounds=3))
        discard(work)
    tests, notes = classify_tests(sides[0], sides[1])
    report: dict[str, object] = {
        "base": base, "candidate": candidate, "changed": changed,
        "workload_sha256": hashlib.sha256(workload_text.encode()).hexdigest(),
        "image": images["python"].tag, "engine": lab.engine, "tests": tests.value, "test_notes": notes[:10],
        "suite": [s.model_dump(mode="json") for s in sides],
        "measured": {"before": before is not None, "after": after is not None,
                     "errors": [error_b[-400:], error_a[-400:]]},
    }  # fmt: skip
    if before is not None and after is not None:
        stats = judge(before, after)
        level = level_for(stats.improved, tests, suite_ran=True)
        experiment = Experiment(
            opportunity_id=_opportunity(store, args.linked), base_sha=base,
            candidate_patch_sha256=hashlib.sha256(_git(repo, "diff", base, candidate).encode()).hexdigest(),
            rounds=3, baseline_tests=sides[0], candidate_tests=sides[1], samples_before_ms=before,
            samples_after_ms=after, workload_sha256=str(report["workload_sha256"]),
            provenance={**provenance(None, list(images.values()), engine=lab.engine), "revalidates": args.linked,
                        "candidate_commit": candidate},
        )  # fmt: skip
        verdict = Verdict(
            experiment_id=experiment.id, improved=stats.improved, evidence_level=level, criteria=PERF_CRITERIA,
            tests=tests, reasons=[f"median {stats.median_before:.1f} ms -> {stats.median_after:.1f} ms, "
                                  f"p = {stats.p_value:.2g}", *stats.reasons],
            caveats=[f"re-measures {args.linked} with its saved workload and today's evaluator", *notes[:5]],
        )  # fmt: skip
        store.put("experiments", experiment)
        store.append_event(
            Event(
                type=EventType.VERDICT_RECORDED,
                actor="lab",
                entity_id=experiment.id,
                correlation_id=experiment.opportunity_id,
                payload=verdict.model_dump(mode="json"),
            )
        )
        report["verdict"] = verdict.model_dump(mode="json")
        report |= {"experiment": experiment.id, "improved": stats.improved, "level": int(level),
                   "median_before_ms": stats.median_before, "median_after_ms": stats.median_after,
                   "p_value": stats.p_value}  # fmt: skip
    print(json.dumps(report, indent=2, default=str))


def _opportunity(store: object, experiment_id: str) -> str:
    found = store.get("experiments", experiment_id, Experiment)  # type: ignore[attr-defined]
    return found.opportunity_id if found is not None else "unknown"


if __name__ == "__main__":
    main()
