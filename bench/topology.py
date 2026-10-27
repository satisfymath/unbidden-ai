"""Score a World Model against a reference topology written independently of it (bench/topologies/*.yaml).

    uv run python -m bench.topology bench/topologies/opentelemetry-demo.yaml path/to/map.json [--out docs/bench/x]

`map.json` is the output of `unbidden map --json`. Rules are the reference file's own: which predicates are claims,
which targets are left out of scoring (the telemetry plane a diagram omits on purpose). Obsolete facts are not
claims. Every miss and every extra is listed, not only the ratios.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

SCORED = ("calls", "uses_database")


def _ratio(hit: int, total: int) -> float | None:
    return round(hit / total, 3) if total else None


def _pr(found: set[Any], expected: set[Any]) -> dict[str, Any]:
    hit = found & expected
    return {
        "precision": _ratio(len(hit), len(found)),
        "recall": _ratio(len(hit), len(expected)),
        "found": len(found),
        "expected": len(expected),
        "missed": sorted(map(str, expected - found)),
        "extra": sorted(map(str, found - expected)),
    }


def score(reference: dict[str, Any], world: dict[str, Any]) -> dict[str, Any]:
    current = {rid: r for rid, r in world["resources"].items() if r["status"] != "obsolete"}
    relations = [r for r in world["relations"] if r["status"] != "obsolete"]
    name = {rid: r["name"] for rid, r in current.items()}

    services = {r["name"] for r in current.values() if r["kind"] in ("service", "database")}
    expected_services = set(reference["services"]) | set(reference["datastores"])
    datastores = {r["name"] for r in current.values() if r["kind"] == "database"} | {
        r["name"] for r in current.values() if r["kind"] == "service" and r["attributes"].get("engine")
    }

    plane = set(reference.get("telemetry_plane", []))
    claimed = {
        (name[r["src"]], name[r["dst"]])
        for r in relations
        if r["predicate"] in SCORED
        and r["src"] in name
        and r["dst"] in name
        and current[r["src"]]["kind"] in ("service", "database")
        and current[r["dst"]]["kind"] in ("service", "database")
    }
    telemetry = sorted(f"{a} -> {b}" for a, b in claimed if b in plane)
    claimed = {(a, b) for a, b in claimed if b not in plane}
    expected = {(a, b) for a, b in reference["relations"] if b not in plane}
    starts = sorted(
        f"{name[r['src']]} -> {name[r['dst']]}"
        for r in relations
        if r["predicate"] == "depends_on" and r["src"] in name and r["dst"] in name
    )

    result: dict[str, Any] = {
        "system": reference["system"],
        "blind": reference.get("blind", False),
        "services": _pr(services, expected_services),
        "datastores": _pr(datastores, set(reference["datastores"])),
        "relations": _pr(claimed, expected),
        "relations_by_status": {
            s: sum(1 for r in relations if r["predicate"] in SCORED and r["status"] == s)
            for s in ("observed", "inferred")
        },
        "telemetry_edges_not_scored": telemetry,
        "depends_on_not_scored": starts,
        "blind_spots": [f"{b['what']}: {b['why']}" for b in world.get("blind_spots", [])],
    }

    if "endpoint_tables" in reference:
        found_et = {
            (name[r["src"]], r["predicate"], name[r["dst"]])
            for r in relations
            if r["predicate"] in ("reads", "writes") and r["src"] in name and r["dst"] in name
        }
        expected_et = {
            (endpoint, predicate, table)
            for endpoint, touches in reference["endpoint_tables"].items()
            for predicate, tables in (touches or {}).items()
            for table in tables
        }
        result["endpoint_tables"] = _pr(found_et, expected_et)

    deployments = [r for r in current.values() if r["kind"] == "deployment"]
    if "running_commit" in reference:
        running = deployments[0]["attributes"] if deployments else {}
        result["running_commit"] = {
            "expected": reference["running_commit"],
            "found": running.get("commit"),
            "status": running.get("commit_status"),
            "correct": running.get("commit") == reference["running_commit"],
        }
    elif deployments:
        a = deployments[0]["attributes"]
        result["running_commit"] = {
            "found": a.get("commit"),
            "status": a.get("commit_status"),
            "reason": a.get("commit_reason"),
        }
    return result


def as_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "| System | Blind | Services P / R | Datastores P / R | Service links P / R | Endpoint→table P / R "
        "| Running commit |",
        "|---|---|---|---|---|---|---|",
    ]

    def pr(r: dict[str, Any], key: str) -> str:
        m = r.get(key)
        return f"{m['precision']} / {m['recall']} ({m['found']} vs {m['expected']})" if m else "n/a"

    for r in results:
        commit = r.get("running_commit") or {}
        shown = f"{(commit.get('found') or '?')[:12]} {commit.get('status')}"
        if "correct" in commit:
            shown += " ✓" if commit["correct"] else " ✗"
        lines.append(
            f"| {r['system']} | {'yes' if r['blind'] else 'no'} | {pr(r, 'services')} | {pr(r, 'datastores')} | "
            f"{pr(r, 'relations')} | {pr(r, 'endpoint_tables')} | {shown} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pairs", nargs="+", help="reference.yaml map.json [reference.yaml map.json ...]")
    parser.add_argument("--out", help="write <out>.json and <out>.md")
    args = parser.parse_args()
    if len(args.pairs) % 2:
        parser.error("give reference/map pairs")
    results = []
    for ref_path, map_path in zip(args.pairs[::2], args.pairs[1::2], strict=True):
        reference = yaml.safe_load(Path(ref_path).read_text())
        world = json.loads(Path(map_path).read_text())
        results.append(score(reference, world))
    print(as_markdown(results))
    if args.out:
        Path(f"{args.out}.json").write_text(json.dumps(results, indent=2) + "\n")
        Path(f"{args.out}.md").write_text(as_markdown(results) + "\n")


if __name__ == "__main__":
    main()
