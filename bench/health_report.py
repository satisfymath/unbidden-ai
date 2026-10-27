"""Summarize fault-injection scenarios (one JSON object per line, written by the scenario operator) into a table.

    uv run python -m bench.health_report scenario1.jsonl scenario2.jsonl

Per trial: when the fault was injected, the first minute any anomaly was open, the first minute the injected
service was a suspect and the first minute it was the only or first one (the pre-registered criterion is top-1
within 5 minutes), and the anomalies open on services the fault does not reach.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def trials(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if row.get("phase") != "inject":
            continue
        flag = row["flag"]
        watch = [r for r in rows[i + 1 :] if r.get("phase") == f"fault:{flag}"]
        expect = watch[0]["expect"] if watch else None
        first_any = next((r["minute"] for r in watch if r["suspects"]), None)
        listed = next((r["minute"] for r in watch if expect in r["suspects"]), None)
        top1 = next((r["minute"] for r in watch if r["suspects"][:1] == [expect]), None)
        others = sorted({s for r in watch for s in r["suspects"] if s != expect})
        out.append(
            {
                "flag": flag,
                "variant": row["variant"],
                "expect": expect,
                "first_anomaly_min": first_any,
                "listed_min": listed,
                "top1_min": top1,
                "pass": top1 is not None and top1 <= 5,
                "other_suspects": others,
            }
        )
    return out


def main() -> None:
    rows: list[dict[str, Any]] = []
    for path in sys.argv[1:]:
        rows += [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    controls = [r for r in rows if r.get("phase") == "control"]
    false_controls = [r for r in controls if r["suspects"]]
    print(f"control minutes: {len(controls)}, with an anomaly open: {len(false_controls)}")
    print(
        "| Fault | Expected | First anomaly (min) | Listed (min) | Top-1 (min) | Pass | Other suspects |"
    )
    print("|---|---|---|---|---|---|---|")
    for t in trials(rows):
        print(
            f"| {t['flag']} {t['variant']} | {t['expect']} | {t['first_anomaly_min']} | {t['listed_min']} | "
            f"{t['top1_min']} | {'yes' if t['pass'] else 'no'} | {', '.join(t['other_suspects']) or '-'} |"
        )


if __name__ == "__main__":
    main()
