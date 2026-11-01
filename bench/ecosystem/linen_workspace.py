"""Give Unbidden the Hotel project (stage 6 evaluation, question A), as a person would, under a model policy.
Written and frozen before the evaluation ran.

    uv run python -m bench.ecosystem.linen_workspace <worktree> [--policy local|spark|wonder] [--grant read|write]
        [--writes allow|require_approval|deny] [--fresh]

`--policy` changes only which models may serve: `local` (profile local), `spark` or `wonder` (profile local-first,
the `code` route on that Meta model, the local model as recorded fallback). The code, the mandate's grants and goal
and the lab are the same under every policy.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

MODELS = {"spark": "muse-spark-1.3", "wonder": "muse-wonder-1.0"}
MANDATE = """mandate:
  workspace: hotelapp
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
    deploy: deny
    rollback: deny
    use_new_capabilities: allow
    act_on_connections: {writes}
  egress:
    package_registries: []
    remote_models:
      destinations: [{destinations}]
      max_payload_bytes: 60000
  models:
    profile: {profile}
    local_fallback: allow
  connections:
    - id: hotel-db
      kind: postgres
      location: 127.0.0.1:55432/linen
      environment: staging
      username: linen_reader
      credential_ref: LINEN_READER_PW
      permissions: [read]
      content_may_leave: true
    - id: linen-api
      kind: http_api
      location: http://127.0.0.1:19191
      docs: http://127.0.0.1:19191/openapi.json
      environment: staging
      credential_ref: LINEN_KEY
      permissions: {permissions}
      content_may_leave: true
  goals:
    - id: towels-covered
      statement: >-
        No floor should run out of towels: every floor station whose towel requests over the last 5 days exceed
        what it can hand out (clean bundles on the shelf, less those held for booked rooms, plus those already en
        route) should get a delivery scheduled for the difference.
      bounds:
        environment: staging
        max_actions: 4
        max_amount_per_action: 25
"""


def write_mandate(repo: Path, policy: str, grant: str, writes: str) -> None:
    remote = policy in MODELS
    (repo / ".unbidden" / "mandate.yaml").write_text(
        MANDATE.format(
            spend=5 if remote else 0,
            delegate="allow" if remote else "deny",
            writes=writes,
            destinations="api.meta.ai" if remote else "",
            profile="local-first" if remote else "local",
            permissions='[read, "write:deliveries"]' if grant == "write" else "[read]",
        )
    )
    config = "# Overrides of unbidden's defaults.\n"
    if remote:
        config += f"routing:\n  code:\n    provider: meta\n    model: {MODELS[policy]}\n    think_budget: 2048\n"
    (repo / ".unbidden" / "config.yaml").write_text(config)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree")
    parser.add_argument("--policy", choices=["local", "spark", "wonder"], default="local")
    parser.add_argument("--grant", choices=["read", "write"], default="write")
    parser.add_argument("--writes", choices=["allow", "require_approval", "deny"], default="allow")
    parser.add_argument("--use-capabilities", default="allow")
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    lab = Path(args.dir)
    repo = lab / "hotelapp"
    if args.fresh and (repo / ".unbidden").exists():
        shutil.rmtree(repo / ".unbidden")
    if not (repo / ".unbidden").exists():
        subprocess.run(
            ["uv", "run", "--project", args.worktree, "unbidden", "init"], cwd=repo, check=True, capture_output=True
        )
    write_mandate(repo, args.policy, args.grant, args.writes)
    held = dict(line.split("=", 1) for line in (lab / "linen-secrets.env").read_text().splitlines() if "=" in line)
    env = repo / ".unbidden" / ".env"
    lines = [f"{k}={held[k]}" for k in ("LINEN_READER_PW", "LINEN_KEY")]
    # The remote model's key stays where the person keeps it (~/.unbidden/.env); the broker reads it there.
    env.write_text("\n".join(lines) + "\n")
    env.chmod(0o600)
    print(repo)


if __name__ == "__main__":
    main()
