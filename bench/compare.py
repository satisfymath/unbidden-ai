"""Two runs of the same repositories under two Unbidden versions, compared pair by pair.

    uv run python -m bench.compare <before.json> <after.json> --out docs/bench/<name>

Only repositories present in both, at the same pinned commit, are compared. For each binary outcome the paired
change is tested with an exact two-sided McNemar test on the discordant pairs (b: lost, c: gained). Every repository
whose root cause changed is listed, regressions first: a fix that helps some repositories and breaks others shows both.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from bench.causes import root_cause

FAILED = {"checkout_failed", "not_software", "unsupported_language", "no_dependency_manifest",
          "no_applicable_analyzer", "analyzer_failed"}  # fmt: skip
# Causes ordered from "stopped earliest" to "went furthest"; moving right is progress.
DEPTH = ["checkout_failed", "not_software", "unsupported_language", "no_dependency_manifest", "deps_other",
         "deps_private_or_network", "deps_python_version", "deps_project_metadata", "deps_native_build",
         "deps_resolution", "no_applicable_analyzer", "analyzer_failed", "nothing_found", "findings_declined",
         "actionable"]  # fmt: skip


def mcnemar_exact(lost: int, gained: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs."""
    n = lost + gained
    if n == 0:
        return 1.0
    k = min(lost, gained)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def outcomes(row: dict[str, Any]) -> dict[str, bool]:
    cause = row.get("cause") or root_cause(row)
    state = row.get("state") or {}
    analyzers = state.get("analyzers") or []
    return {
        "stack_supported": bool(state.get("languages")),
        "dependencies_installed": bool(state.get("languages")) and not cause.startswith("deps_"),
        "analyzer_complete": any(a["completeness"] == "complete" for a in analyzers),
        "bootstrapped": cause not in FAILED and not cause.startswith("deps_"),
        "ci_understood": bool((row.get("ci") or {}).get("commands")),
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    a = {r["name"]: r for r in before["rows"]}
    b = {r["name"]: r for r in after["rows"]}
    pairs = [
        (a[n], b[n]) for n in sorted(a.keys() & b.keys()) if a[n]["meta"].get("commit") == b[n]["meta"].get("commit")
    ]
    metrics: dict[str, dict[str, Any]] = {}
    for key in ("stack_supported", "dependencies_installed", "analyzer_complete", "bootstrapped", "ci_understood"):
        x = [outcomes(p)[key] for p, _ in pairs]
        y = [outcomes(q)[key] for _, q in pairs]
        lost = sum(1 for i, j in zip(x, y, strict=True) if i and not j)
        gained = sum(1 for i, j in zip(x, y, strict=True) if j and not i)
        metrics[key] = {"before": sum(x), "after": sum(y), "n": len(pairs), "gained": gained, "lost": lost,
                        "p_mcnemar": round(mcnemar_exact(lost, gained), 4)}  # fmt: skip
    changes = []
    for p, q in pairs:
        cp, cq = p.get("cause") or root_cause(p), q.get("cause") or root_cause(q)
        if cp != cq:
            direction = DEPTH.index(cq) - DEPTH.index(cp) if cp in DEPTH and cq in DEPTH else 0
            changes.append({"name": p["name"], "before": cp, "after": cq, "direction": direction})
    changes.sort(key=lambda c: (c["direction"], c["name"]))
    return {"pairs": len(pairs), "metrics": metrics, "changes": changes}


def as_markdown(result: dict[str, Any], before: str, after: str) -> str:
    out = [
        f"# Paired comparison: `{before}` → `{after}`",
        "",
        f"{result['pairs']} repositories in both runs, same commits.",
        "",
        "| Outcome | Before | After | Gained | Lost | McNemar p |",
        "|---|---|---|---|---|---|",
    ]
    for key, m in result["metrics"].items():
        out.append(f"| {key} | {m['before']}/{m['n']} | {m['after']}/{m['n']} | {m['gained']} | {m['lost']} | "
                   f"{m['p_mcnemar']} |")  # fmt: skip
    out += ["", "## Repositories whose root cause changed (regressions first)", ""]
    out += [f"- {c['name']}: {c['before']} → {c['after']}" + (" **(regression)**" if c["direction"] < 0 else "")
            for c in result["changes"]] or ["- none"]  # fmt: skip
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = compare(json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text()))
    Path(f"{args.out}.json").write_text(json.dumps(result, indent=2) + "\n")
    Path(f"{args.out}.md").write_text(as_markdown(result, Path(args.before).stem, Path(args.after).stem))
    print(Path(f"{args.out}.md").read_text())


if __name__ == "__main__":
    main()
