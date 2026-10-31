"""Preparation and the project's own checks only, as `observe.checks` makes them, before any full agent cycle.

    uv run --project <frozen worktree> python -m bench.checks_only <repo> <rev> [--registries a,b] --out FILE

The stack detected, the dependency image provisioned under a lab mandate (package registries only), the CI's test
plan read and run for one round in the sandbox, offline, with its services; the record `observe.checks` would keep
(status, tests collected, failed, why, scope, notes, command), and the image's notes. No model is called, nothing is
stored in a workspace. A regression tool of stage 10: the frozen evaluation's checks were never reproduced.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.observe.prepare import checks_record

CHECKS_TIMEOUT_S = 3600


def checks(repo: Path, rev: str, registries: list[str]) -> dict[str, object]:
    """The record `observe.checks` would keep for `repo` at `rev`, from a lab mandate allowing `registries`: the
    product's own `unbidden.observe.prepare.checks_record`, flattened for the benchmark's summaries."""
    mandate = Mandate(workspace="checks")
    mandate.autonomy.provision_dependencies = Autonomy.ALLOW
    mandate.egress.package_registries = registries
    record = checks_record(repo, rev, mandate, timeout_s=CHECKS_TIMEOUT_S)
    flat: dict[str, object] = {"repo": str(repo), **record}
    if isinstance(record.get("image"), dict):
        flat["image_notes"] = record["image"].get("notes")
        flat["image"] = record["image"].get("tag")
    if isinstance(record.get("stack"), dict):
        flat["python"] = record["stack"].get("python")
    if isinstance(record.get("plan"), dict):
        for k in ("source", "scope", "partial", "notes", "command"):
            flat[k] = record["plan"].get(k)
    return flat


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("rev")
    parser.add_argument("--registries", default="pypi.org,files.pythonhosted.org,deb.debian.org,registry.npmjs.org")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    record = checks(Path(args.repo).expanduser(), args.rev, args.registries.split(","))
    Path(args.out).write_text(json.dumps(record, indent=1, default=str))
    print(json.dumps({k: record.get(k) for k in ("status", "collected", "why", "scope")}, default=str)[:1500])


if __name__ == "__main__":
    main()
