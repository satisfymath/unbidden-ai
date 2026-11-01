"""The whole product on each planted repository, from the initial state: no opportunity, location or ticket given.

    uv run python -m bench.eval2.run_product <scenarios dir> <version worktree> --label <name> --out <dir>
        [--experiments N]

For each repository: a fresh copy, `unbidden init`, a fixed mandate (local model only, no remote, no pull request),
`scan`, `decide`, then `try` on at most N opportunities the Director chose to experiment on, in its order. Every
command runs with the version's own code (`uv run --project <worktree>`). Records commands, wall time, the decisions,
each experiment's verdict and patch, and the model calls the workspace recorded. Reads no oracle.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path
from typing import Any

MANDATE = """mandate:
  workspace: eval2
  priorities: [correctness]
  business_constraints:
    maximum_monthly_spend_usd: 0
  autonomy:
    observe: allow
    run_experiments: allow
    provision_dependencies: allow
    delegate_synthetic: deny
    open_pull_requests: deny
    merge_pull_requests: deny
    deploy: deny
    rollback: deny
    use_new_capabilities: deny
  egress:
    package_registries: [pypi.org, files.pythonhosted.org]
    remote_models:
      destinations: []
  models:
    profile: local
"""


def _run(worktree: Path, repo: Path, *args: str, timeout: float = 3600) -> tuple[int, str, float]:
    started = time.monotonic()
    out = subprocess.run(
        ["uv", "run", "--project", str(worktree), "unbidden", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return out.returncode, out.stdout, time.monotonic() - started


def _state(repo: Path, collection: str) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(f"file:{repo / '.unbidden' / 'state.db'}?mode=ro", uri=True)) as conn:
        return [json.loads(d) for (d,) in conn.execute("SELECT doc FROM docs WHERE collection = ?", (collection,))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios")
    parser.add_argument("worktree")
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--experiments", type=int, default=1)
    args = parser.parse_args()
    worktree, out = Path(args.worktree).expanduser(), Path(args.out).expanduser()
    commit = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    rows = []
    for source in sorted((Path(args.scenarios).expanduser() / "repos").iterdir()):
        repo = out / args.label / source.name
        if repo.exists():
            shutil.rmtree(repo)
        subprocess.run(["git", "clone", "-q", str(source), str(repo)], check=True)
        row: dict[str, Any] = {"scenario": source.name, "version": args.label, "commit": commit, "steps": {}}
        _run(worktree, repo, "init")
        (repo / ".unbidden" / "mandate.yaml").write_text(MANDATE)
        for step in ("scan", "decide"):
            code, stdout, seconds = _run(worktree, repo, step, "--json")
            row["steps"][step] = {"exit": code, "seconds": round(seconds, 1)}
            if step == "decide" and code == 0:
                row["decide"] = json.loads(stdout)
        row["opportunities"] = _state(repo, "opportunities")
        chosen = [
            d["id"] for d in (row.get("decide") or {}).get("decisions", []) if d.get("chosen") == "run_experiment"
        ]
        row["experiments"] = []
        for opp_id in chosen[: args.experiments]:
            code, stdout, seconds = _run(worktree, repo, "try", opp_id, "--json", timeout=5400)
            result: dict[str, Any] = {"opportunity": opp_id, "exit": code, "seconds": round(seconds, 1)}
            if code == 0:
                result |= json.loads(stdout)
            row["experiments"].append(result)
        row["model_runs"] = _state(repo, "model_runs")
        rows.append(row)
        print(
            f"{source.name}: {len(row['opportunities'])} opportunities, {len(chosen)} to experiment on, "
            f"{len(row['experiments'])} run",
            flush=True,
        )
    (out / f"product-{args.label}.json").write_text(json.dumps(rows, indent=1, default=str))


if __name__ == "__main__":
    main()
