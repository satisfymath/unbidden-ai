"""Classify a judged deploy's outcome for the proposals it shipped, with the watcher's own code, on recorded rounds.

    uv run python -m bench.attach_outcome <repo> --deploy <index>

For a deploy whose verdict exists but whose outcome was not attached when it was judged. Recomputes each endpoint's
impact from the rounds in the store, with the same judge and criteria `LiveWatcher._judge` uses, then runs
`LiveWatcher._outcomes`. Writes no rounds and changes no criteria; prints what it recorded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unbidden.contracts.opportunity import Opportunity
from unbidden.contracts.world import WorldModel
from unbidden.observe.impact import judge_endpoint
from unbidden.observe.live import LiveWatcher
from unbidden.workspace import Workspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--deploy", type=int, required=True)
    args = parser.parse_args()
    workspace = Workspace(Path(args.repo).expanduser())
    store, mandate = workspace.store(), workspace.mandate()
    world = store.get("world", "world", WorldModel)
    assert world is not None
    watcher = LiveWatcher(workspace.repo, store, mandate, world, log=print)
    history = watcher.history()
    current = args.deploy
    baseline = watcher._baseline(history[: current + 1])  # pyright: ignore[reportPrivateUsage]
    need = mandate.operations.guard_samples
    judgeable = [t for t in store.round_targets() if watcher._served(t, baseline)]  # pyright: ignore[reportPrivateUsage]
    endpoints = [
        judge_endpoint(t, watcher._rounds(t, baseline), watcher._rounds(t, current), need)  # pyright: ignore[reportPrivateUsage]
        for t in judgeable
    ]
    watcher._outcomes(history, current, baseline, endpoints)  # pyright: ignore[reportPrivateUsage]
    for opp in store.list("opportunities", Opportunity):
        if opp.details.get("outcome"):
            found = {"opportunity": opp.id, "level": int(opp.evidence_level), "outcome": opp.details["outcome"]}
            print(json.dumps(found, indent=1, default=str))


if __name__ == "__main__":
    main()
