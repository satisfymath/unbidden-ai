"""Score evaluation v2 against the oracle, per scenario and in aggregate, with denominators.

    uv run python -m bench.eval2.score <scenarios dir> --policies <label>=<decisions.json> ... \
        [--products <label>=<product.json> ...] --out <report base name>

The only reader of the oracle. Capabilities are scored apart (discovery, decision, execution, result, abstention);
no count of actions or declines is a score on its own. A candidate's result is checked by applying its patch to a
clean copy of the scenario and running the project's tests plus the hidden check, with this interpreter.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

NEAR = 2  # lines: a finding this close to the planted line is the planted defect
ABSTAIN_KINDS = {"healthy", "environment", "low_value"}


def matches(opp: dict[str, Any], truth: list[dict[str, Any]]) -> bool:
    findings = (opp.get("details") or {}).get("findings") or []
    return any(
        f.get("path") == t["path"] and abs(int(f.get("line") or 0) - t["line"]) <= NEAR for f in findings for t in truth
    )


def oracle_check(scenarios: Path, scenario: str, patch: str, oracle: dict[str, Any]) -> tuple[bool, str]:
    """The candidate applied to a clean copy: the project's tests and the hidden check must pass."""
    with tempfile.TemporaryDirectory(prefix="eval2-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(scenarios / "repos" / scenario, work)
        applied = subprocess.run(["git", "-C", str(work), "apply", "-"], input=patch, text=True, capture_output=True)
        if applied.returncode != 0:
            return False, f"patch does not apply: {applied.stderr[:200]}"
        hidden = scenarios / "oracle" / f"{scenario}_hidden.py"
        targets = ["tests", *([str(hidden)] if hidden.exists() else [])]
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
            cwd=work,
            capture_output=True,
            text=True,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        )
        passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", out.stdout)) else 0
        if out.returncode != 0:
            return False, out.stdout.strip().splitlines()[-1][:200] if out.stdout.strip() else "tests did not run"
        if passed < int(oracle.get("min_collected", 0)):
            return False, f"{passed} tests ran; the planted defect hid tests and {oracle['min_collected']} should run"
        return True, f"{passed} passed"


