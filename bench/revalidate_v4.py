"""Revalidate a recorded L4 under criteria perf-v4, on an isolated copy at its base commit (stage 10).

    uv run --project <frozen worktree> python -m bench.revalidate_v4 --source <repo> --store <state.db> --opp ID
        --rev BASE --name NAME --out DIR --envelope s10-dev

The original repository and its workspace are only read: the repository is cloned (`git clone --no-hardlinks`) to
`~/unbidden-lab/reval/<name>` and checked out at the base commit the L4 was measured on; the opportunity is read from
the original store with SQLite's read-only mode. The lab then prepares the experiment again from the project's own
evidence (a new workload: the recorded ones return a status code only, and perf-v4 compares responses), validates
it at the base, and judges it under perf-v4. The record, the readiness, the notes and the spend go to
`<out>/<name>.json`; the new workspace is kept under `~/unbidden-lab/reval-runs/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from bench.ecosystem.conduit_eval import ledger

LAB = Path.home() / "unbidden-lab"
MANDATE = """mandate:
  workspace: {name}
  priorities: [performance of reads as data grows]
  business_constraints:
    maximum_monthly_spend_usd: 2.0
  autonomy:
    observe: allow
    run_experiments: allow
    provision_dependencies: allow
    delegate_synthetic: allow
    open_pull_requests: deny
    merge_pull_requests: deny
    deploy: deny
    rollback: deny
    use_new_capabilities: allow
    act_on_connections: deny
  egress:
    package_registries: [{registries}]
    remote_models:
      destinations: [api.meta.ai]
      max_payload_bytes: 60000
  models:
    profile: frontier
    private_code_to_frontier: allow
    local_fallback: deny
    local_inference: deny
"""
def registries(store: Path) -> list[str]:
    """The package registries the original run's mandate allowed (stage 10: fst's frontend needs npm, which a fixed
    Python-only list refused), with the ones every Python image needs."""
    import yaml

    original = yaml.safe_load((store.parent / "mandate.yaml").read_text()) or {}
    allowed = ((original.get("mandate") or {}).get("egress") or {}).get("package_registries") or []
    return list(dict.fromkeys([*map(str, allowed), "pypi.org", "files.pythonhosted.org", "deb.debian.org"]))


CONFIG = (
    "# Overrides of unbidden's defaults.\nrouting:\n  code:\n    provider: meta\n    model: muse-spark-1.3\n"
    "    think_budget: 2048\n"
)


def opportunity(store: Path, opp_id: str) -> dict[str, object]:
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as db:
        row = db.execute("SELECT doc FROM docs WHERE collection = 'opportunities' AND id = ?", (opp_id,)).fetchone()
    if row is None:
        raise SystemExit(f"{opp_id} is not in {store}")
    return json.loads(row[0])


def prepare(source: Path, name: str, rev: str) -> Path:
    clone = LAB / "reval" / name
    if not (clone / ".git").exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(source), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", "--detach", "--force", rev], check=True)
    subprocess.run(["git", "-C", str(clone), "clean", "-q", "-fdx", "-e", ".unbidden/"], check=True)
    if (clone / ".unbidden").exists():
        target = LAB / "reval-runs" / f"{name}-{int(time.time())}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(clone / ".unbidden"), str(target))
    exclude = clone / ".git" / "info" / "exclude"
    if ".unbidden/" not in (exclude.read_text() if exclude.exists() else ""):
        with exclude.open("a") as f:
            f.write(".unbidden/\n")
    return clone


async def measure(clone: Path, doc: dict[str, object], rev: str) -> dict[str, object]:
    from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
    from unbidden.lab.perf import PerfLab
    from unbidden.runtime import Runtime
    from unbidden.workspace import Workspace

    runtime = Runtime.open(Workspace.find(clone))
    stack, images = runtime.stack_and_images(rev)
    keep = ("table", "column", "endpoints", "code", "chain", "check", "cost_path", "rows")
    details = {k: v for k, v in dict(doc["details"]).items() if k in keep}  # type: ignore[arg-type]
    opp = Opportunity.model_validate({**doc, "details": {**details, "rev": rev}, "status": OpportunityStatus.OPEN.value,
                                      "evidence_level": 1, "evidence": doc.get("evidence") or []})  # fmt: skip
    runtime.store.put("opportunities", opp)
    lab = PerfLab(clone, runtime.brain, runtime.store, stack, images, progress=lambda m: print(m, flush=True))
    result = await lab.run(opp)
    saved = runtime.store.get("opportunities", opp.id, Opportunity) or opp
    return {
        "verdict": result.verdict.model_dump(mode="json") if result.verdict else None,
        "experiment": result.experiment.model_dump(mode="json") if result.experiment else None,
        "blocked": result.blocked,
        "notes": result.notes,
        "readiness": saved.details.get("readiness"),
        "level_after": int(saved.evidence_level),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--opp", required=True)
    parser.add_argument("--rev", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--envelope", required=True)
    args = parser.parse_args()
    os.environ["UNBIDDEN_ENVELOPE"], os.environ["UNBIDDEN_RUN"] = args.envelope, f"reval-{args.name}"
    product = Path(__file__).resolve().parent.parent
    doc = opportunity(Path(args.store).expanduser(), args.opp)
    clone = prepare(Path(args.source).expanduser(), args.name, args.rev)
    rev = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.strip()  # fmt: skip
    subprocess.run(["uv", "run", "--project", str(product), "unbidden", "init"], cwd=clone, check=True,
                   capture_output=True)  # fmt: skip
    (clone / ".unbidden" / "mandate.yaml").write_text(
        MANDATE.format(name=args.name, registries=", ".join(registries(Path(args.store).expanduser())))
    )
    (clone / ".unbidden" / "config.yaml").write_text(CONFIG)
    product_rev = subprocess.run(["git", "-C", str(product), "rev-parse", "HEAD"], capture_output=True, text=True,
                                 check=True).stdout.strip()  # fmt: skip
    record: dict[str, object] = {"name": args.name, "opportunity": args.opp, "title": doc.get("title"),
                                 "original_level": doc.get("evidence_level"), "base": rev, "product": product_rev,
                                 "usd_before": ledger(product)}  # fmt: skip
    started = time.monotonic()
    record |= asyncio.run(measure(clone, doc, rev))
    record |= {"usd_after": ledger(product), "wall_s": round(time.monotonic() - started, 1)}
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.json").write_text(json.dumps(record, indent=1, default=str))
    target = LAB / "reval-runs" / f"{args.name}-{int(time.time())}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(clone / ".unbidden"), str(target))
    verdict = record.get("verdict")
    outcome = verdict.get("outcome") if isinstance(verdict, dict) else None
    spent = round(ledger(product) - float(str(record["usd_before"])), 4)
    print(json.dumps({"name": args.name, "outcome": outcome, "blocked": record.get("blocked"), "usd": spent}))


if __name__ == "__main__":
    main()
