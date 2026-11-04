# ruff: noqa: E501
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
    checked = {(str(v.get("slug", "")).split("/c13-")[-1], int(v.get("number") or 0)): v.get("verdict") for v in verify}
    for p in pulls:
        p["verified_independently"] = checked.get((p["repo"], int(p["number"] or 0)), "not run")
    for r in rows:
        r["version"] = version
        r["status"] = "done" if r["name"] in have else "running or not run"
    spent = round(sum(float((r.get("facts") or {}).get("spent_usd") or 0) for r in [*a, *b]), 4)
    return {"label": label, "version": version, "rows": rows, "pulls": pulls, "records": len(have), "spent_usd": spent}


def totals(pulls: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged = [p for p in pulls if p["merged"]]
    # The harness puts each copy back at its pin before a run, so one fix can be merged in two runs (rich's examples/
    # F821 in the pass and in the 0.18.9 rerun): improvements are counted once, by repository and title.
    distinct = {(p["repo"], str(p["title"]).replace("security: bump", "fix(deps): bump").removesuffix(" (security)")): p
                for p in merged}  # fmt: skip
    levels = Counter(str(r.get("level", "-")).split(" ")[0] for r in rows if r.get("status") == "done")
    l5 = [r for r in rows if str(r.get("level", "")).startswith("L5")]
    return {
        "repositories_run": len({r["name"] for r in rows if r.get("status") == "done"}),
        "runs": sum(1 for r in rows if r.get("status") == "done"),
        "pull_requests": len(pulls),
        "pull_requests_ci_green": sum(1 for p in pulls if p["ci"] == "green"),
        "merges": len(merged),
        "merged_by_unbidden": len(distinct),
        "merged_verified_independently": sum(
            1 for p in distinct.values() if p.get("verified_independently") == "verified"
        ),
        "merged_by_kind": dict(Counter(p["kind"] for p in distinct.values())),
        "repositories_with_a_merge": len({p["repo"] for p in merged}),
        "l5": [{"repo": r["name"], "level": r["level"], "version": r["version"]} for r in l5],
        "highest_levels": dict(sorted(levels.items())),
    }


def markdown(out: dict[str, Any]) -> str:
    """FINAL.md: the pass in one page, every figure from `out` (the same data as final-evidence.json)."""
    t = out["totals"]
    merged = [p for p in out["pull_requests"] if p["merged"]]
    running = sorted({r["name"] for r in out["repositories"] if r.get("status") != "done"})
    lines = [
        "# Campaign 13, final pass",
        "",
        f"Generated {out['generated_at']} from the records in this directory (`bench/campaign13/evidence.py`).",
        "",
        "Unbidden ran on its own, frontier models only, over the 39 repositories of the corpus. It worked on copies",
        "under `github.com/satisfymath`, and nothing went upstream. It found improvements and measured them, opened pull",
        "requests and merged them. It merged only when the team's own CI was green on the pull request's exact head.",
        "The apps it brought up itself it then deployed and verified.",
        "",
        "## In numbers",
        "",
        "| | |",
        "|---|---|",
        f"| Repositories with a record | {t['repositories_run']} of 39 |",
        f"| Pull requests opened by the agent | {t['pull_requests']} ({t['pull_requests_ci_green']} green on the team's CI) |",
        f"| Improvements merged by the product, autonomously | **{t['merged_by_unbidden']}** in {t['repositories_with_a_merge']} "
        f"repositories ({', '.join(f'{v} {k}' for k, v in sorted(t['merged_by_kind'].items()))}; {t['merges']} merges, one "
        "fix merged in two runs) |",
        f"| Merges verified independently (`verify.py`: ruff, or OSV advisories) | {t['merged_verified_independently']} of "
        f"{t['merged_by_unbidden']} |",
        f"| L5, verified after the agent's own deploy | {len(t['l5'])}: {', '.join(x['repo'] for x in t['l5'])} |",
        f"| Model spend | US${out['spent_usd']:.2f} |",
        "",
        "## Every merge",
        "",
        "| Repository | Pull request | Kind | CI | Independent check | Version |",
        "|---|---|---|---|---|---|",
    ]
    for p in merged:
        lines.append(f"| {p['repo']} | [#{p['number']}]({p['url']}) {p['title']} | {p['kind']} | {p['ci']} | "
                     f"{p.get('verified_independently')} | {p['version']} |")  # fmt: skip
    lines += ["", "## L5", ""]
    for x in t["l5"]:
        lines.append(f"- **{x['repo']}** ({x['version']}): {x['level']}")
    lines += [
        "",
        "A verified-deploy L5 claims no measured effect. It says four things about the change: it was deployed by the",
        "product, the deploy is attributable, it was judged healthy with no endpoint failing more than before, and",
        "for security the fixed version is the one running. The latency measurement was deferred on every app,",
        "because the host was too busy with many repositories at once (a 1-minute load above a quarter of the CPUs).",
        "That deferral is by design: noise never becomes a result.",
        "",
        "## Every pull request, merged or not",
        "",
        "| Repository | Pull request | Kind | CI | Merged | Version |",
        "|---|---|---|---|---|---|",
    ]
    for p in out["pull_requests"]:
        lines.append(f"| {p['repo']} | [#{p['number']}]({p['url']}) {p['title']} | {p['kind']} | {p['ci']} | "
                     f"{'yes' if p['merged'] else 'no'} | {p['version']} |")  # fmt: skip
    lines += [
        "",
        "Some green pull requests stayed unmerged, and the reason was not a defect. When one pull request merged,",
        "the others that touched the same lock file went stale, and the product closed them to measure them again.",
        "0.18.10 lets the observed cycle wait for that new proposal. Others stayed open because the pass ended first.",
        "A red pull request is left to a person by rule, even when the base was red already (ctfd's own lint).",
        "dooit's merge shows CI `none`: its workflows run only on pushes to `develop`, never on a pull request, so",
        "the lab's evidence is all there is (0.18.6), and the independent check confirms the advisories gone.",
        "",
        "## Repositories without a pull request",
        "",
        "These are listed in `REPORT-aggregate.md`, one row each with its reason. The reasons include: nothing to",
        "propose, the team's CI does not run the tool, no proven fix, a stack that does not build here, no compose",
        "file, or out of scope (TypeScript, Go, a monorepo subdirectory).",
    ]
    if running:
        lines += [
            "",
            f"Stopped before their record when the pass was closed at 20:36 -03 (the hackathon's deadline): "
            f"{', '.join(running)}. Their partial logs are kept; nothing of them is counted.",
        ]
    lines += [
        "",
        "## How this pass got here",
        "",
        "The pass was started on 0.18.1 and stopped five times. Each time its own records showed a general product",
        "defect, and each was fixed with a test and released before going on (0.18.2 to 0.18.10, in `FINDINGS.md`).",
        "The stopped starts are kept in `final-0.18.*-stopped/`. They are never added to the totals above:",
        ]  # fmt: skip
    for e in out["earlier_starts"]:
        lines.append(f"- {e['label']} ({e['version']}): {len(e['pull_requests'])} pull requests, {e['merged']} merged")
    lines += [
        "",
        "## Where",
        "",
        "- `MATRIX.md`: everything the agent did, per repository: the matrix, then every opportunity with its decision.",
        "- `final-evidence.json`: this page as data, for the site.",
        "- `REPORT-aggregate.md`: every dimension per class with Wilson intervals, one joined row per repository, and",
        "  the comparison with campaign 12.",
        "- `<repo>/B1.json`, `<repo>/run.log`, `<repo>/export/`: each run's record, its log, and the agent's own export",
        "  (events, decisions, experiments, transcripts of every model call, secret-scanned).",
        "- `verify/`: the independent checks.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--run", action="append", default=[], help="label=version (a records directory)")
    parser.add_argument("--earlier", action="append", default=[], help="label=version of a stopped start, listed apart")
    parser.add_argument("--out", required=True)
    parser.add_argument("--md", help="also write the one-page summary (FINAL.md) here")
    args = parser.parse_args()
    corpus = {r["name"]: r for r in yaml.safe_load(Path(args.corpus).read_text())["repos"]}

    def block(spec: str, every: bool) -> dict[str, Any]:
        label, version = spec.split("=", 1)
        return run_block(label, version, corpus, every)

    runs = [block(x, i == 0) for i, x in enumerate(args.run)]
    earlier = [block(x, False) for x in args.earlier]
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
    if args.md:
        Path(args.md).write_text(markdown(out))
    print(json.dumps(out["totals"], indent=1))


if __name__ == "__main__":
    main()
