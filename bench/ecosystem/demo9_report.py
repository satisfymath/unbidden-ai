"""The stage 9 demo's story, written from its records alone (docs/bench/stage9-demo.md).

    uv run python -m bench.ecosystem.demo9_report <run dir> <archived workspace> <independent check output> --out FILE

What the harness prepared, what Unbidden did, and what the independent check says, each from where it is recorded:
the run's record and cycle log, the workspace's store (opportunities, experiments with every session, verdicts,
proposals, blocks, model runs), and the output of `bench.ecosystem.conduit_indep`. Nothing is written by a model.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from pathlib import Path

from unbidden.contracts.experiment import Experiment, Proposal
from unbidden.contracts.opportunity import Opportunity
from unbidden.store import Store


def report(run: Path, workspace: Path, independent: str) -> str:
    record = json.loads((run / "record.json").read_text())
    activity = json.loads((run / "activity.json").read_text())
    store = Store(workspace / "state.db")
    opps = store.list("opportunities", Opportunity)
    experiments = {e.opportunity_id: e for e in store.list("experiments", Experiment)}
    proposals = store.list("proposals", Proposal)
    with sqlite3.connect(workspace / "state.db") as db:
        runs = [json.loads(r[0]) for r in db.execute("SELECT doc FROM docs WHERE collection = 'model_runs'")]
    out: list[str] = [
        "# Stage 9 demo: a proactive cycle on Conduit, with its independent check",
        "",
        "Conduit is a development application (used to build Unbidden since stage 7): this is a demonstration of the "
        "whole cycle and of how its evidence is checked, not evaluation evidence.",
        "",
        "## What the harness prepared (not Unbidden)",
        "",
        f"- The repository at `{record['restored']['commit'][:12]}`, its staging with synthetic data "
        f"({', '.join(f'{v} {k}' for k, v in record['restored']['data'].items())}), a read-only database role, a "
        "fresh API token, a new workspace with a proactive mandate (no goal), Meta's API only, envelope `demo`.",
        f"- One declared answer, if asked: adding a package registry Unbidden names. Given: "
        f"{[i['granted'] for i in record['interventions']] or 'nothing (nothing was asked)'}.",
        "",
        "## What Unbidden did",
        "",
    ]
    checks = activity.get("project_checks") or {}
    out.append(
        f"- **Reproduced the project before anything else:** its own checks at the base, "
        f"{checks.get('status')} ({checks.get('collected')} tests, {len(checks.get('failed') or [])} failed), "
        f"`{(checks.get('command') or '').splitlines()[-1] if checks.get('command') else ''}`."
    )
    out.append(f"- **Found, without a ticket:** {len(opps)} opportunities.")
    for opp in sorted(opps, key=lambda o: -int(o.evidence_level)):
        line = f"  - L{int(opp.evidence_level)} {opp.title}"
        exp = experiments.get(opp.id)
        verdict = opp.details.get("verdict") or {}
        if exp is not None and exp.sessions:
            base = [s["median_ms"] for s in exp.sessions if s["arm"] == "base"]
            cand = [s["median_ms"] for s in exp.sessions if s["arm"] == "candidate"]
            scans = sorted({int(s["index_scans"]) for s in exp.sessions
                            if s["arm"] == "candidate" and s.get("index_scans") is not None})  # fmt: skip
            why = verdict.get("outcome") or next(
                (n for n in reversed(opp.details.get("lab_notes", [])) if "permutation" in n or "no change" in n), ""
            )
            line += (
                f": measured in {len(exp.sessions)} alternating sessions, medians {statistics.median(base):.1f} "
                f"-> {statistics.median(cand):.1f} ms; index scans per candidate session {scans}; **{str(why)[:240]}**"
            )
        elif (opp.details.get("consistency") or {}).get("status"):
            line += f": {opp.details['consistency']['status']}: {str(opp.details['consistency'].get('note'))[:200]}"
        elif opp.details.get("blocked"):
            line += f": {str(opp.details['blocked'].get('why'))[:200]}"
        out.append(line)
    out.append(
        f"- **Proposed:** {len(proposals)} change(s), each a local branch with its migration: "
        f"{', '.join(p.branch for p in proposals) or 'none'}; nothing pushed, merged or deployed."
    )
    remote = sum(float((r.get("cost") or {}).get("usd_remote") or 0) for r in runs)
    models = sorted({str(r.get("model")) for r in runs})
    out.append(
        f"- **Spent:** US${record['usd_after'] - record['usd_before']:.2f} on the ledger "
        f"({len(runs)} model calls, {', '.join(models)}; US${remote:.2f} in the workspace's own records); "
        f"{record['wall_s'] / 60:.0f} minutes."
    )
    out += [
        "",
        "## Independent check (not Unbidden: the endpoints' own SQL on the lab data, rolled back)",
        "",
        "```",
        independent.strip(),
        "```",
        "",
    ]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("workspace")
    parser.add_argument("independent")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    text = report(Path(args.run), Path(args.workspace), Path(args.independent).read_text())
    Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
