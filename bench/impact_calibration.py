"""Calibrate deploy-impact criteria on real probe rounds, before adopting them.

A/A: the rounds of one version split into consecutive halves must never produce a claim. Injection: the second
half scaled by +20/+30/+50% shows how often a real change of that size is caught.

Usage: uv run python -m bench.impact_calibration <workspace-path> <version> [--out docs/bench/<name>.md]
"""

from __future__ import annotations

import argparse
import statistics
from collections.abc import Callable
from pathlib import Path

from unbidden.observe import impact
from unbidden.observe.impact import Impact, Round, judge_endpoint
from unbidden.workspace import Workspace

Judge = Callable[[str, list[Round], list[Round], int], impact.EndpointImpact]


def windows(rounds: list[Round], size: int) -> list[tuple[list[Round], list[Round]]]:
    """Disjoint consecutive pairs of windows: (before, after)."""
    pairs = []
    step = size * 2 + impact.WARMUP_ROUNDS
    for start in range(0, len(rounds) - step + 1, step):
        before = rounds[start : start + size]
        after = rounds[start + size : start + step]
        pairs.append((before, after))
    return pairs


def scaled(rounds: list[Round], factor: float) -> list[Round]:
    return [Round(r.version, r.statuses, tuple(ms * factor for ms in r.latencies_ms)) for r in rounds]


def run(judge: Judge, rounds: list[Round], size: int) -> dict[str, str]:
    pairs = windows(rounds, size)
    out = {"pairs": str(len(pairs))}
    aa = [judge("t", b, a, size).impact for b, a in pairs]
    out["A/A claims"] = f"{sum(i in (Impact.IMPROVED, Impact.DEGRADED) for i in aa)}/{len(pairs)}"
    for pct in (20, 30, 50):
        hits = [judge("t", b, scaled(a, 1 + pct / 100), size).impact is Impact.DEGRADED for b, a in pairs]
        out[f"+{pct}% caught"] = f"{sum(hits)}/{len(pairs)}"
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("version")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    store = Workspace(args.workspace).store()
    lines = [
        "| Endpoint | Criteria | Median ms | Pairs | A/A claims | +20% | +30% | +50% |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for target in store.round_targets():
        rounds = [Round(v, tuple(s), tuple(ms)) for _, v, s, ms in store.rounds(target, version=args.version)]
        rounds = [r for r in rounds if r.served]
        if len(rounds) < 40:
            continue
        median = statistics.median(ms for r in rounds for ms in r.served)
        for name, judge in (("v1", impact.judge_endpoint_v1), ("v2", judge_endpoint)):
            res = run(judge, rounds, 15)
            lines.append(
                f"| {target} | {name} | {median:.2f} | {res['pairs']} | {res['A/A claims']} | "
                f"{res['+20% caught']} | {res['+30% caught']} | {res['+50% caught']} |"
            )
    text = "\n".join(lines)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")


if __name__ == "__main__":
    main()
