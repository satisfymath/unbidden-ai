"""Run the pre-registered UI evaluation (bench/scenarios/ui-eval.yaml) on opentelemetry-demo.

    uv run python -m bench.ui_eval bench/scenarios/ui-eval.yaml --workspace ~/opentelemetry-demo --out x

Flags are toggled by this script, declared as the scenario operator; the judges are told nothing about them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from unbidden.lab.ui import browser_judge, capture, visual_judge
from unbidden.workspace import Workspace


def set_flag(repo: Path, flag: str | None, variant: str | None) -> None:
    data = json.loads(
        subprocess.run(
            ["git", "-C", str(repo), "show", "HEAD:src/flagd/demo.flagd.json"], capture_output=True, text=True
        ).stdout
    )
    if flag and variant and variant.startswith("targeting:"):
        data["flags"][flag]["targeting"]["if"][1] = variant.split(":", 1)[1]
    elif flag:
        data["flags"][flag]["defaultVariant"] = variant
    (repo / "src/flagd/demo.flagd.json").write_text(json.dumps(data, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--key-env", default="MODEL_API_KEY")
    args = parser.parse_args()
    plan = yaml.safe_load(Path(args.scenario).read_text())
    ws = Workspace.find(Path(args.workspace).expanduser())
    store, mandate = ws.store(), ws.mandate()
    artifacts = ws.dir / "artifacts" / "ui"
    rows: list[dict[str, Any]] = []
    try:
        set_flag(ws.repo, None, None)
        time.sleep(plan["settle_s"])
        reference = capture(plan["page"], artifacts / "reference", wait_ms=plan["capture_wait_ms"])
        for cond in plan["conditions"]:
            set_flag(ws.repo, cond["flag"], cond.get("variant"))
            time.sleep(plan["settle_s"])
            for i in range(plan["repetitions"]):
                now = capture(plan["page"], artifacts / f"{cond['name']}-{i}", wait_ms=plan["capture_wait_ms"])
                browser = browser_judge(now.page, reference.page)
                visual = visual_judge(now, reference, store=store, mandate=mandate, key=os.environ[args.key_env])
                row: dict[str, Any] = {"condition": cond["name"], "run": i}
                for judge, answer in (("browser", browser), ("visual", visual)):
                    detected = answer["degraded"] is cond["degraded"]
                    named = bool(cond.get("part")) and bool(
                        re.search(cond["part"], answer["what"] or "", re.IGNORECASE)
                    )
                    row[judge] = {**answer, "detection": detected, "attribution": named if cond["degraded"] else None}
                rows.append(row)
                print(json.dumps(row)[:400], flush=True)
                Path(f"{args.out}.json").write_text(json.dumps(rows, indent=2) + "\n")
    finally:
        subprocess.run(["git", "-C", str(ws.repo), "checkout", "--", "src/flagd/demo.flagd.json"], check=False)
    for judge in ("browser", "visual"):
        det = sum(r[judge]["detection"] for r in rows)
        att = [r[judge]["attribution"] for r in rows if r[judge]["attribution"] is not None]
        print(f"{judge}: detection {det}/{len(rows)}, attribution {sum(att)}/{len(att)}")


if __name__ == "__main__":
    main()
