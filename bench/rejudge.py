"""Every recorded experiment judged again with the current test-evidence rules, beside the rules it was judged by.

    uv run python -m bench.rejudge <dir> [<dir> ...] --out docs/bench/<name>

Reads each `.unbidden/state.db` below the directories (read-only), deduplicating experiments by id. For each
experiment with a test summary on both sides it reports the outcome under the rules of its time (tests-v1, kept here
verbatim for the comparison) and under the current ones, and whether its level would still be L4. Nothing recorded is
changed: a level a record states stays in the record; this says whether it would be granted today.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

from unbidden.contracts.experiment import TestOutcome, TestSummary
from unbidden.lab.evaluator import classify_tests, validates


def classify_v1(baseline: TestSummary, candidate: TestSummary) -> str:
    """The judgement before tests-v2, verbatim, so the two can be compared on the same records."""
    base = Counter(n for r in baseline.failed_per_round for n in set(r))
    cand = Counter(n for r in candidate.failed_per_round for n in set(r))
    if any(c == candidate.rounds and base[n] == 0 for n, c in cand.items()):
        return "regression"
    if any(base[n] == 0 and c < candidate.rounds for n, c in cand.items()):
        return "inconclusive"
    return "pre_existing" if any(base.values()) else "passed"


def experiments(roots: list[Path]) -> dict[str, tuple[dict[str, Any], str]]:
    found: dict[str, tuple[dict[str, Any], str]] = {}
    for root in roots:
        for db in sorted(root.expanduser().rglob(".unbidden/state.db")):
            try:
                with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
                    rows = conn.execute("SELECT doc FROM docs WHERE collection = 'experiments'").fetchall()
            except sqlite3.Error:
                continue
            for (doc,) in rows:
                exp = json.loads(doc)
                found.setdefault(exp["id"], (exp, str(db)))
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    rows = []
    for exp, db in experiments([Path(r) for r in args.roots]).values():
        if not exp.get("baseline_tests") or not exp.get("candidate_tests"):
            continue
        base = TestSummary.model_validate(exp["baseline_tests"])
        cand = TestSummary.model_validate(exp["candidate_tests"])
        old = classify_v1(base, cand)
        new, reasons = classify_tests(base, cand)
        rows.append(
            {
                "experiment": exp["id"],
                "opportunity": exp["opportunity_id"],
                "state": db,
                "tests_v1": old,
                "tests_v2": new.value,
                "l4_under_v1": old in ("passed", "pre_existing"),
                "l4_under_v2": validates(new),
                "reasons_v2": reasons[:3],
            }
        )
    changed = [r for r in rows if r["l4_under_v1"] != r["l4_under_v2"]]
    data = {
        "experiments_with_tests": len(rows),
        "l4_eligible_v1": sum(r["l4_under_v1"] for r in rows),
        "l4_eligible_v2": sum(r["l4_under_v2"] for r in rows),
        "no_longer_l4": [r for r in changed if r["l4_under_v1"]],
        "outcomes_v2": dict(Counter(r["tests_v2"] for r in rows)),
        "rows": rows,
    }
    Path(f"{args.out}.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({k: v for k, v in data.items() if k != "rows"}, indent=2))
    assert all(r["tests_v2"] in {o.value for o in TestOutcome} for r in rows)


if __name__ == "__main__":
    main()
