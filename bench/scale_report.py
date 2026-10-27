"""The scale benchmark's report: engineering value, not activity, each rate over the repositories it applies to.

    uv run python -m bench.scale_report docs/bench/2026-10-27-scale-pilot.json [--reread ~/unbidden-bench]

Rates carry Wilson 95 % intervals: with ten repositories an interval is the honest size of what is known. Level 5
needs an authorized deployment; where none exists the repository is not eligible, which is said, never counted as a
failure or a success. `--reread` reads each workspace's state again (the record is derived from state, so it can be
re-derived and audited).
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from bench.scale import classify, read_state

BOOTSTRAPPED_OUT = ("checkout failed", "unsupported stack", "bootstrap failed")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> str:
    if n == 0:
        return "n/a (0 eligible)"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.0%} (95% CI {lo:.0%}-{hi:.0%})"


def first_improvement_minutes(row: dict[str, Any]) -> float | None:
    times = [
        datetime.fromisoformat(v["ts"])
        for v in (row.get("state") or {}).get("verdicts") or []
        if v.get("improved") and v.get("level", 0) >= 4 and v.get("ts")
    ]
    if not times or "started_at" not in row:
        return None
    return round((min(times) - datetime.fromisoformat(row["started_at"])).total_seconds() / 60, 1)


def report(data: dict[str, Any]) -> str:
    rows = data["rows"]
    n = len(rows)
    spend = data.get("spend", {}).get("by_repo", {})
    usd = {r["name"]: spend.get(r["tag"], {}).get("usd", 0.0) for r in rows}
    boot = [r for r in rows if r["outcome"] not in BOOTSTRAPPED_OUT]
    supported = [r for r in rows if (r.get("state") or {}).get("languages")]
    found = [r for r in boot if (r.get("state") or {}).get("opportunities")]
    opps = [o for r in boot for o in r["state"].get("opportunities") or []]
    verdicts = [v for r in boot for v in r["state"].get("verdicts") or []]
    validated = [v for v in verdicts if v.get("improved") and v.get("level", 0) >= 4]
    l4_repos = [r for r in boot if r["outcome"] == "validated improvement (L4)"]
    declined = [o for o in opps if o["status"] == "declined"]
    blocked = [o for o in opps if o.get("blocked")]
    built = sum((r.get("state") or {}).get("capabilities_built", 0) for r in rows)
    probes = [p for r in rows for p in (r.get("state") or {}).get("probe_decisions") or []]
    timed_out = [r for r in rows if r["steps"].get("watch", {}).get("timed_out")]
    total_usd = sum(usd.values())
    local_s = sum(
        (r.get("state") or {}).get("model_runs_by_tier", {}).get("local", {}).get("compute_s", 0.0) for r in rows
    )
    firsts = [m for r in rows if (m := first_improvement_minutes(r)) is not None]

    out = [
        f"# Scale benchmark: {data['run']}",
        "",
        f"Unbidden at `{data['unbidden_commit'][:12]}`; manifest `{data['manifest']}`; settings {data['settings']}.",
        "Nobody chose an opportunity, an experiment or a fix; no person intervened during the runs.",
        *(
            [f"Code under test differed between rows: {sorted(versions)}."]
            if len(versions := {(r.get("unbidden") or {}).get("commit", "?")[:12] for r in rows}) > 1
            or any((r.get("unbidden") or {}).get("dirty") for r in rows)
            else []
        ),
        "",
        "## Rates",
        "",
        "| Measure | Eligible | Result |",
        "|---|---|---|",
        f"| Stack supported | all repositories | {rate(len(supported), n)} |",
        f"| Bootstrap (an analyzer complete or a probe run) | all repositories | {rate(len(boot), n)} |",
        f"| At least one opportunity found | bootstrapped | {rate(len(found), len(boot))} |",
        f"| Experiments that validated (L4) | experiments with a verdict | {rate(len(validated), len(verdicts))} |",
        f"| Repositories with an L4 improvement | bootstrapped | {rate(len(l4_repos), len(boot))} |",
        "| Level 5 (verified deployed effect) | repositories with an authorized deployment | n/a: none here; "
        "these are third parties' upstreams and the mandate denies deploys |",
        f"| Opportunities declined by the Director | opportunities | {rate(len(declined), len(opps))} |",
        f"| Opportunities the lab could not measure | opportunities | {rate(len(blocked), len(opps))} |",
        f"| Cycles past the wall-clock limit | all repositories | {rate(len(timed_out), n)} |",
        "",
        "False positives need a person to label each finding; they are not measured here. A declined or unmeasured",
        "opportunity is not counted as a false positive.",
        "",
        "## Cost and time",
        "",
        f"- Remote spend: US${total_usd:.4f} in total (list price x reported tokens; worst cost where unknown).",
        f"- Per bootstrapped repository: US${total_usd / len(boot):.4f}." if boot else "- No repository bootstrapped.",
        f"- Per opportunity found: US${total_usd / len(opps):.4f}." if opps else "- No opportunity found.",
        f"- Per validated improvement: US${total_usd / len(validated):.4f}."
        if validated
        else "- No validated improvement, so no cost per improvement.",
        f"- Local model compute: {local_s / 60:.1f} min.",
        f"- Time to first validated improvement (min): {sorted(firsts)}." if firsts else "- No validated improvement.",
        f"- Robustness probes decided: {len(probes)} ({sum(p.get('chosen') == 'investigate' for p in probes)} run).",
        f"- Capabilities built by Forge: {built}.",
        "",
        "## Per repository",
        "",
        "| Repository | Language | Shape | Outcome | Analyzers complete | Opportunities | Experiments | L4 | US$ | "
        "Minutes | Max RSS MB |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        s = r.get("state") or {}
        an = s.get("analyzers") or []
        l4 = sum(1 for v in s.get("verdicts") or [] if v.get("improved") and v.get("level", 0) >= 4)
        out.append(
            f"| {r['name']} | {r['meta'].get('language')} | {r['meta'].get('shape')} | {r['outcome']} | "
            f"{sum(a['completeness'] == 'complete' for a in an)}/{len(an)} | {len(s.get('opportunities') or [])} | "
            f"{s.get('experiments', 0)} | {l4} | {usd[r['name']]:.4f} | {r.get('seconds', 0) / 60:.1f} | "
            f"{r['steps'].get('watch', {}).get('max_rss_mb', '-')} |"
        )
    out += ["", "## Why each repository ended where it did", ""]
    for r in rows:
        s = r.get("state") or {}
        reasons = [*(s.get("blind_spots") or []), *(s.get("problems") or [])]
        unfinished = [a for a in s.get("analyzers") or [] if a["completeness"] != "complete"]
        reasons += [f"{a['tool']}: {a['completeness']} {a.get('error', '')[:120]}".strip() for a in unfinished]
        reasons += [f"probe: {p.get('chosen')} ({p.get('reason')})" for p in s.get("probe_decisions") or []]
        if s.get("probe"):
            p = s["probe"]
            reasons.append(f"probe result: {p.get('summary') or p.get('why')}"[:200])
        settled = [o for o in s.get("opportunities") or [] if o["status"] != "open" or o.get("blocked")]
        reasons += [f"{o['id']}: {o['status']}, {o.get('blocked') or o.get('reason')}" for o in settled[:8]]
        if r["steps"].get("watch", {}).get("timed_out"):
            reasons.append("the autonomous cycle reached the wall-clock limit")
        out.append(f"- **{r['name']}** ({r['outcome']}): " + ("; ".join(reasons) or "nothing to report"))
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results")
    parser.add_argument("--reread", metavar="WORKDIR", help="read each workspace's state again from this directory")
    args = parser.parse_args()
    path = Path(args.results)
    data = json.loads(path.read_text())
    if args.reread:
        for row in data["rows"]:
            workspace = Path(args.reread).expanduser() / row["name"]
            if workspace.exists():
                row["state"] = read_state(workspace)
                row["outcome"] = classify(row)
        path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    path.with_suffix(".md").write_text(report(data))
    print(path.with_suffix(".md"))


if __name__ == "__main__":
    main()
