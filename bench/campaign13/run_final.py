"""Campaign 13, the final pass: every repository of the corpus, in parallel, resumable, one table of 39 rows.

    uv run python -m bench.campaign13.run_final bench/campaign13/corpus.yaml --phase final \
        --out docs/bench/campaign13/final --workers 3 --order libraries-first [--all-python] [--only a,b] [--dry-run]

Level B (`level_b.py`) on every eligible repository (`level_b: true` in the corpus, or every Python repository with
`--all-python`); Level A (`level_a.py`, US$0) on every other one, so the final table has one row per repository. The
jobs go to N worker processes; worker i owns the port range `BASE_PORT + i * SPAN ...` (dashboard, Level A dashboard,
hand lab application and database), so no two workers ever share a port. Each repository logs to `<out>/<repo>/
run.log` and writes its records under `<out>/<repo>/`; the summaries are updated under a file lock. A repository whose
record already exists is skipped (resume after a stop). The run header (`<out>/run-header.json`) records the host and
the versions of `uv`, `gh`, `docker`, `act`, `node` and `git` found on PATH.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import multiprocessing
import queue
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from bench.campaign13.common import candidate_of, host_header, locked, scrub

BASE_PORT = 18800
SPAN = 10  # ports per worker: 0 dashboard (B), 1 dashboard (A), 2 lab application, 3 lab database; the rest spare
NOT_PYTHON = {"typescript", "go"}
FIRST_FAMILIES = ("library", "cli")  # `--order libraries-first`: nothing to bring up, shortest runs, earliest PRs


@dataclass(frozen=True)
class Job:
    name: str
    level: str  # "A" or "B"
    run: int = 1


def worker_ports(index: int, base: int = BASE_PORT, span: int = SPAN) -> dict[str, int]:
    """Worker `index`'s ports: a range of `span` ports of its own."""
    if index < 0:
        raise ValueError("a worker index is never negative")
    start = base + index * span
    return {"dashboard": start, "ui_a": start + 1, "lab": start + 2, "lab_db": start + 3}


def is_python(repo: dict[str, Any]) -> bool:
    return str(repo.get("family")) not in NOT_PYTHON and repo.get("build") != "n/a"


def eligible_b(repo: dict[str, Any], all_python: bool = False) -> bool:
    return bool(repo.get("level_b")) or (all_python and is_python(repo))


def plan(
    repos: list[dict[str, Any]],
    *,
    order: str = "corpus",
    all_python: bool = False,
    only: set[str] | None = None,
    runs: int = 1,
) -> list[Job]:
    """The jobs in the order they are handed to the workers: Level B first (they are the long ones), then Level A;
    with `libraries-first`, libraries and CLIs before applications inside each level; corpus order otherwise."""
    chosen = [r for r in repos if not only or r["name"] in only]

    def rank(r: dict[str, Any]) -> int:
        return 0 if order == "libraries-first" and r.get("family") in FIRST_FAMILIES else 1

    b = sorted((r for r in chosen if eligible_b(r, all_python)), key=rank)  # sorted() is stable: corpus order inside
    a = sorted((r for r in chosen if not eligible_b(r, all_python)), key=rank)
    return [Job(r["name"], "B", n) for r in b for n in range(1, runs + 1)] + [Job(r["name"], "A") for r in a]


def record_path(out: Path, job: Job) -> Path:
    return out / job.name / ("A.json" if job.level == "A" else f"B{job.run}.json")


def pending(jobs: list[Job], out: Path) -> list[Job]:
    """Resume: a job whose record exists is done."""
    return [j for j in jobs if not record_path(out, j).exists()]


def log_line(out: Path, job: Job, text: str) -> None:
    path = out / job.name / "run.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} [{job.level}{job.run}] {scrub(text)}\n")


def execute(job: Job, repo: dict[str, Any], ports: dict[str, int], args: dict[str, Any]) -> dict[str, Any]:
    """One job, in the worker's process, on the worker's ports. Imported here: a dry run needs none of it."""
    from bench.campaign13.common import update_summary

    out = Path(args["out"])
    if job.level == "B":
        from bench.campaign13.level_b import level_b

        line = level_b(repo, job.run, args["phase"], out, ports["dashboard"], args["candidate"], args["wheel"],
                       budget=args["budget"], lab_ports=(ports["lab"], ports["lab_db"]))  # fmt: skip
        update_summary(out / "summary-B.json", line, keys=("name", "run"))
        return line
    from bench.campaign13.level_a import level_a

    line = level_a(repo, args["phase"], out, ports["ui_a"], args["candidate"], args["wheel"], ci_env=args["ci_env"])
    update_summary(out / "summary-A.json", line)
    return line