def score_product(scenarios: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        oracle = json.loads((scenarios / "oracle" / f"{row['scenario']}.json").read_text())
        truth = oracle.get("truth", [])
        decisions = {d["id"]: d.get("chosen") for d in (row.get("decide") or {}).get("decisions", [])}
        opps = row.get("opportunities", [])
        acted = [o for o in opps if decisions.get(o["id"]) == "run_experiment"]
        found = [t for t in truth if any(matches(o, [t]) for o in opps)]
        results = []
        for e in row.get("experiments", []):
            verdict = e.get("verdict") or {}
            level = int(verdict.get("evidence_level") or 0)
            entry: dict[str, Any] = {
                "opportunity": e["opportunity"],
                "ran": verdict != {},
                "level": level,
                "improved": bool(e.get("improved")),
                "notes": (e.get("notes") or [])[-2:],
            }
            if e.get("patch"):
                valid, why = oracle_check(scenarios, row["scenario"], e["patch"], oracle)
                entry |= {"oracle_valid": valid, "oracle_why": why}
            entry["false_l4"] = level >= 4 and not entry.get("oracle_valid", False)
            results.append(entry)
        scored.append(
            {
                "scenario": row["scenario"],
                "kind": oracle["kind"],
                "version": row["version"],
                "truth": len(truth),
                "found": len(found),
                "opportunities": len(opps),
                "acted": len(acted),
                "acted_true": sum(1 for o in acted if matches(o, truth)),
                "abstained": (len(acted) == 0) if oracle["kind"] in ABSTAIN_KINDS else None,
                "decision_ok": (len(acted) == 0) if not truth else any(matches(o, truth) for o in acted),
                "experiments": results,
                "valid_results": sum(1 for r in results if r.get("oracle_valid") and r["level"] >= 4),
                "false_l4": sum(1 for r in results if r["false_l4"]),
                "model_calls": len(row.get("model_runs", [])),
                "seconds": round(
                    sum(s.get("seconds", 0) for s in row["steps"].values())
                    + sum(e.get("seconds", 0) for e in row.get("experiments", [])),
                    1,
                ),
            }
        )
    return scored


def score_policy(
    cases: list[dict[str, Any]], decided: list[dict[str, Any]], oracle: dict[str, Any], scenarios: Path
) -> list[dict[str, Any]]:
    by_id = {d["id"]: d for d in decided}
    scored = []
    for case in cases:
        got = by_id.get(case["id"], {"error": "no answer"})
        if "/" in case["id"]:  # an opportunity a scan found in a planted repository
            scenario = case["id"].split("/")[0]
            truth = json.loads((scenarios / "oracle" / f"{scenario}.json").read_text()).get("truth", [])
            real = matches(case["opportunity"], truth)
            acceptable = ["run_experiment"] if real else ["wait", "decline"]
            entry = {
                "case": case["id"],
                "kind": "planted" if real else "not_planted",
                "chosen": got.get("chosen"),
                "ok": got.get("chosen") in acceptable,
            }
        elif case["kind"] == "decide":
            acceptable = oracle[case["id"]]["acceptable"]
            entry = {
                "case": case["id"],
                "kind": oracle[case["id"]]["kind"],
                "chosen": got.get("chosen"),
                "ok": got.get("chosen") in acceptable,
            }
        elif case["kind"] == "judge":
            max_level = oracle[case["id"]]["max_level"]
            entry = {
                "case": case["id"],
                "kind": "evaluator",
                "level": got.get("level"),
                "tests": got.get("tests"),
                "ok": got.get("level") is not None and got["level"] <= max_level,
                "false_l4": (got.get("level") or 0) >= 4 > max_level,
            }
        else:
            final = (got.get("steps") or [{}])[-1].get("statuses", [])
            entry = {
                "case": case["id"],
                "kind": "world",
                "final": final,
                "ok": oracle[case["id"]]["acceptable_final"] in final,
            }
        if "error" in got:
            entry["error"] = got["error"]
        scored.append(entry)
    return scored


def act_on_everything(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The simple reference policy: experiment on every opportunity; judgement and world cases are not its to take."""
    return [{"id": c["id"], "chosen": "run_experiment"} for c in cases if c["kind"] == "decide"]


def _pairs(values: list[str]) -> dict[str, Path]:
    return {k: Path(v).expanduser() for k, _, v in (x.partition("=") for x in values)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios")
    parser.add_argument("--policies", nargs="*", default=[])
    parser.add_argument("--products", nargs="*", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    scenarios = Path(args.scenarios).expanduser()
    cases = json.loads((scenarios / "cases.json").read_text())
    oracle = json.loads((scenarios / "oracle" / "cases.json").read_text())
    report: dict[str, Any] = {"policies": {}, "products": {}}
    decided_sets = {k: json.loads(p.read_text()) for k, p in _pairs(args.policies).items()}
    decided_sets["act-on-everything"] = act_on_everything(cases)
    for label, decided in decided_sets.items():
        rows = score_policy(
            [c for c in cases if label != "act-on-everything" or c["kind"] == "decide"], decided, oracle, scenarios
        )
        report["policies"][label] = {
            "rows": rows,
            "ok": sum(r["ok"] for r in rows),
            "n": len(rows),
            "false_l4": sum(1 for r in rows if r.get("false_l4")),
        }
    for label, path in _pairs(args.products).items():
        rows = score_product(scenarios, json.loads(path.read_text()))
        truth = sum(r["truth"] for r in rows)
        acted = sum(r["acted"] for r in rows)
        due = [r for r in rows if r["abstained"] is not None]
        report["products"][label] = {
            "rows": rows,
            "discovery_recall": f"{sum(r['found'] for r in rows)}/{truth}",
            "action_precision": f"{sum(r['acted_true'] for r in rows)}/{acted}",
            "decisions_ok": f"{sum(r['decision_ok'] for r in rows)}/{len(rows)}",
            "abstentions_due": f"{sum(1 for r in due if r['abstained'])}/{len(due)}",
            "valid_results": sum(r["valid_results"] for r in rows),
            "false_l4": sum(r["false_l4"] for r in rows),
            "model_calls": sum(r["model_calls"] for r in rows),
            "seconds": round(sum(r["seconds"] for r in rows), 1),
        }
    Path(f"{args.out}.json").write_text(json.dumps(report, indent=1, default=str))
    lines = [f"# Evaluation v2: {Path(args.out).name}", ""]
    for label, p in report["policies"].items():
        lines.append(f"## Policy `{label}`: {p['ok']}/{p['n']} as the oracle accepts, false L4 {p['false_l4']}")
        lines += ["", "| Case | Kind | Answer | OK |", "|---|---|---|---|"]
        lines += [
            f"| {r['case']} | {r['kind']} | {r.get('chosen') or r.get('level') or r.get('final')}"
            f"{' (' + r['error'][:60] + ')' if r.get('error') else ''} | {'yes' if r['ok'] else 'no'} |"
            for r in p["rows"]
        ]
        lines.append("")
    for label, p in report["products"].items():
        lines.append(f"## Product `{label}` from the initial state")
        lines.append("")
        lines.append(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in p.items() if k != "rows"))
        lines += [
            "",
            "| Scenario | Kind | Found / truth | Acted (true) | Decision | Experiments | Valid | False L4 | s |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in p["rows"]:
            ex = "; ".join(f"L{e['level']} {e.get('oracle_why', 'no patch')}"[:70] for e in r["experiments"]) or "-"
            lines.append(
                f"| {r['scenario']} | {r['kind']} | {r['found']}/{r['truth']} | {r['acted']} ({r['acted_true']}) "
                f"| {'ok' if r['decision_ok'] else 'no'} | {ex} | {r['valid_results']} | {r['false_l4']} "
                f"| {r['seconds']} |"
            )
        lines.append("")
    Path(f"{args.out}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
