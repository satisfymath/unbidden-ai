"""Campaign 13: the final pass as data for the site and the project (`final-evidence.json`), from the records only.

    uv run python -m bench.campaign13.evidence --corpus bench/campaign13/corpus.yaml \
        --run final=0.18.6 --run final-rerun-0.18.9=0.18.9 \
        [--earlier final-0.18.5-stopped=0.18.5] --out docs/bench/campaign13/final-evidence.json

Every pull request the agent opened on a campaign copy, with its URL, the CI on its exact head, whether the product
merged it, and the run's version; the highest evidence level per repository; totals; repositories still running or
without a record, said as such. Starts that were stopped are listed apart, never added to the pass's totals.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bench.campaign13.report import _agent_pulls, _ci_of, joined_rows, load, load_verify

BASE = Path("docs/bench/campaign13")


def kind_of(title: str) -> str:
    t = title.lower()
    if "bump" in t and ("security" in t or t.startswith("fix(deps)")):
        return "security"
    if t.startswith("perf"):
        return "performance"
    if "error in" in t or t.startswith("fix: repair"):
        return "correctness"
    return "quality"


def pulls_of(records: list[dict[str, Any]], version: str) -> list[dict[str, Any]]:
    out = []
    for rec in records:
        f = rec.get("facts") or {}
        slug = (f.get("fork") or {}).get("slug") or f"satisfymath/c13-{rec['repo']}"
        for p in _agent_pulls(f.get("fork_after_c2") or {}, rec.get("started_at")):
            out.append({
                "repo": rec["repo"], "version": version, "number": p.get("number"), "title": p.get("title"),
                "url": f"https://github.com/{slug}/pull/{p.get('number')}", "kind": kind_of(str(p.get("title"))),
                "ci": _ci_of(p), "merged": bool(p.get("merged_at")), "merged_at": p.get("merged_at"),
                "state": p.get("state"),
            })  # fmt: skip
    return out


def run_block(label: str, version: str, corpus: dict[str, dict[str, Any]], every: bool) -> dict[str, Any]:
    d = BASE / label
    a, b = load([d])
    verify = load_verify([d])
    rows = [r for r in joined_rows(a, b, verify, corpus) if r["run"] != "A" or r["checks"] is not None or every]
    have = {r["repo"] for r in b} | {r["repo"] for r in a}
    pulls = pulls_of(b, version)
    for r in rows:
        r["version"] = version
        r["status"] = "done" if r["name"] in have else "running or not run"
    spent = round(sum(float((r.get("facts") or {}).get("spent_usd") or 0) for r in [*a, *b]), 4)
    return {"label": label, "version": version, "rows": rows, "pulls": pulls, "records": len(have), "spent_usd": spent}


def totals(pulls: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged = [p for p in pulls if p["merged"]]
    levels = Counter(str(r.get("level", "-")).split(" ")[0] for r in rows if r.get("status") == "done")
    l5 = [r for r in rows if str(r.get("level", "")).startswith("L5")]
    return {
        "repositories_run": len({r["name"] for r in rows if r.get("status") == "done"}),
        "runs": sum(1 for r in rows if r.get("status") == "done"),
        "pull_requests": len(pulls),
        "pull_requests_ci_green": sum(1 for p in pulls if p["ci"] == "green"),
        "merged_by_unbidden": len(merged),
        "merged_by_kind": dict(Counter(p["kind"] for p in merged)),
        "repositories_with_a_merge": len({p["repo"] for p in merged}),
        "l5": [{"repo": r["name"], "level": r["level"], "version": r["version"]} for r in l5],
        "highest_levels": dict(sorted(levels.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--run", action="append", default=[], help="label=version (a records directory)")
    parser.add_argument("--earlier", action="append", default=[], help="label=version of a stopped start, listed apart")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    corpus = {r["name"]: r for r in yaml.safe_load(Path(args.corpus).read_text())["repos"]}
    runs = [run_block(*x.split("=", 1), corpus, i == 0) for i, x in enumerate(args.run)]
    earlier = [run_block(*x.split("=", 1), corpus, False) for x in args.earlier]
    rows = [r for blk in runs for r in blk["rows"]]
    pulls = [p for blk in runs for p in blk["pulls"]]
    out = {
        "title": "Unbidden campaign 13, final pass: what the agent did on 39 repositories, autonomously",
        "generated_at": datetime.now(UTC).isoformat(timespec="minutes"),
        "where": "copies of the repositories under github.com/satisfymath (c13-<name>); nothing upstream",
        "rule": "merged only by the product, on the team's own CI green on the pull request's exact head",
        "runs": [{k: v for k, v in blk.items() if k not in ("rows", "pulls")} for blk in runs],
        "totals": totals(pulls, rows),
        "pull_requests": pulls,
        "repositories": rows,
        "earlier_starts": [
            {
                "label": blk["label"],
                "version": blk["version"],
                "pull_requests": blk["pulls"],
                "merged": sum(1 for p in blk["pulls"] if p["merged"]),
            }
            for blk in earlier
        ],
        "spent_usd": round(sum(blk["spent_usd"] for blk in runs), 4),
    }
    Path(args.out).write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps(out["totals"], indent=1))


if __name__ == "__main__":
    main()
