"""The evaluator's controls before the freeze (stage 10): perf-v4's seven cases measured on a real application.

    uv run --project <frozen worktree> python -m bench.promotion_cases --repo <fst clone> --rev f4bcfab \
        --workload <saved workload.py> --patch <saved index patch> --out DIR [--case NAME ...]

Each case is one of `tests/unit/test_promotion.py` (D-060), here with real sessions instead of numbers: the lab's own
measurement (`PerfLab._measure`, `_sessions`) and its own judgment (`PerfLab.judge_v4`: mechanism, functional
comparison, A/A control and confirmation), on full-stack-fastapi-template at its pinned commit, no model. The
candidates are written by the evaluator, not by Unbidden: the saved index patch, an index on a column the listing
does not filter by, nothing, and small edits of the listing's handler (a delay, a dropped item). A case passes when
its outcome is the one its unit test asserts. The project's CI tests are not run here: they are not part of the
promotion's judgment, and each experiment of the evaluation runs them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.lab.perf import LAB_DIR, PROMOTION_CRITERIA, PerfLab, alembic_head, async_suite, index_candidate
from unbidden.lab.testsuite import test_plan
from unbidden.observe.stack import detect_stack
from unbidden.sandbox.provision import provision
from unbidden.store import Store

ROUTE = "backend/app/api/routes/items.py"
DOCSTRING = '    """\n    Retrieve items.\n    """\n'
LISTED = "    items_public = [ItemPublic.model_validate(item) for item in items]\n"


@dataclass
class Case:
    name: str
    unit_test: str  # the test of tests/unit/test_promotion.py this case measures for real
    expected: str  # what that test asserts, in words
    passes: Callable[[str, list[str], list[dict[str, Any]]], bool]  # outcome, reasons, first sessions
    candidate: dict[str, str] = field(default_factory=dict[str, str])
    base: dict[str, str] = field(default_factory=dict[str, str])  # an overlay both arms get (the near-threshold case)
    index: tuple[str, str] | None = ("item", "owner_id")  # the mechanism the verdict checks
    workload: str | None = None  # another workload than the saved one


def patched(repo: Path, rev: str, patch: str) -> dict[str, str]:
    """The files a saved patch writes, whole: applied with `git apply` to the commit's own files (v3's `added_files`
    kept only a patch's added lines, which broke a modified file: stage 10's first control run)."""
    import re
    import tempfile

    touched = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for path in touched:
            shown = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True)
            if shown.returncode == 0:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(shown.stdout)
        subprocess.run(["git", "apply", "-"], input=patch, text=True,
                       cwd=root, check=True, capture_output=True)  # fmt: skip
        return {path: (root / path).read_text() for path in touched}


def _unused(sessions: list[dict[str, Any]]) -> bool:
    scans = [s.get("index_scans") for s in sessions if s["arm"] == "candidate"]
    return bool(scans) and all(x == 0 for x in scans)


def _delay(route: str, seconds: float) -> str:
    assert DOCSTRING in route
    return route.replace(DOCSTRING, f"{DOCSTRING}    import time\n\n    time.sleep({seconds})\n", 1)


def cases(
    show: Callable[[str], str], rev_head: tuple[str, str, str], patch: dict[str, str], workload: str
) -> list[Case]:
    route = show(ROUTE)
    assert LISTED in route
    irrelevant = index_candidate(show, "item", "title", rev_head[2], rev_head, model=False) or {}
    wrong = {**patch, ROUTE: route.replace(LISTED, "    items = items[1:]\n" + LISTED, 1)}
    superuser = workload.replace("headers = normal_user_token_headers", "headers = superuser_token_headers")
    superuser = superuser.replace("def build(client, db, normal_user_token_headers)",
                                  "def build(client, db, superuser_token_headers)")  # fmt: skip
    assert superuser != workload
    return [
        Case(
            "real_improvement",
            "test_a_real_improvement_with_its_mechanism_function_control_and_confirmation_is_promoted",
            "improved",
            lambda o, r, s: o == "improved",
            candidate=patch,
        ),
        Case(
            "unchanged",
            "test_the_unchanged_candidate_is_no_relevant_change",
            "no_relevant_change",
            lambda o, r, s: o == "no_relevant_change",
            candidate={},
        ),
        Case(
            "irrelevant_index",
            "test_an_irrelevant_index_is_not_promoted_even_if_faster",
            "not improved; the index is not used",
            lambda o, r, s: o != "improved" and _unused(s),
            candidate=irrelevant,
            index=("item", "title"),
        ),
        Case(
            "workload_without_the_column",
            "test_a_workload_that_does_not_use_the_column_shows_no_mechanism",
            "not improved",
            lambda o, r, s: o != "improved",
            candidate=patch,
            workload=superuser,
        ),
        Case(
            "slower",
            "test_a_slower_candidate_is_a_regression",
            "regression",
            lambda o, r, s: o == "regression",
            candidate={ROUTE: _delay(route, 0.008)},
            index=None,
        ),
        # Both arms wait 30 ms in the handler; the candidate 7 ms less: about 18% faster, below the 20% threshold.
        Case(
            "near_threshold",
            "test_near_the_threshold_a_first_pass_is_not_enough",
            "not improved",
            lambda o, r, s: o != "improved",
            base={ROUTE: _delay(route, 0.030)},
            candidate={ROUTE: _delay(route, 0.023)},
            index=None,
        ),
        Case(
            "faster_wrong_answer",
            "test_a_faster_wrong_answer_is_a_regression",
            "regression, the result differs",
            lambda o, r, s: o == "regression" and any("differ" in x for x in r),
            candidate=wrong,
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--rev", required=True)
    parser.add_argument("--workload", required=True)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    repo, out = Path(args.repo).expanduser(), Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    rev = subprocess.run(["git", "-C", str(repo), "rev-parse", args.rev], capture_output=True, text=True,
                         check=True).stdout.strip()  # fmt: skip

    def show(path: str) -> str:
        return subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True,
                              check=True).stdout  # fmt: skip

    head = alembic_head(repo, rev)
    assert head is not None
    saved = Path(args.workload).read_text()
    selected = [c for c in cases(show, head, patched(repo, rev, Path(args.patch).read_text()), saved)
                if not args.case or c.name in args.case]  # fmt: skip
    mandate = Mandate(workspace="controls")
    mandate.autonomy.provision_dependencies = Autonomy.ALLOW
    mandate.egress.package_registries = ["pypi.org", "files.pythonhosted.org", "deb.debian.org", "registry.npmjs.org"]
    stack = detect_stack(repo, rev)
    images = {"python": provision(repo, rev, stack.part("python"), policy=PolicyEngine(mandate))}
    plan = test_plan(repo, rev, stack, "python")
    assert plan is not None
    files = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", rev], capture_output=True,
                           text=True, check=True).stdout.splitlines()  # fmt: skip
    test_dir = stack.python.test_paths[0] if stack.python and stack.python.test_paths else "tests"  # as the lab
    product = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent.parent), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    summary = []
    for case in selected:
        started = time.monotonic()
        store = Store(None)  # each case alone: its confirmation is the only one at the commit
        lab = PerfLab(repo, None, store, stack, images)  # type: ignore[arg-type]  # no model: nothing written by one
        lab.marker = async_suite(show, files)
        workload = {f"{LAB_DIR}/workload.py": case.workload or saved}

        def measure(overlay: dict[str, str], case: Case = case, workload: dict[str, str] = workload,
                    lab: PerfLab = lab) -> tuple[dict[str, Any] | None, str]:  # fmt: skip
            return lab._measure(rev, {**(overlay or case.base), **workload}, plan, test_dir,  # pyright: ignore[reportPrivateUsage]
                                ("item", "owner_id"), case.index)  # fmt: skip

        sessions, error = lab._sessions(measure, case.candidate, f"control:{case.name}")  # pyright: ignore[reportPrivateUsage]
        report: dict[str, Any] = {
            "case": case.name, "unit_test": f"tests/unit/test_promotion.py::{case.unit_test}",
            "expected": case.expected, "product": product, "rev": rev, "criteria": PROMOTION_CRITERIA,
            "candidate_files": sorted(case.candidate), "base_overlay": sorted(case.base),
            "candidate_sha256": hashlib.sha256(json.dumps(case.candidate, sort_keys=True).encode()).hexdigest(),
            "workload_sha256": hashlib.sha256((case.workload or saved).encode()).hexdigest(),
            "image": images["python"].tag, "error": error[-600:],
        }  # fmt: skip
        if sessions is None:
            report |= {"outcome": "not measured", "passed": False}
        else:
            promotion, control, confirmation = lab.judge_v4(measure, case.candidate, sessions, case.name, rev,
                                                            case.index)  # fmt: skip
            strip = lambda rows: [{k: v for k, v in s.items() if k != "responses"} for s in rows]  # noqa: E731
            report |= {
                "outcome": promotion.outcome, "reasons": promotion.reasons,
                "passed": case.passes(promotion.outcome, promotion.reasons, sessions),
                "sessions": strip(sessions), "control": strip(control), "confirmation": strip(confirmation),
            }  # fmt: skip
        report["wall_s"] = round(time.monotonic() - started, 1)
        (out / f"{case.name}.json").write_text(json.dumps(report, indent=1, default=str))
        line = {k: report.get(k) for k in ("case", "expected", "outcome", "passed", "wall_s")}
        line["reasons"] = (report.get("reasons") or [report.get("error")])[:6]
        summary.append(line)
        print(json.dumps(line, default=str), flush=True)
    (out / "summary.json").write_text(json.dumps({"product": product, "rev": rev, "cases": summary}, indent=1))
    print(json.dumps({"passed": sum(1 for s in summary if s["passed"]), "of": len(summary)}))


if __name__ == "__main__":
    main()
