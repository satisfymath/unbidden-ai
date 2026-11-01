"""Measure a recorded performance candidate again under criteria v3, from its saved workload and patch; no model.

    uv run python -m bench.perf_v3_replay <repo> <rev> <workload.py> --name NAME --out DIR
        [--patch exp.patch | --index TABLE.COLUMN | --no-change] [--expect-index TABLE.COLUMN]

The candidate is the files a saved patch adds (`--patch`), an index written by Unbidden's own rule on any column
(`--index`, for an irrelevant-candidate control), or nothing (`--no-change`, the A/A control). `--expect-index` is
the mechanism the verdict checks (the index the finding asks for). The lab's own code measures: `_sessions` (four
sessions per side, alternating, each a fresh database), the CI test job three rounds per side, `judge_sessions`.
Everything is written raw to `<out>/<name>.json`; no store, opportunity or original record is touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.lab.evaluator import classify_tests, level_for
from unbidden.lab.perf import LAB_DIR, PerfLab, _mechanism, alembic_head, async_suite, index_candidate
from unbidden.lab.perfstats import SESSION_CRITERIA, judge_sessions
from unbidden.lab.testsuite import run_suite, test_plan
from unbidden.observe.stack import detect_stack
from unbidden.sandbox.provision import link_dependencies, provision
from unbidden.sandbox.runner import discard, snapshot
from unbidden.store import Store


def added_files(patch: str) -> dict[str, str]:
    """The files a patch of new files adds (the lab's candidates are new migrations)."""
    out: dict[str, str] = {}
    for block in re.split(r"^--- ", patch, flags=re.M)[1:]:
        target = re.search(r"^\+\+\+ b/(\S+)", block, re.M)
        if target is None:
            continue
        body = block.split("\n@@", 1)[1].split("\n", 1)[1] if "\n@@" in block else ""
        out[target.group(1)] = "".join(line[1:] + "\n" for line in body.splitlines() if line.startswith("+"))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("rev")
    parser.add_argument("workload")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--patch")
    group.add_argument("--index")
    group.add_argument("--no-change", action="store_true")
    parser.add_argument("--expect-index")
    args = parser.parse_args()
    repo, out = Path(args.repo).expanduser(), Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    rev = subprocess.run(["git", "-C", str(repo), "rev-parse", args.rev], capture_output=True, text=True,
                         check=True).stdout.strip()  # fmt: skip
    show = lambda path: subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True,  # noqa: E731
                                       text=True, check=True).stdout  # fmt: skip
    if args.patch:
        candidate = added_files(Path(args.patch).read_text())
    elif args.index:
        table, column = args.index.split(".")
        head = alembic_head(repo, rev)
        assert head is not None
        candidate = index_candidate(show, table, column, head[2], head, model=False) or {}
    else:
        candidate = {}
    workload_text = Path(args.workload).read_text()
    workload = {f"{LAB_DIR}/workload.py": workload_text}
    mandate = Mandate(workspace="replay")
    mandate.autonomy.provision_dependencies = Autonomy.ALLOW
    mandate.egress.package_registries = ["pypi.org", "files.pythonhosted.org", "deb.debian.org"]
    stack = detect_stack(repo, rev)
    images = {"python": provision(repo, rev, stack.part("python"), policy=PolicyEngine(mandate))}
    store = Store(out / f"{args.name}.state.db")
    lab = PerfLab(repo, None, store, stack, images)  # type: ignore[arg-type]  # no model: nothing is written by one
    files = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", rev], capture_output=True,
                           text=True, check=True).stdout.splitlines()  # fmt: skip
    lab.marker = async_suite(show, files)
    plan = test_plan(repo, rev, stack, "python")
    assert plan is not None
    test_dir = stack.python.test_paths[0] if stack.python and stack.python.test_paths else "tests"
    expect = tuple(args.expect_index.split(".")) if args.expect_index else None
    sessions, error = lab._sessions(rev, candidate, workload, plan, test_dir, expect, args.name)  # pyright: ignore[reportPrivateUsage]
    report: dict[str, object] = {
        "name": args.name, "rev": rev, "candidate_files": sorted(candidate),
        "candidate_sha256": hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest(),
        "workload_sha256": hashlib.sha256(workload_text.encode()).hexdigest(), "image": images["python"].tag,
        "criteria": SESSION_CRITERIA, "sessions": sessions, "error": error[-600:],
    }  # fmt: skip
    if sessions is not None:
        sides = []
        for overlay in ({}, candidate):
            work = snapshot(repo, rev)
            for path, content in overlay.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, images["python"])
            sides.append(run_suite(lab.runner, work, images["python"], plan, rounds=3))
            discard(work)
        tests, notes = classify_tests(sides[0], sides[1])
        mechanism, note = _mechanism(sessions, expect)  # type: ignore[arg-type]
        base = [s["median_ms"] for s in sessions if s["arm"] == "base"]
        cand = [s["median_ms"] for s in sessions if s["arm"] == "candidate"]
        judged = judge_sessions(base, cand, mechanism=mechanism, mechanism_note=note)
        report |= {
            "tests": tests.value, "test_notes": notes[:10], "suite": [s.model_dump(mode="json") for s in sides],
            "outcome": judged.outcome, "reasons": judged.reasons, "effect": judged.effect,
            "p_faster": judged.p_faster, "p_slower": judged.p_slower,
            "level": int(level_for(judged.improved, tests, suite_ran=True)),
        }  # fmt: skip
    (out / f"{args.name}.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: report.get(k) for k in ("name", "outcome", "effect", "p_faster", "tests", "level",
                                                  "reasons", "error")}, default=str))  # fmt: skip


if __name__ == "__main__":
    main()
