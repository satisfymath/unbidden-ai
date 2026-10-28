"""Bring an opportunity's recorded history from one workspace into another, as history, never as a new run.

    uv run python -m bench.import_history <source state.db> <target repo> <opportunity id> --decision D-035

Reads the source read-only. Copies the opportunity, its experiment and its proposals with their original ids. The
opportunity is marked `details.imported` (where from, which decision, the level it was recorded at) and its level is
set to what today's test rules grant on its recorded test data: an old level is not carried over by the copy.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.experiment import Experiment, Proposal
from unbidden.contracts.opportunity import Opportunity
from unbidden.lab.evaluator import classify_tests, level_for
from unbidden.workspace import Workspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("opportunity")
    parser.add_argument("--decision", required=True)
    args = parser.parse_args()
    with closing(sqlite3.connect(f"file:{Path(args.source).expanduser()}?mode=ro", uri=True)) as conn:
        docs = {(c, i): json.loads(d) for c, i, d in conn.execute("SELECT collection, id, doc FROM docs")}
    opp = Opportunity.model_validate(docs[("opportunities", args.opportunity)])
    experiment_id = opp.details.get("experiment_id")
    experiment = Experiment.model_validate(docs[("experiments", experiment_id)]) if experiment_id else None
    proposals = [Proposal.model_validate(d) for (c, _), d in docs.items() if c == "proposals"
                 and d["opportunity_id"] == opp.id]  # fmt: skip
    recorded = int(opp.evidence_level)
    granted = recorded
    tests = None
    if experiment and experiment.baseline_tests and experiment.candidate_tests:
        outcome, _ = classify_tests(experiment.baseline_tests, experiment.candidate_tests)
        tests = outcome.value
        improved = bool((opp.details.get("verdict") or {}).get("improved"))
        granted = min(recorded, int(level_for(improved, outcome, suite_ran=True)))
    opp.evidence_level = EvidenceLevel(granted)
    opp.details = {**opp.details, "imported": {
        "from": args.source, "decision": args.decision, "recorded_level": recorded, "granted_today": granted,
        "tests_today": tests, "note": "historical record, not a new run",
    }}  # fmt: skip
    store = Workspace(Path(args.target).expanduser()).store()
    store.put("opportunities", opp, key=opp.dedup_key)
    if experiment is not None:
        experiment.provenance = {**experiment.provenance, "imported_from": args.source, "decision": args.decision}
        store.put("experiments", experiment)
    for proposal in proposals:
        store.put("proposals", proposal)
    print(json.dumps({"opportunity": opp.id, "experiment": experiment_id, "proposals": [p.id for p in proposals],
                      "recorded_level": recorded, "granted_today": granted, "tests_today": tests}))  # fmt: skip


if __name__ == "__main__":
    main()
