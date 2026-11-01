"""Campaign level A: preparation and the project's checks on every repository of a corpus, no model, no spend.

    uv run --project <frozen worktree> python -m bench.level_a bench/repos/campaign-v1.yaml --out DIR [--only a,b]

One record per repository (`bench/checks_only.py`), then a summary: for each, the status, tests collected, the
plan's source and scope, the wall time, and the image's notes. Every repository stays in the denominator.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import yaml

from bench.checks_only import checks

REGISTRIES = ["pypi.org", "files.pythonhosted.org", "deb.debian.org", "registry.npmjs.org"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus")
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    repos = yaml.safe_load(Path(args.corpus).read_text())["repos"]
    only = {n for n in args.only.split(",") if n}
    summary = []
    for repo in repos:
        if only and repo["name"] not in only:
            continue
        path = Path(os.path.expanduser(repo["path"]))
        line: dict[str, object] = {"name": repo["name"], "shape": repo["shape"], "commit": repo["commit"][:12]}
        if not (path / ".git").exists():
            line |= {"status": "missing", "why": f"{path} is not a git repository"}
        else:
            load = os.getloadavg()[0]
            record = checks(path, repo["commit"], REGISTRIES)
            (out / f"{repo['name']}.json").write_text(json.dumps(record, indent=1, default=str))
            line |= {k: record.get(k) for k in ("status", "collected", "source", "scope", "wall_s", "python")}
            failed = record.get("failed")
            line["failed"] = len(failed) if isinstance(failed, list) else None
            line["why"] = str(record.get("why") or "")[-300:]
            line["host_load_at_start"] = load
        summary.append(line)
        print(json.dumps(line, default=str)[:600], flush=True)
    (out / "summary.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "repos": summary},
                                                 indent=1, default=str))  # fmt: skip
    reproduced = [s for s in summary if s.get("status") in ("passed", "failed") and s.get("collected")]
    print(json.dumps({"checks_reproduced": len(reproduced), "of": len(summary)}))


if __name__ == "__main__":
    main()