def worker(index: int, jobs: Any, repos: dict[str, dict[str, Any]], args: dict[str, Any], runner: Any = None) -> None:
    """Take jobs until the queue is empty; a failing job is logged and recorded in `failures.json`, never fatal."""
    ports = worker_ports(index, args.get("base_port", BASE_PORT))
    run_one = runner or execute
    out = Path(args["out"])
    while True:
        try:
            # A short wait, not get_nowait: a worker that asks before the queue's feeder thread has handed the items
            # over sees it empty and leaves (final pass 2026-11-04: one of five workers, two of three, left at once).
            job: Job = jobs.get(timeout=5)
        except queue.Empty:
            return
        log_line(out, job, f"worker {index} starts on ports {ports}")
        started = time.monotonic()
        try:
            line = run_one(job, repos[job.name], ports, args)
            log_line(out, job, f"done in {time.monotonic() - started:.0f} s: {json.dumps(line, default=str)[:600]}")
        except Exception as exc:  # one repository's failure is its own row, the others go on
            log_line(out, job, f"FAILED: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}")
            path = out / "failures.json"
            with locked(path):
                failures = json.loads(path.read_text()) if path.exists() else []
                failures.append({**asdict(job), "worker": index, "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
                path.write_text(json.dumps(failures, indent=1))


def run_all(jobs: list[Job], repos: dict[str, dict[str, Any]], args: dict[str, Any], workers: int) -> None:
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    for job in jobs:
        q.put(job)
    time.sleep(0.2)  # the queue's feeder thread hands the items over before the workers ask
    procs = [ctx.Process(target=worker, args=(i, q, repos, args), name=f"c13-worker-{i}") for i in range(workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


def header(args: argparse.Namespace, jobs: list[Job], candidate: str, wheel: str) -> dict[str, Any]:
    return {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "phase": args.phase,
        "workers": args.workers,
        "order": args.order,
        "all_python": args.all_python,
        "candidate": candidate,
        "wheel_sha256": wheel,
        "ports": {i: worker_ports(i, args.base_port) for i in range(args.workers)},
        "jobs": [asdict(j) for j in jobs],
        **host_header(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("corpus")
    parser.add_argument("--phase", default="final")
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--order", choices=("corpus", "libraries-first"), default="corpus")
    parser.add_argument("--only", default="", help="comma-separated repository names")
    parser.add_argument("--all-python", action="store_true", help="Level B on every Python repository")
    parser.add_argument("--runs", type=int, default=1, help="Level B runs per repository")
    parser.add_argument("--candidate", default="", help="a named candidate in the corpus")
    parser.add_argument("--budget", default="2", help="each project's monthly cap in US$ (Level B)")
    parser.add_argument("--ci-env", action="store_true", help="Level A: the team's CI job prepares the environment")
    parser.add_argument("--base-port", type=int, default=BASE_PORT)
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the header; run nothing")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    corpus = yaml.safe_load(Path(args.corpus).read_text())
    repos = {r["name"]: r for r in corpus["repos"]}
    only = {n for n in args.only.split(",") if n}
    unknown = only - set(repos)
    if unknown:
        parser.error(f"not in the corpus: {', '.join(sorted(unknown))}")
    out = Path(args.out).expanduser().resolve()  # absolute: the browser check runs from frontend/
    candidate, wheel = candidate_of(corpus, args.candidate)
    jobs = plan(corpus["repos"], order=args.order, all_python=args.all_python, only=only or None, runs=args.runs)
    todo = pending(jobs, out)
    head = header(args, jobs, candidate, wheel) | {"pending": [asdict(j) for j in todo]}
    if args.dry_run:
        print(json.dumps(head, indent=1, default=str))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        (out / "run-header.json").write_text(json.dumps(head, indent=1, default=str))
    print(f"{len(jobs)} jobs, {len(todo)} pending, {args.workers} workers", flush=True)
    shared = {"out": str(out), "phase": args.phase, "candidate": candidate, "wheel": wheel, "budget": args.budget,
              "ci_env": args.ci_env, "base_port": args.base_port}  # fmt: skip
    run_all(todo, repos, shared, min(args.workers, max(1, len(todo))))
    left = pending(jobs, out)
    print(f"done: {len(jobs) - len(left)}/{len(jobs)} records; {len(left)} without one", flush=True)
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
