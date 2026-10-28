"""Decide the same inputs with whichever Unbidden is installed: run it with another version's interpreter.

    uv run --project <worktree of version X> python bench/eval2/policy_runner.py <cases.json> > <decisions.json>

Standalone on purpose (it imports nothing from `bench`), so the exact previous commit decides with its own code.
Three kinds of case:
- `decide`: an opportunity and a context, decided by `director.decide.decide` (context fields this version does not
  know are dropped, and listed);
- `judge`: planted test and timing evidence, judged by this version's own rules for a performance verdict;
- `world`: a sequence of maps of one table, run through this version's `world.checks.run_checks`.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Any


def decide_case(case: dict[str, Any]) -> dict[str, Any]:
    from unbidden.contracts.guardian import Mandate
    from unbidden.contracts.opportunity import Opportunity
    from unbidden.director.decide import Context, decide

    known = {f.name for f in dataclasses.fields(Context)}
    given = case.get("context", {})
    kwargs: dict[str, Any] = {k: (tuple(v) if k == "checked_dirs" else v) for k, v in given.items() if k in known}
    context = Context(**kwargs)
    decision = decide(Opportunity.model_validate(case["opportunity"]), Mandate.model_validate(case["mandate"]), context)
    return {"chosen": decision.chosen.value, "reason": decision.reason, "ignored_context": sorted(set(given) - known)}


def judge_case(case: dict[str, Any]) -> dict[str, Any]:
    from unbidden.contracts.experiment import TestOutcome, TestSummary
    from unbidden.lab import evaluator
    from unbidden.lab.perfstats import judge

    base, cand = (TestSummary.model_validate(case[k]) for k in ("baseline_tests", "candidate_tests"))
    tests, _ = evaluator.classify_tests(base, cand)
    stats = judge(case["before_ms"], case["after_ms"])
    improved = stats.improved and tests is not TestOutcome.REGRESSION
    if hasattr(evaluator, "level_for"):
        level = int(evaluator.level_for(improved, tests, suite_ran=True))
    else:  # before tests-v2: PerfLab granted L4 to an improvement whose tests passed or failed as before
        level = 4 if improved and tests in (TestOutcome.PASSED, TestOutcome.PRE_EXISTING) else 3 if improved else 2
    return {"tests": tests.value, "improved": improved, "level": level}


def world_case(case: dict[str, Any]) -> dict[str, Any]:
    from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
    from unbidden.contracts.world import WorldModel
    from unbidden.store import Store
    from unbidden.world.checks import run_checks

    store = Store(None)
    steps = []
    for step in case["steps"]:
        opened = run_checks(WorldModel.model_validate(step["world"]), store)
        opps = store.list("opportunities", Opportunity)
        steps.append({"opened": len(opened), "statuses": sorted(o.status.value for o in opps)})
        if step.get("then") == "decline":
            for o in opps:
                o.status = OpportunityStatus.DECLINED
                store.put("opportunities", o)
    return {"steps": steps}


def main() -> None:
    with open(sys.argv[1]) as handle:
        cases = json.load(handle)
    run = {"decide": decide_case, "judge": judge_case, "world": world_case}
    out = []
    for case in cases:
        try:
            out.append({"id": case["id"], **run[case["kind"]](case)})
        except Exception as exc:  # a version that cannot take a case says so; it is scored as such
            out.append({"id": case["id"], "error": f"{type(exc).__name__}: {exc}"[:300]})
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
