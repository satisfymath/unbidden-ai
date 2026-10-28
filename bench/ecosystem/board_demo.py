"""The demo: Unbidden finds that the screen contradicts the data, finds why in the code, fixes it, and shows it holds.

    uv run python -m bench.ecosystem.board_demo <worktree> [--case style] [--perception dom] [--policy spark]

Reproducible on this machine's lab (`depot_lab up` first). The scenario is prepared, and said so: the harness seeds
one defect in a neutrally worded commit of the board's repository (the case's name is never shown to Unbidden), and
gives Unbidden a workspace with the goal, two read-only grants and the declared deploy and check steps, as a person
would. Then it only watches: two cycles of `unbidden watch --once`, then the model-free checker. It prints what the
harness prepared, what Unbidden did, what Meta's models did (each call, model, cost), how much a person helped, and
what the checker says; and writes the same as `demo.json` with the screenshots before and after.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from bench.ecosystem import board_check, board_lab
from bench.ecosystem.board_eval import LAB, _state  # pyright: ignore[reportPrivateUsage]

AFTER = ("verified", "short", "flagged", "false_flags", "preserved", "problems")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree")
    parser.add_argument("--case", default="style", choices=sorted(board_lab.DEFECTS))
    parser.add_argument("--perception", default="dom", choices=["dom", "vision", "vision_sam"])
    parser.add_argument("--policy", default="spark", choices=["local", "spark", "wonder"])
    parser.add_argument("--out", default=str(LAB / "demo"))
    args = parser.parse_args()
    worktree, out = Path(args.worktree).expanduser(), Path(args.out).expanduser()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print("1. The harness prepares (the only part that knows the case):")
    board_lab.reset(LAB, args.case, [], 5_2026, 24)
    before = board_check.check(LAB, out / "checker-before")
    print(f"   board reset with one seeded defect in a commit titled {board_lab.NEUTRAL!r}; data seeded (24 bins)")
    print(f"   checker before: {len(before['short'])} bins short, {len(before['flagged'])} correctly flagged")
    given = ["--policy", args.policy, "--perception", args.perception]
    subprocess.run(["uv", "run", "python", "-m", "bench.ecosystem.board_workspace", str(worktree), *given],
                   cwd=worktree, check=True, capture_output=True)  # fmt: skip
    repo = board_lab.repo_dir(LAB)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()  # fmt: skip
    print("   Unbidden is given: the goal (no hint of the defect), read-only grants to the picks database and the")
    print("   Depot API, the app's declared check and deploy steps, lab staging only.")

    print("\n2. Unbidden works on its own (two cycles):")
    started = time.monotonic()
    for n in (1, 2):
        ran = subprocess.run(["uv", "run", "--project", str(worktree), "unbidden", "watch", "--once"], cwd=repo,
                             capture_output=True, text=True, timeout=3600)  # fmt: skip
        (out / f"cycle-{n}.log").write_text(ran.stdout + ran.stderr)
        for line in (ran.stdout + ran.stderr).splitlines():
            if "goal board-flags" in line or "capability need" in line:
                print(f"   cycle {n}: {line.strip()[9:180]}")
    wall = round(time.monotonic() - started, 1)
    state = _state(repo)
    commits = subprocess.run(["git", "-C", str(repo), "log", "--format=%h %s", f"{base}..HEAD"], capture_output=True,
                             text=True, check=False).stdout.splitlines()  # fmt: skip
    fixed = next((r for r in state["goal_runs"] if r["status"] == "page_fixed"), None)
    if fixed:
        first = fixed["evidence"]["before"]
        print(f"   found: {len(first['discrepancies'])} rows shown wrongly; cause: {first['cause'][:160]}")
        for a in fixed["evidence"].get("attempts", []):
            print(f"   change {a.get('commit', '')[:12]}: {a.get('result')}; checks: "
                  f"{'passed' if (a.get('checks') or {}).get('ok') else 'failed'}")  # fmt: skip
            (out / "patch.diff").write_text(a.get("patch", ""))
    print(f"   commits: {commits or 'none'}")

    print("\n3. What Meta's models did:")
    for m in state["model_runs"]:
        print(f"   {m['purpose']:22} {m['model']:18} {m['tier']:6} US${m['usd']:.4f}")
    usd = sum(m["usd"] for m in state["model_runs"])

    print("\n4. The independent checker (model-free, never the agent's code):")
    after = board_check.check(LAB, out / "checker-after")
    print(f"   verified: {after['verified']}; flagged {len(after['flagged'])}/{len(after['short'])} short bins; "
          f"false flags {after['false_flags'] or 'none'}; preserved {after['preserved']}")  # fmt: skip
    for p in after["problems"][:5]:
        print(f"   problem: {p}")

    print(f"\n5. Person's help: none during the run. Model calls {len(state['model_runs'])}, US${usd:.4f}; {wall}s.")
    (out / "demo.json").write_text(json.dumps({
        "case": args.case, "prepared_by_harness": True, "perception": args.perception, "policy": args.policy,
        "checker_before": {k: before[k] for k in ("short", "flagged", "problems")},
        "checker_after": {k: after[k] for k in AFTER},
        "commits": commits, "goal_runs": state["goal_runs"], "model_runs": state["model_runs"], "usd": usd,
        "wall_s": wall, "human_interventions": 0,
    }, indent=1, default=str))  # fmt: skip
    print(f"   records: {out}")


if __name__ == "__main__":
    main()
