"""Re-read recorded board checks with checker v2 (objective amendment 2): no model call, no new capture.

    uv run python -m bench.ecosystem.board_rescore <records dir> --out <json>

For every `check.json` beside a `verdict.json` (written by checker v1), v2 is applied to the same page record: the
same rows, flag boxes, hit-tests and pixels. Which bins were short is v1's record of the truth; the numbers rule is
v1's, carried over from its findings. Nothing in the records is changed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bench.ecosystem.board_check import judge_v2, wrong_rows_v2


def rescore(check: Path) -> dict[str, Any]:
    page = json.loads(check.read_text())
    v1 = json.loads((check.parent / "verdict.json").read_text())
    true = {b: {"shortfall": 1 if b in set(v1["short"]) else 0} for b in v1["bins"]}
    judged = judge_v2(page, true, v1={"bins": v1["bins"], "problems": v1["problems"]})  # type: ignore[arg-type]
    preserved = all(v for k, v in v1["preserved"].items() if k != "lost")
    return {
        "record": str(check.parent),
        "v1": {"verified": v1["verified"], "problems": len(v1["problems"])},
        "v2": {"verified": not judged["problems"] and preserved, "problems": judged["problems"],
               "wrong": wrong_rows_v2(judged), "straddling": judged["straddling"]},
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("records")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    found = sorted(Path(args.records).expanduser().rglob("check.json"))
    out = [rescore(c) for c in found if (c.parent / "verdict.json").exists()]
    Path(args.out).write_text(json.dumps(out, indent=1))
    changed = [r for r in out if r["v1"]["verified"] != r["v2"]["verified"]]
    print(f"{len(out)} records; verdict changed in {len(changed)}")
    for r in changed:
        print(" ", r["record"].split("/eval6/")[-1], "v1", r["v1"]["verified"], "-> v2", r["v2"]["verified"],
              r["v2"]["problems"][:2])  # fmt: skip


if __name__ == "__main__":
    main()
