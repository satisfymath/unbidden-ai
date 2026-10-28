"""Give Unbidden the restock board project (stage 5), as a person would, under a model policy and a perception.

    uv run python -m bench.ecosystem.board_workspace <worktree> [--policy local|spark|wonder]
        [--perception dom|vision|vision_sam] [--max-changes N]

The goal says what the board is for, never what is wrong with it. `--policy` changes only which models may serve:
`local` (profile local), `spark` or `wonder` (profile frontier, the `code` route on that Meta model, the local model
as recorded fallback; this lab's repository and data are synthetic, so a person lets its code and screenshots go
to the frontier model). `--perception` changes only what the page check is shown. The grants read the data only:
the board can be fixed, not the stock or the history.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from bench.ecosystem.board_lab import PORT, PROJECT, repo_dir

MODELS = {"spark": "muse-spark-1.3", "wonder": "muse-wonder-1.0"}
# The person's goal carries what the contract asks a person to see (a red SHORT alert, legible, on the bin's own row,
# not covered); never what may be wrong. Development runs style-1 and style-2 showed why: with "flagged", then "a red
# alert", the agent restyled it pale pink with red text, its own check accepted it, the checker (a red badge) did not.
# Stage 6, without history: "a red SHORT badge" still gave pale pink with red text (Spark and Wonder, colours named
# or not): the statement now says what the contract asks, a red background.
STATEMENT = (
    "Every bin with a shortfall must be flagged on the restock board with a SHORT badge on a red background (white "
    "text on red, an alert) that a person can see and read on that bin's own row, and no other bin may carry one: "
    "a bin is short when its picks over the last 7 days exceed what it can supply (what it holds, less what is "
    "reserved, plus what is incoming), and people "
    "restock from what the board shows them."
)
MANDATE = """mandate:
  workspace: boardapp
  priorities: [correctness]
  business_constraints:
    maximum_monthly_spend_usd: {spend}
  autonomy:
    observe: allow
    run_experiments: allow
    provision_dependencies: deny
    delegate_synthetic: {delegate}
    open_pull_requests: deny
    merge_pull_requests: deny
    deploy: allow
    rollback: allow
    use_new_capabilities: allow
    act_on_connections: deny
  egress:
    package_registries: []
    remote_models:
      destinations: [{destinations}]
      max_payload_bytes: 120000
  models:
    profile: {profile}
    private_code_to_frontier: {private_code}
    screenshots_to_frontier: {screenshots}
    local_fallback: allow
  operations:
    deploy_steps:
      - [docker, compose, -p, {project}, up, -d, --build]
    check_steps:
      - [python, -m, unittest]
    check_image: python:3.12-slim
    max_deploys_per_hour: 6
  connections:
    - id: board-db
      kind: postgres
      location: 127.0.0.1:55432/boardpicks
      environment: staging
      username: board_reader
      credential_ref: BOARD_READER_PW
      permissions: [read]
      content_may_leave: true
    - id: board-api
      kind: http_api
      location: http://127.0.0.1:18086
      docs: http://127.0.0.1:18086/openapi.json
      environment: staging
      credential_ref: BOARD_DEPOT_KEY
      permissions: [read]
      content_may_leave: true
  goals:
    - id: board-flags
      statement: >-
        {statement}
      bounds:
        environment: staging
        max_changes: {max_changes}
"""


def write(repo: Path, policy: str, perception: str, max_changes: int) -> None:
    remote = policy in MODELS
    (repo / ".unbidden" / "mandate.yaml").write_text(
        MANDATE.format(
            spend=5 if remote else 0,
            delegate="allow" if remote else "deny",
            destinations="api.meta.ai" if remote else "",
            profile="frontier" if remote else "local",
            private_code="allow" if remote else "deny",
            screenshots="allow" if remote and perception != "dom" else "deny",
            project=PROJECT,
            statement=STATEMENT,
            max_changes=max_changes,
        )
    )
    config = f"# Overrides of unbidden's defaults.\nui:\n  perception: {perception}\n"
    if remote:
        config += f"routing:\n  code:\n    provider: meta\n    model: {MODELS[policy]}\n    think_budget: 2048\n"
    (repo / ".unbidden" / "config.yaml").write_text(config)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree")
    parser.add_argument("--policy", choices=["local", "spark", "wonder"], default="spark")
    parser.add_argument("--perception", choices=["dom", "vision", "vision_sam"], default="dom")
    parser.add_argument("--max-changes", type=int, default=2)
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    args = parser.parse_args()
    lab = Path(args.dir)
    repo = repo_dir(lab)
    if (repo / ".unbidden").exists():
        shutil.rmtree(repo / ".unbidden")
    subprocess.run(["uv", "run", "--project", args.worktree, "unbidden", "init"], cwd=repo, check=True,
                   capture_output=True)  # fmt: skip
    write(repo, args.policy, args.perception, args.max_changes)
    held = dict(line.split("=", 1) for line in (lab / "board-secrets.env").read_text().splitlines() if "=" in line)
    env = repo / ".unbidden" / ".env"
    env.write_text("".join(f"{k}={held[k]}\n" for k in ("BOARD_READER_PW", "BOARD_DEPOT_KEY")))
    env.chmod(0o600)
    print(repo, f"(staging on {PORT})")


if __name__ == "__main__":
    main()
