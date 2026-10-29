"""Run stage 8's independent proactive run on LNbits (docs/bench/stage8-independent.md).

    uv run python -m bench.ecosystem.lnbits_eval <frozen worktree> --out DIR

Same shape as the Conduit runs (`conduit_eval.py`): the repository back at the pinned release, the synthetic data
re-seeded, a fresh read key, a new `.unbidden` with a proactive mandate and no goal; two cycles; the one declared
answer a person gives (a package registry Unbidden names, added once), then two more cycles; the workspace moved out.
The ledger is read before and after. The harness only prepares and records; it never tells Unbidden anything about
the application.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from bench.ecosystem import lnbits_lab
from bench.ecosystem.conduit_eval import ledger

LAB = Path.home() / "unbidden-lab"
ENV: dict[str, str] = dict(os.environ)  # with the run's envelope and tag (stage 9: spend is split into envelopes)
MANDATE = """mandate:
  workspace: lnbits
  priorities: [correctness, performance of reads as data grows]
  business_constraints:
    maximum_monthly_spend_usd: 1.5
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
    - id: lnbits-db
      kind: postgres
      location: 127.0.0.1:{db_port}/lnbits
      environment: staging
      username: lnbits_reader
      credential_ref: LNBITS_READER_PW
      permissions: [read]
      content_may_leave: true
    - id: lnbits-api
      kind: http_api
      location: http://127.0.0.1:{port}
      docs: http://127.0.0.1:{port}/openapi.json
      environment: staging
      credential_ref: LNBITS_TOKEN
      permissions: [read]
      content_may_leave: true
"""
CONFIG = (
    "# Overrides of unbidden's defaults.\nrouting:\n  code:\n    provider: meta\n    model: muse-spark-1.3\n"
    "    think_budget: 2048\n"
)


def restore() -> dict[str, Any]:
    repo = lnbits_lab.repo_dir(LAB)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", "--force", lnbits_lab.COMMIT], check=True)
    subprocess.run(["git", "-C", str(repo), "clean", "-q", "-fd"], check=True)  # excluded lab files stay
    heads = ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads"]
    for branch in subprocess.run(heads, capture_output=True, text=True, check=True).stdout.split():
        subprocess.run(["git", "-C", str(repo), "branch", "-q", "-D", branch], check=False)
    counts = lnbits_lab.seed(LAB)
    lnbits_lab.token(LAB)
    return {"commit": lnbits_lab.COMMIT, "data": counts}


def workspace(worktree: Path) -> None:
    repo = lnbits_lab.repo_dir(LAB)
    if (repo / ".unbidden").exists():
        raise SystemExit(f"{repo / '.unbidden'} exists: archive it first")
    subprocess.run(["uv", "run", "--project", str(worktree), "unbidden", "init"], cwd=repo, check=True,
                   capture_output=True)  # fmt: skip
    (repo / ".unbidden" / "mandate.yaml").write_text(MANDATE.format(db_port=lnbits_lab.DB_PORT, port=lnbits_lab.PORT))
    (repo / ".unbidden" / "config.yaml").write_text(CONFIG)
    held = dict(ln.split("=", 1) for ln in (LAB / lnbits_lab.SECRETS).read_text().splitlines() if "=" in ln)
    env = repo / ".unbidden" / ".env"
    env.write_text(f"LNBITS_READER_PW={held['LNBITS_READER_PW']}\nLNBITS_TOKEN={held['LNBITS_TOKEN']}\n")
    env.chmod(0o600)


def run(worktree: Path, name: str, out: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"run": name, "mode": "proactive", "restored": restore(), "usd_before": ledger(worktree)}
    repo = lnbits_lab.repo_dir(LAB)
    workspace(worktree)
    logs, started = [], time.monotonic()
    unbidden = ["uv", "run", "--project", str(worktree), "unbidden"]

    def cycles(numbers: tuple[int, ...]) -> None:
        for cycle in numbers:
            ran = subprocess.run([*unbidden, "watch", "--once"], cwd=repo, capture_output=True, text=True,
                                 timeout=5400, env={**ENV, "UNBIDDEN_RUN": name})  # fmt: skip
            logs.append(f"== cycle {cycle} (exit {ran.returncode})\n{ran.stdout}{ran.stderr}")

    cycles((1, 2))
    record["interventions"] = []
    asked = json.loads(subprocess.run([*unbidden, "activity", "--json"], cwd=repo, capture_output=True, text=True,
                                      check=False).stdout or "{}")  # fmt: skip
    for request in asked.get("needs_a_person", []):
        wanted = re.search(r"add ([\w.\-, ]+) to egress\.package_registries", str(request.get("what", "")))
        if wanted:
            hosts = [h.strip() for h in wanted.group(1).split(",") if h.strip()]
            mandate = repo / ".unbidden" / "mandate.yaml"
            text = mandate.read_text()
            listed = re.search(r"package_registries: \[([^\]]*)\]", text)
            if listed:
                have = [h.strip() for h in listed.group(1).split(",") if h.strip()]
                merged = ", ".join(dict.fromkeys([*have, *hosts]))
                mandate.write_text(text.replace(listed.group(0), f"package_registries: [{merged}]"))
                record["interventions"].append({"answered": request, "granted": hosts, "at": time.time()})
    if record["interventions"]:
        cycles((3, 4))
    record["wall_s"] = round(time.monotonic() - started, 1)
    activity = subprocess.run([*unbidden, "activity", "--json"], cwd=repo, capture_output=True, text=True,
                              check=False).stdout  # fmt: skip
    record["repo_after"] = subprocess.run(["git", "-C", str(repo), "status", "--short"], capture_output=True,
                                          text=True, check=False).stdout.strip()  # fmt: skip
    heads = ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads"]
    record["branches_after"] = subprocess.run(heads, capture_output=True, text=True, check=False).stdout.split()
    record["usd_after"] = ledger(worktree)
    where = out / name
    where.mkdir(parents=True, exist_ok=True)
    (where / "cycles.log").write_text("\n\n".join(logs))
    (where / "activity.json").write_text(activity)
    target = LAB / "lnbits-runs" / f"{out.name}-{name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(repo / ".unbidden"), str(target))
    record["workspace"] = str(target)
    (where / "record.json").write_text(json.dumps(record, indent=1))
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree")
    parser.add_argument("--out", required=True)
    parser.add_argument("--run", default="I-1")
    parser.add_argument("--envelope", help="the spend envelope every model call of this run comes from")
    args = parser.parse_args()
    worktree, out = Path(args.worktree).expanduser(), Path(args.out).expanduser()
    if args.envelope:
        ENV["UNBIDDEN_ENVELOPE"] = args.envelope
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()  # fmt: skip
    (out / "frozen.json").write_text(json.dumps({"product": commit, "app": lnbits_lab.COMMIT}, indent=1))
    rec = run(worktree, args.run, out)
    print(json.dumps({k: rec[k] for k in ("run", "usd_before", "usd_after", "wall_s")}), flush=True)


if __name__ == "__main__":
    main()
