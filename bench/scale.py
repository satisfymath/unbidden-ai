"""Scale benchmark: a full autonomous cycle on each repository Unbidden has never seen, and an honest record of it.

    uv run python -m bench.scale bench/repos/scale.yaml --split pilot --run pilot-1 \\
        --workdir ~/unbidden-bench --out docs/bench/2026-10-27-scale-pilot

Per repository, at its pinned commit, in a workspace of its own:

1. Checkout and `init`, then the benchmark mandate: autonomous for everything local (experiments, dependencies,
   delegation, new capabilities), nothing toward GitHub (these are third parties' upstreams), the `frontier` profile
   (the code is public, confirmed by GitHub; logs and data still never leave), and a remote spend cap per repository.
2. `map`, then `watch --once` under a wall-clock limit. Unbidden scans, decides, probes, experiments and prepares
   proposals on its own. Nobody chooses an opportunity, an experiment or a fix.
3. The record is read from the workspace's own state and the machine's spend ledger (`UNBIDDEN_RUN` attributes
   every remote call to the run and repository), never from Unbidden's printed output.

A paid run needs a verified credit balance (`unbidden spend --verified-balance`). The ledger enforces the budget for
every call in any case; this harness refuses to start a remote-model run without one unless told it is only a check
of the method. Workers are bounded (at most 3): each repository runs its own Docker sandboxes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bench.repos import checkout

PROJECT = Path(__file__).resolve().parents[1]
UNBIDDEN = ["uv", "run", "--project", str(PROJECT), "unbidden"]
MAX_WORKERS = 3


def bench_mandate(
    raw: dict[str, Any], *, profile: str, repo_budget_usd: float, fork: str | None = None, local_fallback: str = "deny"
) -> dict[str, Any]:
    """The mandate `init` wrote, set for an unattended run on someone else's repository. With `fork` (owner/name, an
    authorized fork), proposals become pull requests there; the upstream is never written to."""
    m = raw["mandate"]
    m["business_constraints"]["maximum_monthly_spend_usd"] = repo_budget_usd
    m["autonomy"].update(
        {
            "observe": "allow",
            "run_experiments": "allow",
            "provision_dependencies": "allow",
            "delegate_synthetic": "allow",
            "use_new_capabilities": "allow",
            "open_pull_requests": "deny",
            "merge_pull_requests": "deny",
            "deploy": "deny",
            "rollback": "deny",
        }
    )
    registries = m["egress"].setdefault("package_registries", [])
    if "deb.debian.org" not in registries:
        registries.append("deb.debian.org")  # C headers and compilers some installs need (D-027)
    m["models"] = {"profile": profile, "private_code_to_frontier": "deny", "local_fallback": local_fallback}
    if fork is not None:
        m["egress"]["github"]["repository"] = fork
        m["autonomy"]["open_pull_requests"] = "allow"
    elif m["egress"]["github"].get("repository"):
        # Without a fork the slug is the upstream's: kept only to read its CI, never to publish.
        m["autonomy"]["open_pull_requests"] = "deny"
    return raw


def _cli(argv: list[str], cwd: Path, env: dict[str, str], timeout: float) -> dict[str, Any]:
    """Run one command in its own process group; past the limit, engage the workspace's kill switch, then stop it."""
    started = time.monotonic()
    proc = subprocess.Popen(
        ["/usr/bin/time", "-l", *argv],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run([*UNBIDDEN, "kill", "benchmark wall-clock limit"], cwd=cwd, env=env, capture_output=True)
        try:
            out, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                out, err = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                out, err = proc.communicate()
    rss = re.search(r"(\d+)\s+maximum resident set size", err or "")
    err = re.split(r"^\s+[\d.]+ real\s", err or "", flags=re.MULTILINE)[0]  # drop time's own report
    return {
        "code": proc.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "timed_out": timed_out,
        "max_rss_mb": round(int(rss.group(1)) / 2**20, 1) if rss else None,
        "stdout": out or "",
        "log_tail": "\n".join((out or "").splitlines()[-40:]),
        "stderr": (err or "")[-1500:],
    }


def _docs(db: sqlite3.Connection, collection: str) -> list[dict[str, Any]]:
    return [json.loads(d) for (d,) in db.execute("SELECT doc FROM docs WHERE collection = ?", (collection,))]


def _events(db: sqlite3.Connection, type_: str) -> list[dict[str, Any]]:
    return [
        {**json.loads(p), "ts": ts} for ts, p in db.execute("SELECT ts, payload FROM events WHERE type = ?", (type_,))
    ]


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


def read_state(workspace: Path) -> dict[str, Any]:
    """Everything the record says about what Unbidden did, from its own state file."""
    path = workspace / ".unbidden" / "state.db"
    if not path.exists():
        return {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        kv = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM kv")}
        opps = _docs(db, "opportunities")
        decisions = _docs(db, "decisions")
        proposals = _docs(db, "proposals")
        runs = _docs(db, "model_runs")
        capabilities = _docs(db, "capabilities")
        verdicts = _events(db, "verdict.recorded")
        probes = [p for p in _events(db, "decision.made") if p.get("kind") == "robustness_probe"]
        denied = _count(p.get("rule", "?") for p in _events(db, "policy.denied"))
        blocked = len(_events(db, "egress.blocked"))
        experiments = len(_docs(db, "experiments"))
    scan = kv.get("last_scan") or {}
    tiers: dict[str, dict[str, float]] = {}
    for r in runs:
        t = tiers.setdefault(r["tier"], {"calls": 0, "ok": 0, "tokens_in": 0, "tokens_out": 0, "compute_s": 0.0})
        t["calls"] += 1
        t["ok"] += int(r["ok"])
        t["tokens_in"] += r["cost"]["tokens_in"]
        t["tokens_out"] += r["cost"]["tokens_out"]
        t["compute_s"] += r["usage"].get("duration_s", 0.0)
    return {
        "head": kv.get("head"),
        "probe": kv.get("last_probe"),
        "languages": scan.get("languages"),
        "blind_spots": scan.get("blind_spots"),
        "problems": scan.get("problems"),
        "analyzers": scan.get("reports"),
        "opportunities": [
            {
                "id": o["id"],
                "source": o["source"],
                "category": o["category"],
                "status": o["status"],
                "level": o["evidence_level"],
                "title": o["title"][:160],
                "attempts": o.get("details", {}).get("attempts", 0),
                "decision": (o.get("details", {}).get("decision") or {}).get("chosen"),
                "reason": ((o.get("details", {}).get("decision") or {}).get("reason") or "")[:200],
                "blocked": (o.get("details", {}).get("blocked") or {}).get("why"),
            }
            for o in opps
        ],
        "decisions": _count(d["chosen"] for d in decisions),
        "probe_decisions": probes,
        "verdicts": verdicts,
        "experiments": experiments,
        "proposals": [
            {
                k: p.get(k)
                for k in ("id", "opportunity_id", "branch", "base_sha", "commit_sha", "evidence_level", "status")
            }
            for p in proposals
        ],
        "capabilities_built": len(capabilities),
        "model_runs_by_tier": tiers,
        "policy_denied": denied,
        "egress_blocked": blocked,
    }


def classify(row: dict[str, Any]) -> str:
    """One outcome per repository, by rules fixed before the run."""
    if row["steps"]["checkout"]["code"] != 0:
        return "checkout failed"
    state = row.get("state") or {}
    if not state.get("languages"):
        return "unsupported stack"
    analyzers = state.get("analyzers") or []
    probed = bool((state.get("probe") or {}).get("ran"))  # tests that actually ran, not a probe only decided
    if not any(a["completeness"] == "complete" for a in analyzers) and not probed:
        return "bootstrap failed"
    levels = [o["level"] for o in state.get("opportunities") or []]
    if any(v.get("improved") and v.get("level", 0) >= 4 for v in state.get("verdicts") or []):
        return "validated improvement (L4)"
    if not levels:
        return "nothing found"
    if state.get("experiments"):
        return "found, experiments did not validate"
    return "found, not experimented"


def run_one(repo: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    tag = f"bench:{args.run}:{repo['name']}"
    row: dict[str, Any] = {
        "name": repo["name"],
        "run": args.run,
        "tag": tag,
        "meta": {
            k: repo.get(k) for k in ("url", "commit", "split", "license", "language", "shape", "database", "domain")
        },
        "started_at": datetime.now(UTC).isoformat(),
        # Each repository launches Unbidden from this checkout: the code under test is recorded per row.
        "unbidden": unbidden_version(),
        "steps": {},
    }
    workdir = Path(args.workdir).expanduser()
    target, fetched = checkout(repo, workdir)
    row["steps"]["checkout"] = {k: v for k, v in fetched.items() if k != "stdout"}
    if fetched["code"] != 0:
        row["outcome"] = classify(row)
        return row
    env = {**os.environ, "UNBIDDEN_RUN": tag}
    if not (target / ".unbidden" / "mandate.yaml").exists():
        row["steps"]["init"] = _strip(_cli([*UNBIDDEN, "init", "--json"], target, env, 300))
        mandate_path = target / ".unbidden" / "mandate.yaml"
        if mandate_path.exists():
            raw = yaml.safe_load(mandate_path.read_text())
            mandate_path.write_text(
                yaml.safe_dump(
                    bench_mandate(
                        raw,
                        profile=args.profile,
                        repo_budget_usd=args.repo_budget,
                        fork=f"{args.fork_owner}/{repo['name']}" if args.fork_owner else None,
                        local_fallback=args.local_fallback,
                    ),
                    sort_keys=False,
                )
            )
    row["steps"]["map"] = _strip(_cli([*UNBIDDEN, "map", "--json"], target, env, 1800))
    watch = _cli([*UNBIDDEN, "watch", "--once"], target, env, args.minutes * 60)
    row["steps"]["watch"] = _strip(watch)
    row["state"] = read_state(target)
    row["finished_at"] = datetime.now(UTC).isoformat()
    row["seconds"] = round(sum(s["seconds"] for s in row["steps"].values()), 1)
    row["outcome"] = classify(row)
    return row


def _strip(step: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in step.items() if k != "stdout"}


def spend_by_run(run: str) -> dict[str, Any]:
    from unbidden.brain.spend import SpendLedger, summarize

    rows = [r for r in SpendLedger().rows() if (r["run"] or "").startswith(f"bench:{run}:")]
    return {
        "by_repo": summarize(rows, "run"),
        "by_model": summarize(rows, "model"),
        "by_purpose": summarize(rows, "purpose"),
    }


def unbidden_version() -> dict[str, Any]:
    git = ["git", "-C", str(PROJECT)]
    commit = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run([*git, "status", "--porcelain", "--", "unbidden"], capture_output=True, text=True).stdout
    return {"commit": commit, "dirty": bool(dirty.strip())}


def deps_images() -> set[str]:
    out = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True, check=False
    )
    return {line for line in out.stdout.split() if line.startswith("unbidden-deps-")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repos")
    parser.add_argument("--split", choices=["pilot", "holdout", "all"], default="pilot")
    parser.add_argument("--only", nargs="*", help="names to run")
    parser.add_argument("--run", required=True, help="run name; tags every remote call as bench:<run>:<repo>")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--out", required=True, help="writes <out>.json, appended as each repository finishes")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--minutes", type=float, default=45, help="wall-clock limit of each autonomous cycle")
    parser.add_argument("--repo-budget", type=float, default=1.0, help="remote spend cap per repository, US$")
    parser.add_argument("--profile", choices=["local", "local-first", "frontier"], default="frontier")
    parser.add_argument("--method-check", action="store_true", help="run without a verified balance (allowance only)")
    parser.add_argument(
        "--local-fallback",
        choices=["allow", "deny"],
        default="deny",
        help="whether the local model takes over when the remote one fails (always recorded)",
    )
    parser.add_argument("--fork-owner", help="publish pull requests to <owner>/<name>, an authorized fork")
    parser.add_argument("--cleanup-images", action="store_true", help="remove dependency images this run created")
    args = parser.parse_args()
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")

    from unbidden.brain.spend import SpendLedger

    if unbidden_version()["dirty"]:
        raise SystemExit("Unbidden's package has uncommitted changes: a benchmark runs on one commit; commit first")
    status = SpendLedger().status()
    print(f"budget: {status.reason}; available US${status.available_usd:.2f}", flush=True)
    if args.profile != "local" and not status.verified and not args.method_check:
        raise SystemExit(
            "no verified credit balance: record it with `unbidden spend --verified-balance <USD> --source <where>`, "
            "or pass --method-check to run within the unverified allowance only"
        )
    planned = args.repo_budget * len(yaml.safe_load(Path(args.repos).read_text())["repos"])
    if status.verified and planned > status.available_usd:
        print(f"note: per-repository caps add up to US${planned:.2f}; the ledger stops at the budget", flush=True)

    repos = [
        r
        for r in yaml.safe_load(Path(args.repos).read_text())["repos"]
        if (args.split == "all" or r["split"] == args.split) and (not args.only or r["name"] in args.only)
    ]
    out_json = Path(f"{args.out}.json")
    rows: list[dict[str, Any]] = json.loads(out_json.read_text())["rows"] if out_json.exists() else []
    done = {r["name"] for r in rows}
    lock = threading.Lock()
    images_before = deps_images()

    def write() -> None:
        data = {
            "run": args.run,
            "manifest": args.repos,
            "unbidden_commit": subprocess.run(
                ["git", "-C", str(PROJECT), "rev-parse", "HEAD"], capture_output=True, text=True
            ).stdout.strip(),
            "settings": {
                k: getattr(args, k)
                for k in ("split", "workers", "minutes", "repo_budget", "profile", "local_fallback", "fork_owner")
            },
            "rows": rows,
            "spend": spend_by_run(args.run),
        }
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(data, indent=2, default=str) + "\n")

    def work(repo: dict[str, Any]) -> None:
        print(f"{repo['name']}: running", flush=True)
        row = run_one(repo, args)
        with lock:
            rows.append(row)
            write()
        print(f"{repo['name']}: {row['outcome']} in {row.get('seconds', '?')} s", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, [r for r in repos if r["name"] not in done]))
    if args.cleanup_images:
        for image in sorted(deps_images() - images_before):
            subprocess.run(["docker", "rmi", image], capture_output=True, check=False)
            print(f"removed {image} (created by this run)", flush=True)
    write()


if __name__ == "__main__":
    main()
