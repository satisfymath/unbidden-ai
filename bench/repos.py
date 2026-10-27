"""Level A benchmark: run Unbidden on many repositories it does not know, and record what happened to each.

    uv run python -m bench.repos bench/repos/level-a.yaml --split dev --workdir /tmp/x --out docs/bench/x

For each repository, at its pinned commit, in a throwaway directory: `init`, `map --no-model`, `scan`, `inbox`.
No model is called and nothing leaves but package downloads into the sandbox's dependency images. Every step's time,
exit code and the first lines of its error are kept, so a repository where Unbidden finds nothing or fails is a
row like any other.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

UNBIDDEN = ["uv", "run", "--project", str(Path(__file__).resolve().parents[1]), "unbidden"]
STEP_TIMEOUT_S = 3600


def _run(argv: list[str], cwd: Path, timeout: int = STEP_TIMEOUT_S) -> dict[str, Any]:
    started = time.monotonic()
    try:
        out = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        code, stdout, stderr = out.returncode, out.stdout, out.stderr
    except subprocess.TimeoutExpired:
        code, stdout, stderr = -1, "", f"timed out after {timeout} s"
    return {"code": code, "seconds": round(time.monotonic() - started, 1), "stdout": stdout, "stderr": stderr[-1500:]}


def _json(step: dict[str, Any]) -> Any:
    try:
        return json.loads(step["stdout"]) if step["code"] == 0 else None
    except ValueError:
        return None


def checkout(repo: dict[str, str], workdir: Path) -> tuple[Path, dict[str, Any]]:
    target = workdir / repo["name"]
    if not target.exists():
        target.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "remote", "add", "origin", repo["url"]], check=True)
    step = _run(["git", "fetch", "-q", "--depth", "1", "origin", repo["commit"]], target, timeout=1800)
    if step["code"] == 0:
        step = _run(["git", "checkout", "-q", "--force", "FETCH_HEAD"], target)
    return target, step


def run_one(repo: dict[str, str], workdir: Path) -> dict[str, Any]:
    row: dict[str, Any] = {"name": repo["name"], "split": repo["split"], "commit": repo["commit"], "steps": {}}
    target, fetched = checkout(repo, workdir)
    row["steps"]["checkout"] = {k: v for k, v in fetched.items() if k != "stdout"}
    if fetched["code"] != 0:
        row["outcome"] = "checkout failed"
        return row
    for name, argv in (
        ("init", ["init", "--json"]),
        ("map", ["map", "--no-model", "--json"]),
        ("scan", ["scan", "--json"]),
        ("inbox", ["inbox", "--all", "--json"]),
    ):
        step = _run([*UNBIDDEN, *argv], target)
        row["steps"][name] = {k: v for k, v in step.items() if k != "stdout"}
        row[name] = _json(step)
    world = row.pop("map") or {}
    scan = row.pop("scan") or {}
    inbox = row.pop("inbox") or []
    kinds: dict[str, int] = {}
    for r in (world.get("resources") or {}).values():
        if r["status"] != "obsolete":
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    row.pop("init", None)
    row["summary"] = {
        "languages": scan.get("languages"),
        "resources": kinds,
        "blind_spots": [b["what"] for b in world.get("blind_spots", [])] + list(scan.get("blind_spots") or []),
        "ci_understood": kinds.get("ci_job", 0) > 0,
        "reports": scan.get("reports"),
        "problems": scan.get("problems"),
        "opportunities": len(inbox),
        "by_category": _count(o.get("category", "?") for o in inbox),
        "by_status": _count(o.get("status", "?") for o in inbox),
        "seconds": round(sum(s["seconds"] for s in row["steps"].values()), 1),
    }
    failed = [n for n, s in row["steps"].items() if s["code"] != 0]
    row["outcome"] = (
        f"failed at {failed[0]}" if failed else ("no stack analyzed" if not scan.get("languages") else "ran")
    )
    return row


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def as_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Repository | Split | Outcome | Languages | CI understood | Analyzers (complete/total) | Findings "
        "| Opportunities | Time (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        s = r.get("summary") or {}
        reports = s.get("reports") or []
        complete = sum(1 for x in reports if x["completeness"] == "complete")
        findings = sum(x["findings"] for x in reports)
        lines.append(
            f"| {r['name']} | {r['split']} | {r['outcome']} | {', '.join(s.get('languages') or []) or '-'} | "
            f"{'yes' if s.get('ci_understood') else 'no'} | {complete}/{len(reports)} | {findings} | "
            f"{s.get('opportunities', 0)} | {s.get('seconds', '-')} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repos")
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    parser.add_argument("--only", nargs="*", help="names to run")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--out", required=True, help="writes <out>.json (rows, appended as each finishes) and <out>.md")
    args = parser.parse_args()
    repos = [
        r
        for r in yaml.safe_load(Path(args.repos).read_text())["repos"]
        if (args.split == "all" or r["split"] == args.split) and (not args.only or r["name"] in args.only)
    ]
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for repo in repos:
        print(f"{repo['name']}: running", flush=True)
        row = run_one(repo, workdir)
        rows.append(row)
        print(f"{repo['name']}: {row['outcome']} in {(row.get('summary') or {}).get('seconds', '?')} s", flush=True)
        Path(f"{args.out}.json").write_text(json.dumps(rows, indent=2) + "\n")
        Path(f"{args.out}.md").write_text(as_markdown(rows) + "\n")


if __name__ == "__main__":
    main()
