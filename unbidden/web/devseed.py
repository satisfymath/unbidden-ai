"""Seed a development workspace with records written through the engine's own `Store`, for the live reader.

    uv run python -m unbidden.web.devseed ~/unbidden-fe-dev/sample          # create and seed once
    uv run python -m unbidden.web.devseed ~/unbidden-fe-dev/sample --tick 30 --every 10   # then append events

The workspace is marked (`.unbidden/web-dev-seed`) so the web layer says its records come from a seed, not a run.
Never point this at an evaluation workspace: it writes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from unbidden.store import Store
from unbidden.web.demo import DemoTicker, populate
from unbidden.workspace import Workspace


def seed(repo: Path) -> Store:
    repo = repo.expanduser().resolve()
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "README.md").write_text("# sample\n\nA development workspace for Unbidden's web layer.\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=dev", "-c", "user.email=dev@localhost", "commit", "-qm", "seed"],
            check=True,
        )
    ws = Workspace(repo)
    ws.init()
    marker = ws.dir / "web-dev-seed"
    store = ws.store()
    if marker.exists():
        print(f"{repo} already seeded; events will be appended only", file=sys.stderr)
        return store
    populate(store)
    marker.write_text("records written by unbidden.web.devseed, not by a run\n")
    print(f"seeded {repo}", file=sys.stderr)
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--tick", type=int, default=0, help="append this many events after seeding")
    parser.add_argument("--every", type=float, default=5.0, help="seconds between events")
    args = parser.parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    for forbidden in ("mealie", "opentelemetry-demo", "unbidden-lab"):
        if forbidden in repo.parts:
            print(f"refusing to seed {repo}: an evaluation workspace", file=sys.stderr)
            return 2
    store = seed(repo)
    ticker = DemoTicker(store)
    for i in range(args.tick):
        event = ticker.tick()
        print(f"event {event.seq} {event.type.value}", file=sys.stderr)
        if i + 1 < args.tick:
            time.sleep(args.every)
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
