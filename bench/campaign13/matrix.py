# ruff: noqa: E501
"""Campaign 13, final pass: MATRIX.md, everything the agent did on every repository, from the records only.

    uv run python -m bench.campaign13.matrix --corpus bench/campaign13/corpus.yaml \
        --run final=0.18.6 --run final-rerun-0.18.9=0.18.9 --evidence docs/bench/campaign13/final-evidence.json \
        --out docs/bench/campaign13/final/MATRIX.md

One matrix row per repository (all 39, a repository without a record says why), then one section per run: the
checks, every opportunity with the director's last decision and the lab's last note, experiments and verdicts,
pull requests with CI, merge and the independent check, deploys and outcomes, blocks, model calls and spend.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

BASE = Path("docs/bench/campaign13")


def jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def one_line(text: Any, limit: int = 160) -> str:
    s = " ".join(str(text or "").split())
    return (s[: limit - 1] + "…") if len(s) > limit else s


def run_detail(label: str, version: str, name: str, pulls: list[dict[str, Any]]) -> dict[str, Any] | None:
    d = BASE / label / name
    rec_path = d / "B1.json" if (d / "B1.json").exists() else d / "A.json"
    if not rec_path.exists():
        return None
    rec = json.loads(rec_path.read_text())
    f = rec.get("facts") or {}
    ex = d / "export"
    opps = jsonl(ex / "opportunities.jsonl")
    decisions = jsonl(ex / "decisions.jsonl")
    experiments = jsonl(ex / "experiments.jsonl")
    events = jsonl(ex / "events.jsonl")
    blocks = jsonl(ex / "blocks.jsonl")
    spend = jsonl(ex / "spend.jsonl")
    calls = jsonl(ex / "model_runs.jsonl")
    last_decision: dict[str, dict[str, Any]] = {}
    for dec in sorted(decisions, key=lambda x: str(x.get("decided_at"))):
        last_decision[str(dec.get("opportunity_id"))] = dec
    kinds = Counter(str(e.get("type")) for e in events)
    checks = f.get("checks") or {}
    self_host = f.get("self_host") or {}
    return {
        "name": name,
        "version": version,
        "label": label,
        "level": "A" if rec_path.name == "A.json" else "B",
        "mode": (f.get("autonomy") or {}).get("mode") or f.get("mode_got") or "-",
        "deploy_target": f.get("deploy_target") or "-",
        "self_host": None if not self_host else ("up" if self_host.get("ok") else one_line(self_host.get("why"), 140)),
        "checks": checks.get("status") or (rec.get("facts") or {}).get("checks"),
        "collected": checks.get("collected"),
        "opportunities": [
            {
                "title": o.get("title"),
                "category": o.get("category"),
                "source": o.get("source"),
                "status": o.get("status"),
                "level": o.get("evidence_level"),
                "decision": (last_decision.get(str(o.get("id"))) or {}).get("chosen"),
                "why": (last_decision.get(str(o.get("id"))) or {}).get("reason"),
                "lab": ((o.get("details") or {}).get("lab_notes") or [None])[-1],
            }
            for o in opps
        ],
        "decisions": dict(Counter(str(x.get("chosen")) for x in decisions)),
        "experiments": len(experiments),
        "improved": kinds.get("verdict.recorded", 0),
        "pulls": pulls,
        "deploys": kinds.get("operations.deployed", 0),
        "outcomes": [e.get("payload") for e in events if e.get("type") in ("outcome.recorded", "impact.judged")],
        "blocks": [one_line(b.get("detail") or b.get("why") or b.get("kind"), 160) for b in blocks],
        "model_calls": len(calls),
        "spent_usd": round(sum(float(s.get("cost_usd") or 0) for s in spend), 4) or f.get("spent_usd"),
        "events": dict(kinds.most_common()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--run", action="append", default=[])
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    corpus = yaml.safe_load(Path(args.corpus).read_text())["repos"]
    evidence = json.loads(Path(args.evidence).read_text())
    runs = [tuple(x.split("=", 1)) for x in args.run]
    details: list[dict[str, Any]] = []
    missing: list[str] = []
    for repo in corpus:
        name = repo["name"]
        found = False
        for label, version in runs:
            pulls = [p for p in evidence["pull_requests"] if p["repo"] == name and p["version"] == version]
            det = run_detail(label, version, name, pulls)
            if det is not None:
                det["class"], det["family"] = repo.get("class"), repo.get("family")
                details.append(det)
                found = True
        if not found:
            missing.append(name)
    lines = [
        "# Campaign 13, final pass: everything the agent did, per repository",
        "",
        "Generated by `bench/campaign13/matrix.py` from each run's record (`<repo>/B1.json` or `A.json`) and the agent's own",
        "export (`<repo>/export/*.jsonl`): opportunities, the director's decisions, experiments, verdicts, events, blocks,",
        "model calls and spend. Pull requests come from the copies on GitHub; the independent check is `verify.py`.",
        "",
        "## Matrix",
        "",
        "| Repository | Class | Version | Mode | Checks (tests) | Opportunities | Experiments | PRs (green) | Merged | Deploys | Highest level | Self-host | Model calls | US$ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    level_of = {(r["name"], r["version"]): r.get("level") for r in evidence["repositories"]}
    for d in details:
        n_green = sum(1 for p in d["pulls"] if p["ci"] == "green")
        merged = [f"[#{p['number']}]({p['url']})" for p in d["pulls"] if p["merged"]]
        level = str(level_of.get((d["name"], d["version"])) or "-").split(" (")[0]
        tests = f"{d['checks']} ({d['collected']})" if d["collected"] else str(d["checks"] or "-")
        lines.append(
            f"| [{d['name']}](#{d['name']}-{d['version'].replace('.', '')}) | {d['class']} | {d['version']} | {d['mode']} | {tests} | "
            f"{len(d['opportunities'])} | {d['experiments']} | {len(d['pulls'])} ({n_green}) | {', '.join(merged) or '-'} | "
            f"{d['deploys']} | {level} | {one_line(d['self_host'] or '-', 60)} | {d['model_calls']} | {d['spent_usd']} |"
        )
    for name in missing:
        lines.append(
            f"| {name} | {next(r.get('class') for r in corpus if r['name'] == name)} | - | - | stopped before its record (the pass was closed at 20:36 -03, the hackathon's deadline) | | | | | | | | | |"
        )
    for d in details:
        lines += [
            "",
            f"## {d['name']} ({d['version']})",
            f'<a id="{d["name"]}-{d["version"].replace(".", "")}"></a>',
            "",
            f"- Class **{d['class']}**, family {d['family']}; mode **{d['mode']}**, deploy target {d['deploy_target']}"
            + (f"; self-host: {d['self_host']}" if d["self_host"] else ""),
            f"- The team's checks: **{d['checks']}**"
            + (f", {d['collected']} tests collected" if d["collected"] else ""),
            f"- Director's decisions: {', '.join(f'{k} {v}' for k, v in sorted(d['decisions'].items())) or 'none'}",
            f"- Experiments {d['experiments']}, verdicts recorded {d['improved']}, deploys {d['deploys']}, model calls {d['model_calls']}, US${d['spent_usd']}",
        ]
        if d["pulls"]:
            lines += ["", "| Pull request | Kind | CI | Merged | Independent check |", "|---|---|---|---|---|"]
            for p in d["pulls"]:
                lines.append(
                    f"| [#{p['number']}]({p['url']}) {one_line(p['title'], 90)} | {p['kind']} | {p['ci']} | {'yes' if p['merged'] else 'no'} | {p.get('verified_independently')} |"
                )
        if d["opportunities"]:
            lines += [
                "",
                "| Opportunity | Category | Status | Level | Last decision | Why / the lab's last note |",
                "|---|---|---|---|---|---|",
            ]
            for o in d["opportunities"]:
                why = one_line(o["lab"] or o["why"], 150).replace("|", "/")
                lines.append(
                    f"| {one_line(o['title'], 80).replace('|', '/')} | {o['category']} | {o['status']} | L{o['level']} | {o['decision'] or '-'} | {why} |"
                )
        for out in d["outcomes"][:3]:
            lines.append(f"\n- Outcome after deploy: {one_line(json.dumps(out, default=str), 300)}")
        if d["blocks"]:
            lines += ["", "Blocks: " + "; ".join(d["blocks"][:5])]
    Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"{len(details)} runs, {len(missing)} without a record: {', '.join(missing)}")


if __name__ == "__main__":
    main()
