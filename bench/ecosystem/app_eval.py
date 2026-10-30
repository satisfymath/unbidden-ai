"""Stage 9's frozen evaluation on applications never used in development (docs/bench/stage9-evaluation.md).

    uv run python -m bench.ecosystem.app_eval <frozen worktree> --app spoolman|prefect --run B-1|A-1 --out DIR
        --envelope eval

Each run starts from the same restored state: the repository at the pinned release (only the lab's excluded files
kept), the synthetic data re-seeded, a new `.unbidden`. B is proactive (no goal); A has one general goal, the same
text for every application, naming no table, file, index or defect. Two cycles; the one declared answer a person
gives (adding a package registry Unbidden names, once); two more cycles; the workspace moved out whole. The ledger
is read before and after. The harness prepares and records; it never tells Unbidden anything about the application.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from bench.ecosystem.conduit_eval import ledger

LAB = Path.home() / "unbidden-lab"
ENV: dict[str, str] = dict(os.environ)
GOAL = """  goals:
    - id: data-correct-and-fast
      statement: >-
        Readers must see correct and timely data: every number the API reports about stored records must agree with
        what is stored, and the main listings must stay fast as the data grows.
      bounds:
        environment: staging
        max_actions: 0
"""
MANDATE = """mandate:
  workspace: {app}
  priorities: [correctness, performance of reads as data grows]
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
    package_registries: [pypi.org, files.pythonhosted.org]
    remote_models:
      destinations: [api.meta.ai]
      max_payload_bytes: 60000
  models:
    profile: frontier
    private_code_to_frontier: allow
    local_fallback: deny
    local_inference: deny
  connections:
    - id: {app}-db
      kind: postgres
      location: 127.0.0.1:{db_port}/{database}
      environment: staging
      username: {app}_reader
      credential_ref: {secret}
      permissions: [read]
      content_may_leave: true
    - id: {app}-api
      kind: http_api
      location: http://127.0.0.1:{port}
      docs: http://127.0.0.1:{port}{docs}
      environment: staging
      permissions: [read]
      content_may_leave: true
{goals}"""
CONFIG = (
    "# Overrides of unbidden's defaults.\nrouting:\n  code:\n    provider: meta\n    model: muse-spark-1.3\n"
    "    think_budget: 2048\n"
)
APPS: dict[str, dict[str, str]] = {
    "spoolman": {"database": "spoolman", "docs": "/api/v1/openapi.json", "secret": "SPOOLMAN_READER_PW"},
    "prefect": {"database": "prefect", "docs": "/api/openapi.json", "secret": "PREFECT_READER_PW"},
}


def lab_of(app: str) -> ModuleType:
    return importlib.import_module(f"bench.ecosystem.{app}_lab")


def restore(lab: ModuleType) -> dict[str, Any]:
    repo = lab.repo_dir(LAB)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", "--force", lab.COMMIT], check=True)
    subprocess.run(["git", "-C", str(repo), "clean", "-q", "-fd"], check=True)  # excluded lab files stay
    heads = ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads"]
    for branch in subprocess.run(heads, capture_output=True, text=True, check=True).stdout.split():
        subprocess.run(["git", "-C", str(repo), "branch", "-q", "-D", branch], check=False)
    return {"commit": lab.COMMIT, "data": lab.seed(LAB)}


def workspace(worktree: Path, app: str, lab: ModuleType, goal: bool) -> None:
    repo = lab.repo_dir(LAB)
    if (repo / ".unbidden").exists():
        raise SystemExit(f"{repo / '.unbidden'} exists: archive it first")
    subprocess.run(["uv", "run", "--project", str(worktree), "unbidden", "init"], cwd=repo, check=True,
                   capture_output=True)  # fmt: skip
    spec = APPS[app]
    mandate = MANDATE.format(app=app, db_port=lab.DB_PORT, port=lab.PORT, goals=GOAL if goal else "", **spec)
    (repo / ".unbidden" / "mandate.yaml").write_text(mandate)
    (repo / ".unbidden" / "config.yaml").write_text(CONFIG)
    held = dict(ln.split("=", 1) for ln in (LAB / lab.SECRETS).read_text().splitlines() if "=" in ln)
    env = repo / ".unbidden" / ".env"
    env.write_text(f"{spec['secret']}={held[spec['secret']]}\n")
    env.chmod(0o600)


def run(worktree: Path, app: str, name: str, out: Path) -> dict[str, Any]:
    lab = lab_of(app)
    goal = name.startswith("A")
    record: dict[str, Any] = {"app": app, "run": name, "mode": "goal" if goal else "proactive",
                              "restored": restore(lab), "usd_before": ledger(worktree)}  # fmt: skip
    repo = lab.repo_dir(LAB)
    workspace(worktree, app, lab, goal)
    logs, started = [], time.monotonic()
    unbidden = ["uv", "run", "--project", str(worktree), "unbidden"]

    def cycles(numbers: tuple[int, ...]) -> None:
        for cycle in numbers:
            try:
                ran = subprocess.run([*unbidden, "watch", "--once"], cwd=repo, capture_output=True, text=True,
                                     timeout=5400, env={**ENV, "UNBIDDEN_RUN": f"{app}-{name}"})  # fmt: skip
            except subprocess.TimeoutExpired as exc:  # recorded, and the run goes on to archive its workspace
                logs.append(f"== cycle {cycle} (did not finish within {exc.timeout:.0f} s)")
                continue
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
    cycles((3, 4))  # the second pair runs either way: it shows what a later cycle repeats
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
    target = LAB / f"{app}-runs" / f"{out.name}-{name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(repo / ".unbidden"), str(target))
    record["workspace"] = str(target)
    (where / "record.json").write_text(json.dumps(record, indent=1))
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree")
    parser.add_argument("--app", choices=sorted(APPS), required=True)
    parser.add_argument("--runs", default="B-1,A-1")
    parser.add_argument("--out", required=True)
    parser.add_argument("--envelope", required=True)
    args = parser.parse_args()
    ENV["UNBIDDEN_ENVELOPE"] = args.envelope
    worktree, out = Path(args.worktree).expanduser(), Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()  # fmt: skip
    (out / "frozen.json").write_text(json.dumps({"product": commit, "app": args.app,
                                                 "app_commit": lab_of(args.app).COMMIT}, indent=1))  # fmt: skip
    for name in args.runs.split(","):
        rec = run(worktree, args.app, name, out)
        print(json.dumps({k: rec[k] for k in ("app", "run", "usd_before", "usd_after", "wall_s")}), flush=True)


if __name__ == "__main__":
    main()
