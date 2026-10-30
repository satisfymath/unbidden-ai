"""Give Unbidden the Conduit project (stage 7), as a person would: question B (proactive, no goal) or A (a goal).

    uv run python -m bench.ecosystem.conduit_workspace <worktree> --mode proactive|goal

Both modes: read-only grants to the database (role `conduit_reader`) and the API (a synthetic user's token), the
repository and its running staging, experiments in Unbidden's sandbox (dependencies from PyPI), no pull request, no
merge, no deploy, no write to data or through the API. Spark through the router (profile local-first: content goes
remote only where the route policy lets it), the local model as recorded fallback. The workspace's monthly cap is
the run's share of the stage budget. Proactive mode gets priorities and constraints and no goal; goal mode gets the
protocol's goal (docs/bench/stage7-transfer.md) and nothing about any finding.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from bench.ecosystem.conduit_lab import DB_PORT, PORT, repo_dir

GOAL = """  goals:
    - id: counts-correct-and-fast
      statement: >-
        Readers must see correct and timely counts: for every article, the number of favorites and comments the API
        reports must match what is stored, and reading an article's comments must stay fast as the site grows.
      bounds:
        environment: staging
"""
MANDATE = """mandate:
  workspace: conduit
  priorities: [correctness, performance of reads as data grows]
  business_constraints:
    maximum_monthly_spend_usd: {cap}
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
    package_registries: [pypi.org, files.pythonhosted.org]
    remote_models:
      destinations: [api.meta.ai]
      max_payload_bytes: 60000
  models:
    # Stage 9 (D-052): Meta's API only; the projects are public and their data synthetic.
    profile: frontier
    private_code_to_frontier: allow
    local_fallback: deny
    local_inference: deny
  connections:
    - id: conduit-db
      kind: postgres
      location: 127.0.0.1:{db_port}/postgres
      environment: staging
      username: conduit_reader
      credential_ref: CONDUIT_READER_PW
      permissions: [read]
      content_may_leave: true
    - id: conduit-api
      kind: http_api
      location: http://127.0.0.1:{port}
      docs: http://127.0.0.1:{port}/openapi.json
      environment: staging
      credential_ref: CONDUIT_TOKEN
      permissions: [read]
      content_may_leave: true
{goals}"""
CAPS = {"proactive": 1.2, "goal": 1.2}  # stage 9: Meta-only runs cost more; the goal run hit US$0.40 in R9-A-3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree")
    parser.add_argument("--mode", choices=["proactive", "goal"], required=True)
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    args = parser.parse_args()
    lab = Path(args.dir)
    repo = repo_dir(lab)
    if (repo / ".unbidden").exists():
        raise SystemExit(f"{repo / '.unbidden'} exists: archive it first (each question starts from a clean workspace)")
    subprocess.run(["uv", "run", "--project", args.worktree, "unbidden", "init"], cwd=repo, check=True,
                   capture_output=True)  # fmt: skip
    (repo / ".unbidden" / "mandate.yaml").write_text(
        MANDATE.format(cap=CAPS[args.mode], db_port=DB_PORT, port=PORT, goals=GOAL if args.mode == "goal" else "")
    )
    (repo / ".unbidden" / "config.yaml").write_text(
        "# Overrides of unbidden's defaults.\nrouting:\n  code:\n    provider: meta\n    model: muse-spark-1.3\n"
        "    think_budget: 2048\n"
    )
    held = dict(line.split("=", 1) for line in (lab / "conduit-secrets.env").read_text().splitlines() if "=" in line)
    env = repo / ".unbidden" / ".env"
    env.write_text(f"CONDUIT_READER_PW={held['CONDUIT_READER_PW']}\nCONDUIT_TOKEN={held['CONDUIT_TOKEN']}\n")
    env.chmod(0o600)
    print(repo)


def archive(lab: Path, name: str) -> Path:
    """Move a finished workspace out of the repository, whole (state, artifacts), so the next starts clean."""
    repo = repo_dir(lab)
    target = lab / "conduit-runs" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(repo / ".unbidden"), str(target))
    return target


if __name__ == "__main__":
    main()
