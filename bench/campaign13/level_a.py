"""Campaign 12, Level A: the installed product on every repository of the corpus, no model spend.

    uv run python -m bench.campaign13.level_a bench/campaign13/corpus.yaml --phase pilot \
        --out docs/bench/campaign13/pilot [--only a,b] [--port 8800]

Per repository, as a person would from a terminal: a fresh clone at the pin under ~/unbidden-lab/c13/repos/<name>;
`unbidden setup --non-interactive --models api --mode supervised --budget 0 --dashboard later --model-key-stdin --yes`
(the key read from the machine's credentials file by the harness and passed on stdin: never in argv); `doctor`;
`scan` (isolated preparation, the CI's checks in the sandbox, the analyzers: no model); `inbox`; `start` → `status` →
`stop` (the daemon's first cycle has a zero cap: its model calls are refused and recorded as such); `ui` → the API →
`ui --stop`; the ledger before and after (must be equal). Every step is bounded and recorded; a repository where
something fails is a row like any other. The workspace is archived under ~/unbidden-lab/c13/archive/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from bench.campaign13.common import (
    LAB,
    LEDGER_HOME,
    Record,
    candidate_of,
    env,
    envelope_for,
    ledger,
    run,
    run_spend,
    scrub,
    unbidden,
)

CHECKS_TIMEOUT_S = 3600
SHORT_S = 600
REPOS = LAB / "repos"
ARCHIVE = LAB / "archive"


def key_from_machine(name: str = "MODEL_API_KEY") -> str:
    """The machine's key, read by the harness only to hand it to `setup` on stdin (the product's own path)."""
    for line in (LEDGER_HOME / ".env").read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def clone(repo: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """A fresh clone at the pin (a previous clone is removed: every run starts from the same state)."""
    target = REPOS / f"c13-{repo['name']}"  # the directory names the workspace: campaign rows apart in the ledger
    started = time.monotonic()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "remote", "add", "origin", repo["url"]], check=True)
    fetch = subprocess.run(
        ["git", "-C", str(target), "fetch", "-q", "--depth", "1", "origin", repo["commit"]],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if fetch.returncode != 0:  # a commit not reachable shallowly: the full history
        fetch = subprocess.run(
            ["git", "-C", str(target), "fetch", "-q", "origin"],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "--detach", repo["commit"]], check=True)
    head = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    return target, {
        "path": str(target),
        "head": head,
        "seconds": round(time.monotonic() - started, 1),
        "fetch_code": fetch.returncode,
    }


def ui_read(repo_dir: Path, port: int, e: dict[str, str], rec: Record) -> dict[str, Any]:
    """Open the dashboard apart, read the session, the summary and the opportunities through its API, close it."""
    out: dict[str, Any] = {}
    step = rec.add(run("ui", [unbidden(), "ui", "--json", "--port", str(port)], cwd=repo_dir, env_=e, timeout_s=120))
    info = step.json() or {}
    out["opened"] = step.code == 0 and bool(info.get("url"))
    if out["opened"]:
        try:
            token = json.loads((repo_dir / ".unbidden" / "ui.json").read_text())["token"]
            base = f"http://127.0.0.1:{info['port']}"
            headers = {"Authorization": f"Bearer {token}"}
            session = httpx.get(f"{base}/api/session", headers=headers, timeout=10).json()
            sid = session["sources"][0]["id"]
            summary = httpx.get(f"{base}/api/ws/{sid}/summary", headers=headers, timeout=20).json()
            opps = httpx.get(f"{base}/api/ws/{sid}/opportunities", headers=headers, timeout=20).json()
            events = httpx.get(f"{base}/api/ws/{sid}/events?limit=500", headers=headers, timeout=20).json()
            index = httpx.get(f"{base}/", headers=headers, timeout=10).text
            out.update(
                session_ok=bool(session.get("ok")),
                source_mode=summary["workspace"]["mode"],
                freshness=summary.get("freshness"),
                counts=summary.get("counts"),
                agent=summary.get("connection", {}).get("agent"),
                route=summary.get("connection", {}).get("route", {}).get("profile"),
                key_present=summary.get("connection", {}).get("route", {}).get("remote", {}).get("key_present"),
                opportunities_total=opps.get("total"),
                events=len(events.get("items", [])),
                built_index=('<div id="root">' in index) and ("make web-build" not in index),
                secret_in_summary=key_from_machine() in json.dumps(summary) if key_from_machine() else False,
            )
        except Exception as exc:  # the failure is the record
            out["api_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    stop = rec.add(run("ui-stop", [unbidden(), "ui", "--stop", "--json"], cwd=repo_dir, env_=e, timeout_s=60))
    out["stopped"] = stop.code == 0
    return out


def level_a(
    repo: dict[str, Any], phase: str, out_dir: Path, port: int, candidate: str, wheel: str, *, debian: bool = False,
    ci_env: bool = False,
) -> dict[str, Any]:
    name = repo["name"]
    e = env(envelope_for(phase), f"c13-{phase}-A-{name}")
    rec = Record(repo=name, phase=phase, run="A", candidate=candidate, wheel_sha256=wheel)
    rec.facts["repo"] = {k: repo.get(k) for k in ("url", "commit", "family", "class", "build", "license")}
    rec.facts["ledger_before"] = ledger(e["UNBIDDEN_ENVELOPE"])
    repo_dir, cloned = clone(repo)
    rec.facts["clone"] = cloned
    rec.human.append({"step": "clone at the pin", "minutes": round(cloned["seconds"] / 60, 1), "why": "harness"})
    key = key_from_machine()
    setup = rec.add(
        run(
            "setup",
            [
                unbidden(),
                "setup",
                "--non-interactive",
                "--models",
                "api",
                "--mode",
                "supervised",
                "--budget",
                "0",
                "--dashboard",
                "later",
                "--model-key-stdin",
                "--yes",
                "--json",
            ],
            cwd=repo_dir,
            env_=e,
            timeout_s=SHORT_S,
            stdin=key + "\n",
        )
    )
    rec.facts["setup"] = {"ok": setup.code == 0, "applied": (setup.json() or {}).get("applied")}
    if ci_env:
        # Campaign 13, 0.16.0: the team's own CI job prepares the environment (sandbox/ci_env.py), as in the final pass.
        path = repo_dir / ".unbidden" / "mandate.yaml"
        raw = yaml.safe_load(path.read_text())
        raw["mandate"]["egress"]["ci_environment"] = "allow"
        path.write_text(yaml.safe_dump(raw, sort_keys=False))
        rec.facts["mandate_ci_environment"] = "allow"
    if debian:
        # Phase 7 variant, documented: the default mandate lists no Debian archive (FINDINGS 2026-11-03), so the
        # tool cluster of Level A blocks by design; this run allows it, as Level B's mandate did.
        path = repo_dir / ".unbidden" / "mandate.yaml"
        raw = yaml.safe_load(path.read_text())
        raw["mandate"]["egress"]["package_registries"] = ["pypi.org", "files.pythonhosted.org", "deb.debian.org",
                                                           "registry.npmjs.org"]  # fmt: skip
        path.write_text(yaml.safe_dump(raw, sort_keys=False))
        rec.facts["mandate_variant"] = "debian allowed"
    doctor = rec.add(run("doctor", [unbidden(), "doctor", "--json"], cwd=repo_dir, env_=e, timeout_s=SHORT_S))
    d = doctor.json() or {}
    rec.facts["doctor"] = {
        "ok": d.get("ok"),
        "failed_required": d.get("failed_required"),
        "requirements": d.get("requirements"),
        "scope": {c["check"]: (c["ok"], c["detail"]) for c in d.get("checks", []) if c["check"].startswith("scope")},
    }
    scan = rec.add(run("scan", [unbidden(), "scan", "--json"], cwd=repo_dir, env_=e, timeout_s=CHECKS_TIMEOUT_S))
    s = scan.json() or {}
    rec.facts["scan"] = {
        "ok": scan.code == 0,
        "timed_out": scan.timed_out,
        "seconds": scan.seconds,
        "languages": s.get("languages"),
        "reports": s.get("reports"),
        "opened": s.get("opened"),
        "problems": s.get("problems"),
        "blind_spots": s.get("blind_spots"),
    }
    inbox = rec.add(run("inbox", [unbidden(), "inbox", "--json"], cwd=repo_dir, env_=e, timeout_s=SHORT_S))
    opps = inbox.json() or []
    by_source: dict[str, int] = {}
    for o in opps if isinstance(opps, list) else []:
        by_source[o.get("source", "?")] = by_source.get(o.get("source", "?"), 0) + 1
    rec.facts["inbox"] = {"total": len(opps) if isinstance(opps, list) else None, "by_source": by_source}
    status0 = rec.add(run("status0", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=SHORT_S))
    # The project's own checks run in the agent's first cycle (observe.head -> `baseline_checks`), in the sandbox,
    # without a model: start the agent and wait for that record (bounded), then read the lifecycle.
    start = rec.add(
        run("start", [unbidden(), "start", "--interval", "3600", "--json"], cwd=repo_dir, env_=e, timeout_s=SHORT_S)
    )
    waited = _wait_for_checks(repo_dir, CHECKS_TIMEOUT_S)
    rec.facts["checks"] = _checks_record(repo_dir) | {"waited_s": waited}
    rec.facts["checks"]["image_age"] = _image_age(rec.facts["checks"].get("image_notes"))
    status = rec.add(run("status", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=SHORT_S))
    st = status.json() or {}
    second = rec.add(
        run(
            "start-again",
            [unbidden(), "start", "--interval", "3600", "--json"],
            cwd=repo_dir,
            env_=e,
            timeout_s=SHORT_S,
        )
    )
    stop = rec.add(run("stop", [unbidden(), "stop", "--json"], cwd=repo_dir, env_=e, timeout_s=300))
    after = rec.add(run("status-after", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=SHORT_S))
    rec.facts["lifecycle"] = {
        "started": (start.json() or {}).get("started"),
        "running_after_checks": (st.get("agent") or {}).get("running"),
        "second_start_refused": not (second.json() or {}).get("started") and bool((second.json() or {}).get("already")),
        "stopped": (stop.json() or {}).get("stopped"),
        "jobs_left_running": (stop.json() or {}).get("jobs_left_running"),
        "stale_after": ((after.json() or {}).get("agent") or {}).get("stale"),
        "kill_file": (repo_dir / ".unbidden" / "KILL").exists(),
        "status0_ok": status0.code == 0,
    }
    rec.facts["ui"] = ui_read(repo_dir, port, e, rec)
    rec.facts["ledger_after"] = ledger(e["UNBIDDEN_ENVELOPE"])
    rec.facts["run_spend"] = run_spend(e["UNBIDDEN_RUN"], e["UNBIDDEN_ENVELOPE"])
    rec.facts["spent_usd"] = rec.facts["run_spend"]["usd"]
    rec.facts["refused_by_cap"] = _count_log(repo_dir, "cap") if (repo_dir / ".unbidden" / "logs").exists() else None
    rec.facts["events"] = _events(repo_dir)
    rec.facts["archive"] = archive(repo_dir, f"{name}-A-{phase}")
    path = rec.write(out_dir / name / "A.json")
    return {
        "name": name,
        "class": repo.get("class"),
        "family": repo.get("family"),
        "record": str(path),
        "setup": rec.facts["setup"]["ok"],
        "doctor_ok": d.get("ok"),
        "scan_ok": rec.facts["scan"]["ok"],
        "checks": rec.facts["checks"].get("status"),
        "collected": rec.facts["checks"].get("collected"),
        "opps": rec.facts["inbox"]["total"],
        "lifecycle": rec.facts["lifecycle"],
        "ui": rec.facts["ui"].get("opened"),
        "spent_usd": rec.facts["spent_usd"],
        "wall_s": round(sum(s["seconds"] for s in rec.steps), 1),
    }


def _baseline(repo_dir: Path) -> dict[str, Any] | None:
    import sqlite3

    try:
        c = sqlite3.connect(str(repo_dir / ".unbidden" / "state.db"))
        row = c.execute("select value from kv where key = 'baseline_checks'").fetchone()
        c.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        v = json.loads(row[0])
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _wait_for_checks(repo_dir: Path, timeout_s: float) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if _baseline(repo_dir) is not None:
            break
        time.sleep(10)
    return round(time.monotonic() - started, 1)


def _checks_record(repo_dir: Path) -> dict[str, Any]:
    """What `observe.checks` recorded at the base (`baseline_checks`): status, tests collected, failed, why, scope."""
    v = _baseline(repo_dir)
    if v is None:
        return {"status": None, "why": "no baseline_checks record (the first cycle did not reach it in time)"}
    out = {k: v.get(k) for k in ("status", "collected", "why", "scope", "partial", "command", "rev", "could_not_run")}
    failed = v.get("failed")
    out["failed"] = len(failed) if isinstance(failed, list) else failed
    image = v.get("image") if isinstance(v.get("image"), dict) else {}
    out["image_notes"] = image.get("notes")
    stack = v.get("stack") if isinstance(v.get("stack"), dict) else {}
    out["python"] = stack.get("python")
    return out


def _image_age(notes: Any) -> dict[str, Any] | None:
    """Whether the dependency image existed before this run (cached from an earlier stage on this machine) or was
    built now: the wall time of 'environment reproduced' is honest only with this beside it."""
    tag = next(
        (n.split(" ")[1] for n in (notes or []) if isinstance(n, str) and n.startswith("image unbidden-deps")), None
    )
    if not tag:
        return None
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Created}}", tag], capture_output=True, text=True, check=False
    )
    created = out.stdout.strip()
    return {
        "tag": tag,
        "created": created,
        "built_in_this_run": created[:16] >= time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 3600)),
    }


def _count_log(repo_dir: Path, needle: str) -> int:
    log = repo_dir / ".unbidden" / "logs" / "agent.log"
    return log.read_text(errors="replace").lower().count(needle) if log.exists() else 0


def _events(repo_dir: Path) -> dict[str, int]:
    import sqlite3

    try:
        c = sqlite3.connect(str(repo_dir / ".unbidden" / "state.db"))
        rows = dict(c.execute("select type, count(*) from events group by type").fetchall())
        c.close()
        return rows
    except sqlite3.Error:
        return {}


def archive(repo_dir: Path, label: str) -> str | None:
    ws = repo_dir / ".unbidden"
    if not ws.exists():
        return None
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE / f"{label}.tgz"
    with tarfile.open(target, "w:gz") as tar:
        for p in ws.rglob("*"):
            if p.name in (".env", "ui.json") or p.suffix in (".db-wal", ".db-shm"):
                continue  # credentials and tokens never leave the workspace; sqlite side files are transient
            tar.add(p, arcname=str(p.relative_to(repo_dir)))
    return str(target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--candidate", default="", help="a named candidate in the corpus (confirm: phase 7)")
    parser.add_argument("--debian", action="store_true", help="allow deb.debian.org in the mandate (variant)")
    parser.add_argument("--ci-env", action="store_true", help="let the team's CI job prepare the environment")
    args = parser.parse_args()
    corpus = yaml.safe_load(Path(args.corpus).read_text())
    candidate, wheel = candidate_of(corpus, args.candidate)
    only = {n for n in args.only.split(",") if n}
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "summary-A.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else []
    done = {s["name"] for s in summary}
    for repo in corpus["repos"]:
        if (only and repo["name"] not in only) or (not only and repo["name"] in done):
            continue
        print(
            f"== {repo['name']} ({repo.get('class')}, {repo.get('family')}) load {os.getloadavg()[0]:.1f}", flush=True
        )
        line = level_a(repo, args.phase, out, args.port, candidate, wheel, debian=args.debian, ci_env=args.ci_env)
        summary = [s for s in summary if s["name"] != repo["name"]] + [line]
        summary_path.write_text(json.dumps(summary, indent=1, default=str))
        print(scrub(json.dumps(line, default=str))[:700], flush=True)


if __name__ == "__main__":
    main()
