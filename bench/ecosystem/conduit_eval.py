"""Run the stage 7 transfer protocol on Conduit (docs/bench/stage7-transfer.md, stage7-freeze.md), B before A.

    uv run python -m bench.ecosystem.conduit_eval <frozen worktree> --out DIR

Each run starts from the same restored state and a clean workspace: the repository back at the pinned commit (only
the lab's own excluded files kept), the synthetic data re-seeded (the same), a fresh token, a new `.unbidden`; after
it, the whole workspace (state, artifacts, memory) is moved out. B never sees A's goal, findings or proposals: it
runs first, and nothing of it is carried over. The ledger is read before and after every run. The harness only
prepares and records; it never tells Unbidden anything about the application.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from bench.ecosystem import conduit_lab
from bench.ecosystem.conduit_workspace import archive

LAB = Path.home() / "unbidden-lab"
RUNS = [("B-1", "proactive"), ("A-1", "goal"), ("A-2", "goal"), ("B-2", "proactive"), ("A-3", "goal"),
        ("B-3", "proactive"), ("A-4", "goal"), ("B-4", "proactive"), ("A-5", "goal"),
        ("B-5", "proactive"), ("A-6", "goal"),
        ("B-6", "proactive"), ("A-7", "goal"),
        ("B-7", "proactive"), ("A-8", "goal")]  # fmt: skip


def ledger(worktree: Path) -> float:
    out = subprocess.run(["uv", "run", "--project", str(worktree), "unbidden", "spend", "--json"],
                         capture_output=True, text=True, check=True).stdout  # fmt: skip
    return round(float(json.loads(out)["spent_since_verification_usd"]), 4)


def restore(worktree: Path) -> dict[str, Any]:
    repo = conduit_lab.repo_dir(LAB)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", "--force", conduit_lab.COMMIT], check=True)
    subprocess.run(["git", "-C", str(repo), "clean", "-q", "-fd"], check=True)  # excluded lab files stay (-x not given)
    for branch in subprocess.run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads"],
                                 capture_output=True, text=True, check=True).stdout.split():  # fmt: skip
        subprocess.run(["git", "-C", str(repo), "branch", "-q", "-D", branch], check=False)
    counts = conduit_lab.seed(LAB)
    conduit_lab.token(LAB)
    return {"commit": conduit_lab.COMMIT, "data": counts}


def run(worktree: Path, name: str, mode: str, out: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"run": name, "mode": mode, "restored": restore(worktree), "usd_before": ledger(worktree)}
    repo = conduit_lab.repo_dir(LAB)
    subprocess.run(["uv", "run", "python", "-m", "bench.ecosystem.conduit_workspace", str(worktree), "--mode", mode],
                   cwd=worktree, check=True, capture_output=True)  # fmt: skip
    logs, started = [], time.monotonic()

    def cycles(numbers: tuple[int, ...]) -> None:
        for cycle in numbers:
            argv = ["uv", "run", "--project", str(worktree), "unbidden", "watch", "--once"]
            ran = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=5400)
            logs.append(f"== cycle {cycle} (exit {ran.returncode})\n{ran.stdout}{ran.stderr}")

    cycles((1, 2))
    # A person answers what Unbidden asked, and only that, from the answers this protocol declares a person gives:
    # adding a package registry it names. Counted as an intervention; then two more cycles.
    record["interventions"] = []
    show = ["uv", "run", "--project", str(worktree), "unbidden", "activity", "--json"]
    asked = json.loads(subprocess.run(show, cwd=repo, capture_output=True, text=True, check=False).stdout or "{}")
    for request in asked.get("needs_a_person", []):
        wanted = re.search(r"add ([\w.\-, ]+) to egress\.package_registries", str(request.get("what", "")))
        if wanted:
            hosts = [h.strip() for h in wanted.group(1).split(",") if h.strip()]
            mandate = repo / ".unbidden" / "mandate.yaml"
            text = mandate.read_text()
            listed = re.search(r"package_registries: \[([^\]]*)\]", text)
            if listed:
                have = [h.strip() for h in listed.group(1).split(",") if h.strip()]
                merged = ", ".join(dict.fromkeys([*have, *hosts]))
                mandate.write_text(text.replace(listed.group(0), f"package_registries: [{merged}]"))
                record["interventions"].append({"answered": request, "granted": hosts, "at": time.time()})
    if record["interventions"]:
        cycles((3, 4))
    record["wall_s"] = round(time.monotonic() - started, 1)
    activity = subprocess.run(["uv", "run", "--project", str(worktree), "unbidden", "activity", "--json"], cwd=repo,
                              capture_output=True, text=True, check=False).stdout  # fmt: skip
    record["repo_after"] = subprocess.run(["git", "-C", str(repo), "status", "--short"], capture_output=True,
                                          text=True, check=False).stdout.strip()  # fmt: skip
    heads = ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads"]
    record["branches_after"] = subprocess.run(heads, capture_output=True, text=True, check=False).stdout.split()
    record["usd_after"] = ledger(worktree)
    where = out / name
    where.mkdir(parents=True, exist_ok=True)
    (where / "cycles.log").write_text("\n\n".join(logs))
    (where / "activity.json").write_text(activity)
    record["workspace"] = str(archive(LAB, f"{out.name}-{name}"))
    (where / "record.json").write_text(json.dumps(record, indent=1))
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree")
    parser.add_argument("--out", required=True)
    parser.add_argument("--runs", default=",".join(n for n, _ in RUNS))
    args = parser.parse_args()
    worktree, out = Path(args.worktree).expanduser(), Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()  # fmt: skip
    (out / "frozen.json").write_text(json.dumps({"product": commit, "app": conduit_lab.COMMIT}, indent=1))
    wanted = args.runs.split(",")
    for name, mode in RUNS:
        if name in wanted:
            rec = run(worktree, name, mode, out)
            print(json.dumps({k: rec[k] for k in ("run", "usd_before", "usd_after", "wall_s")}), flush=True)


if __name__ == "__main__":
    main()
