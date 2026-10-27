"""Replay a Prometheus's history minute by minute under two health criteria: false alarms when nothing was wrong,
and whether the injected service was degraded while a fault was on.

    uv run python -m bench.health_calibration http://127.0.0.1:9090 scenario1.jsonl [scenario2.jsonl ...] \\
        --clean-until 2026-10-27T03:40 --tz -03:00

Intervals come from the scenario operator's logs: control minutes are clean; a fault interval runs from its
injection to its result; recovery minutes are left out (the baseline window still holds the fault). `--clean-until`
adds the minutes after the last scenario ended, when nothing was injected.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from unbidden.observe.health import degraded_services
from unbidden.world.prometheus import Prometheus

CRITERIA = ("health-v1", "health-v2-candidate", "health-v3-candidate")


def _ts(day: str, clock: str, tz: timezone) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=tz)


def intervals(
    paths: list[str], day: str, tz: timezone
) -> tuple[list[datetime], list[tuple[datetime, datetime, str]], datetime]:
    clean: list[datetime] = []
    faults: list[tuple[datetime, datetime, str]] = []
    last = datetime.min.replace(tzinfo=tz)
    for path in paths:
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        start: tuple[datetime, str] | None = None
        for row in rows:
            at = _ts(day, row["t"], tz)
            last = max(last, at)
            phase = row["phase"]
            if phase == "control":
                clean.append(at)
            elif phase.startswith("fault:") and start is None:
                start = (at, row["expect"])
            elif phase == "result" and start is not None:
                faults.append((start[0], at, start[1]))
                start = None
    return clean, faults, last


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prometheus")
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--day", default="2026-10-27")
    parser.add_argument("--tz", default="-03:00")
    parser.add_argument("--clean-until", help="local ISO time; minutes after the last scenario up to it are clean")
    parser.add_argument("--out")
    args = parser.parse_args()
    sign = -1 if args.tz.startswith("-") else 1
    hours, minutes = args.tz.lstrip("+-").split(":")
    tz = timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))
    clean, faults, last = intervals(args.logs, args.day, tz)
    if args.clean_until:
        until = datetime.fromisoformat(args.clean_until).replace(tzinfo=tz)
        # The baseline window is 30 minutes: leave the first 35 after the last fault out of "clean".
        at = last + timedelta(minutes=35)
        while at <= until:
            clean.append(at)
            at += timedelta(minutes=1)
    prom = Prometheus(args.prometheus)
    result: dict[str, Any] = {}
    for criteria in CRITERIA:
        alarms = [sorted(degraded_services(prom, criteria, at.timestamp())) for at in clean]
        trials = []
        for start, end, expect in faults:
            minutes = []
            at = start
            while at <= end:
                minutes.append(sorted(degraded_services(prom, criteria, at.timestamp())))
                at += timedelta(minutes=1)
            first = next((i for i, d in enumerate(minutes) if expect in d), None)
            trials.append({"expect": expect, "minutes": len(minutes), "detected_min": first,
                           "others": sorted({s for d in minutes for s in d if s != expect})})  # fmt: skip
        result[criteria] = {
            "clean_minutes": len(clean),
            "clean_minutes_with_alarm": sum(1 for a in alarms if a),
            "alarmed_services": sorted({s for a in alarms for s in a}),
            "trials": trials,
        }
    for criteria, r in result.items():
        print(f"{criteria}: {r['clean_minutes_with_alarm']}/{r['clean_minutes']} clean minutes alarmed "
              f"({', '.join(r['alarmed_services']) or 'none'})")  # fmt: skip
        for t in r["trials"]:
            print(
                f"   {t['expect']:16} detected at minute {t['detected_min']} of {t['minutes']}; others: {t['others']}"
            )
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
