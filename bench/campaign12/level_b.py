"""Campaign 12, Level B: two autonomous runs per chosen repository, from the same restored state, on the installed
product, with a campaign fork for pull requests and merges and a campaign lab for deploys (applications only).

    uv run python -m bench.campaign12.level_b bench/campaign12/corpus.yaml --repo spoolman --run 1 --phase pilot \
        --out docs/bench/campaign12/pilot

Human preparation, counted and recorded apart: the fork and its campaign base branch, the lab (compose, synthetic
data, a read-only role), the mandate's operations (deploy steps, check steps, health), the rollback drill, and the
GitHub token held by the campaign HOME. The run itself: `unbidden start --ui` (the agent and its dashboard in one
process), cycles bounded in time, `stop`, `start` again (the second cycle must not repeat an effect), the dashboard
read with a browser and through its API, the chat (one deterministic question, one analysis), the ledger before and
after, the fork and the lab inspected independently (pull requests, merges, deploy health). Nobody helps the agent
during a run: an intervention ends the autonomous attempt and is recorded as such.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from bench.campaign12 import labs
from bench.campaign12.common import (
    LAB,
    REAL_HOME,
    Record,
    Step,
    candidate_of,
    env,
    envelope_for,
    ledger,
    run,
    run_spend,
    scrub,
    unbidden,
)
from bench.campaign12.copies import ci_pending, copy_state, ensure_copy
from bench.campaign12.level_a import archive, key_from_machine

CYCLE_BOUND_S = 5400
IDLE_POLL_S = 20
GH = "satisfymath"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def gh(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    token = subprocess.run(["gh", "auth", "token", "-u", GH], capture_output=True, text=True, check=True).stdout.strip()
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "GH_TOKEN": token},
    )


def fork_for(repo: dict[str, Any], rec: Record) -> dict[str, Any]:
    """The campaign copy (`satisfymath/c12-<name>`, a plain public repository at the pin, its default branch the
    upstream's; see `copies.py`) that the product sees as its GitHub repository. Forks were abandoned on 2026-11-01:
    GitHub does not start `pull_request` workflows on them, so CI, merges and deploys were unobservable."""
    return ensure_copy(repo, rec.human)


def fork_state(slug: str, base: str) -> dict[str, Any]:
    return copy_state(slug, base)


def write_mandate(
    repo_dir: Path,
    repo: dict[str, Any],
    fork: dict[str, Any],
    lab: dict[str, Any] | None,
    e: dict[str, str],
    rec: Record,
) -> None:
    """The product's own setup (scripted form), then the operations and GitHub target a person declares, written as
    YAML by the harness and validated by `unbidden mode`/`doctor` afterwards. Counted as human preparation."""
    key = key_from_machine()
    token = key_from_machine("GITHUB_TOKEN")
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
                "autopilot",
                "--budget",
                "2",
                "--dashboard",
                "later",
                "--model-key-stdin",
                "--github-token-stdin",
                "--yes",
                "--json",
            ],
            cwd=repo_dir,
            env_=e,
            timeout_s=600,
            stdin=f"{key}\n{token}\n",
        )
    )
    rec.facts["setup"] = {"ok": setup.code == 0, "applied": (setup.json() or {}).get("applied")}
    path = repo_dir / ".unbidden" / "mandate.yaml"
    raw = yaml.safe_load(path.read_text())
    m = raw["mandate"]
    m["priorities"] = ["correctness", "performance of reads as data grows", "robustness"]
    m["egress"]["github"] = {"repository": fork["slug"], "base_branch": fork["base"], "max_open_pull_requests": 3}
    m["egress"]["package_registries"] = [
        "pypi.org",
        "files.pythonhosted.org",
        "deb.debian.org",
        "registry.npmjs.org",
        "ghcr.io",
        "registry-1.docker.io",
    ]
    m["models"]["private_code_to_frontier"] = "allow"  # public repositories, declared
    m["autonomy"]["use_new_capabilities"] = "allow"
    m["autonomy"]["act_on_connections"] = "allow" if lab and lab.get("writes") else "deny"
    if lab:
        m["operations"] = {
            "deploy_steps": lab["deploy_steps"],
            "check_steps": lab["check_steps"],
            "check_image": lab["check_image"],
            "max_deploys_per_hour": 6,
            "probe_every_s": 5.0,
        }
        m["connections"] = lab["connections"]
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    rec.human.append(
        {"step": "mandate: fork, registries, operations, connections", "minutes": 2, "why": "a person's declaration"}
    )
    if lab and lab.get("credentials"):
        envf = repo_dir / ".unbidden" / ".env"
        envf.write_text("".join(f"{k}={v}\n" for k, v in lab["credentials"].items()))
        envf.chmod(0o600)
        rec.human.append(
            {"step": "connection credentials into the project's .env", "minutes": 1, "why": "read-only role"}
        )


def enable_autonomy(repo_dir: Path, lab: dict[str, Any] | None, e: dict[str, str], rec: Record) -> str:
    """autopilot for libraries; for applications: map while the lab runs, the rollback drill, then `mode autonomous`
    through the product's own command (its conditions enforced by it)."""
    if not lab:
        rec.facts["mode"] = {"asked": "autopilot", "why": "a library has no deploy: autonomous is not available"}
        return "autopilot"
    rec.add(run("map", [unbidden(), "map", "--json"], cwd=repo_dir, env_=e, timeout_s=900))
    drill = rec.add(run("drill", [unbidden(), "drill", "--json"], cwd=repo_dir, env_=e, timeout_s=1800))
    rec.human.append(
        {
            "step": "rollback drill (the product's command; the lab's steps)",
            "minutes": round(drill.seconds / 60, 1),
            "why": "autonomous requires a passed drill",
        }
    )
    mode = rec.add(
        run("mode-autonomous", [unbidden(), "mode", "autonomous", "--json"], cwd=repo_dir, env_=e, timeout_s=300)
    )
    if mode.code != 0:
        rec.blocks.append(f"autonomous refused by the product: {scrub((mode.stderr or mode.stdout)[-300:])}")
        rec.facts["mode"] = {
            "asked": "autonomous",
            "got": "autopilot",
            "drill_code": drill.code,
            "mode_code": mode.code,
        }
        return "autopilot"
    rec.facts["mode"] = {"asked": "autonomous", "got": "autonomous", "drill_code": drill.code}
    return "autonomous"


def _store_counts(repo_dir: Path) -> dict[str, Any]:
    import sqlite3

    try:
        c = sqlite3.connect(str(repo_dir / ".unbidden" / "state.db"))
        events = dict(c.execute("select type, count(*) from events group by type").fetchall())
        docs = dict(c.execute("select collection, count(*) from docs group by collection").fetchall())
        jobs = dict(c.execute("select status, count(*) from jobs group by status").fetchall())
        proposals = [json.loads(r[0]) for r in c.execute("select doc from docs where collection='proposals'")]
        c.close()
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    return {
        "events": events,
        "docs": docs,
        "jobs": jobs,
        "proposals": [
            {k: p.get(k) for k in ("id", "opportunity_id", "status", "branch", "evidence_level", "title")}
            | {"pr": (p.get("pr") or {}).get("url")}
            for p in proposals
        ],
    }


def cycle(
    repo_dir: Path,
    e: dict[str, str],
    rec: Record,
    label: str,
    port: int,
    bound_s: float,
    copy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One bounded cycle of the daemon serving its dashboard: start, wait until the queue is idle (or the bound),
    read the state, stop. The agent is never helped."""
    start = rec.add(
        run(
            f"{label}-start",
            [unbidden(), "start", "--ui", "--port", str(port), "--interval", "60", "--json"],
            cwd=repo_dir,
            env_=e,
            timeout_s=300,
        )
    )
    began = time.monotonic()
    idle_since: float | None = None
    last: dict[str, Any] = {}
    while time.monotonic() - began < bound_s:
        time.sleep(IDLE_POLL_S)
        st = run("status", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=120).json() or {}
        agent = st.get("agent") or {}
        last = st
        if not agent.get("running"):
            break
        if (agent.get("jobs_queued") or 0) + (agent.get("jobs_running") or 0) == 0:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since > 150:  # idle through two ticks of the loop
                # An open pull request whose CI is still to come keeps the cycle observed (the agent polls it on its
                # own ticks; the harness only waits longer, within the bound; nothing is said to the agent).
                if copy and ci_pending(copy["slug"], copy["base"]):
                    idle_since = time.monotonic()
                    continue
                break
        else:
            idle_since = None
    waited = round(time.monotonic() - began, 1)
    out: dict[str, Any] = {
        "started": (start.json() or {}).get("started"),
        "waited_s": waited,
        "bound_hit": waited >= bound_s,
        "status_at_end": last.get("agent"),
        "counts": _store_counts(repo_dir),
    }
    return out


def ui_and_chat(repo_dir: Path, e: dict[str, str], rec: Record, out_dir: Path, label: str) -> dict[str, Any]:
    """While the agent serves its dashboard: the browser walk, the API's summary, one deterministic chat question and
    one analysis through the product's chat (its route recorded)."""
    info_path = repo_dir / ".unbidden" / "ui.json"
    if not info_path.exists():
        return {"opened": False, "why": "no ui.json: the agent did not serve a dashboard"}
    info = json.loads(info_path.read_text())
    base = f"http://127.0.0.1:{info['port']}"
    headers = {"Authorization": f"Bearer {info['token']}"}
    out: dict[str, Any] = {"opened": True, "in_daemon": info.get("in_daemon")}
    try:
        sid = httpx.get(f"{base}/api/session", headers=headers, timeout=10).json()["sources"][0]["id"]
        summary = httpx.get(f"{base}/api/ws/{sid}/summary", headers=headers, timeout=30).json()
        out["summary"] = {
            "mode": summary["workspace"]["mode"],
            "freshness": summary.get("freshness"),
            "counts": summary.get("counts"),
            "agent": summary["connection"].get("agent"),
            "key_present": summary["connection"]["route"]["remote"].get("key_present"),
        }
        opps = httpx.get(f"{base}/api/ws/{sid}/opportunities", headers=headers, timeout=30).json()
        out["opportunities_total"] = opps.get("total")
        # a widget from existing data, by rules (no model), with its provenance
        with httpx.stream(
            "POST",
            f"{base}/api/ws/{sid}/chat",
            headers=headers,
            timeout=120,
            json={"content": "Añade una tabla con las oportunidades", "selected": [], "planner": "rule"},
        ) as r:
            for _ in r.iter_lines():
                pass
        pres = httpx.get(f"{base}/api/ws/{sid}/presentation", headers=headers, timeout=30).json()
        out["widgets"] = [
            {
                "type": w["type"],
                "title": w["title"],
                "provenance": w.get("provenance", {}).get("completeness"),
                "source": w.get("provenance", {}).get("source"),
            }
            for w in pres.get("widgets", [])
        ]
    except Exception as exc:
        out["api_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    # the browser
    shots = out_dir / f"ui-{label}"
    node = run(
        "ui-browser",
        ["node", str(FRONTEND / "scripts" / "c12_ui_check.mjs"), info["url"], str(shots)],
        cwd=FRONTEND,
        env_={**os.environ, "HOME": str(REAL_HOME)},
        timeout_s=300,
    )
    rec.steps.append(node.record())
    out["browser"] = node.json()
    # the chat from the terminal: deterministic, then an analysis (one routed call, recorded)
    q1 = rec.add(
        run(
            "chat-status",
            [unbidden(), "chat", "--json", "¿Qué ha hecho el agente hasta ahora y cuántas oportunidades hay?"],
            cwd=repo_dir,
            env_=e,
            timeout_s=300,
        )
    )
    q2 = rec.add(
        run(
            "chat-analyze",
            [unbidden(), "chat", "--json", "¿Qué hallazgo priorizarías y por qué? Di qué falta en el registro."],
            cwd=repo_dir,
            env_=e,
            timeout_s=600,
        )
    )
    for name, step in (("status", q1), ("analyze", q2)):
        d = step.json() or {}
        out[f"chat_{name}"] = {
            "planner": d.get("planner"),
            "route": d.get("route"),
            "state": d.get("state"),
            "content": scrub(str(d.get("content", "")))[:400],
        }
    return out


def level_b(
    repo: dict[str, Any], run_no: int, phase: str, out_dir: Path, port: int, candidate: str, wheel: str
) -> dict[str, Any]:
    name = repo["name"]
    envelope = envelope_for(phase)
    e = env(envelope, f"c12-{phase}-B{run_no}-{name}")  # the phase in the tag: pilot and eval spend never mix
    rec = Record(repo=name, phase=phase, run=f"B{run_no}", candidate=candidate, wheel_sha256=wheel)
    rec.facts["repo"] = {k: repo.get(k) for k in ("url", "commit", "family", "class", "build", "lab")}
    rec.facts["ledger_before"] = ledger(envelope)
    fork = fork_for(repo, rec)
    rec.facts["fork"] = fork
    rec.facts["fork_before"] = fork_state(fork["slug"], fork["base"])
    lab_info: dict[str, Any] | None = None
    t0 = time.monotonic()
    # A clean checkout under the campaign lab, no .unbidden, at the copy's base head: the pin plus the one documented
    # campaign commit (a proposal's base is the local HEAD; the product marks it stale when the remote base differs).
    copy_url = f"https://github.com/{fork['slug']}"
    existing = labs.repo_dir(repo, LAB)
    if (existing / ".git").exists():
        subprocess.run(["git", "-C", str(existing), "remote", "set-url", "origin", copy_url], check=True)
    repo_dir = labs.restore({**repo, "url": copy_url, "commit": fork["base_sha"]}, LAB)
    rec.facts["repo"]["copy_base_sha"] = fork["base_sha"]
    if repo.get("lab"):
        lab_info = labs.up(repo["lab"], LAB)  # compose, data, roles: human preparation
        rec.human.append(
            {
                "step": f"lab {repo['lab']} up and seeded",
                "minutes": round((time.monotonic() - t0) / 60, 1),
                "why": "the application's own services, synthetic data, a read-only role",
            }
        )
        rec.facts["lab"] = {k: v for k, v in lab_info.items() if k != "credentials"}
        rec.human.extend(lab_info.get("prep", []))
    # the copy is the origin the product sees (pull requests go there); upstream is never a remote of this checkout
    subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "set-url", "origin", f"git@github-satisfymath:{fork['slug']}.git"],
        check=True,
    )
    write_mandate(repo_dir, repo, fork, lab_info, e, rec)
    rec.facts["doctor"] = (
        rec.add(run("doctor", [unbidden(), "doctor", "--json"], cwd=repo_dir, env_=e, timeout_s=600)).json() or {}
    )
    rec.facts["doctor"] = {k: rec.facts["doctor"].get(k) for k in ("ok", "failed_required", "requirements")}
    rec.facts["mode_got"] = enable_autonomy(repo_dir, lab_info, e, rec)
    rec.facts["cycle1"] = cycle(repo_dir, e, rec, "c1", port, CYCLE_BOUND_S, fork)
    rec.facts["ui1"] = ui_and_chat(repo_dir, e, rec, out_dir / name / f"B{run_no}", "c1")
    rec.add(run("c1-stop", [unbidden(), "stop", "--json"], cwd=repo_dir, env_=e, timeout_s=300))
    rec.facts["fork_after_c1"] = fork_state(fork["slug"], fork["base"])
    if lab_info:
        rec.facts["lab_after_c1"] = labs.observe(repo["lab"], LAB)
    # the second cycle: from the same workspace, after a stop; nothing done must be done twice
    rec.facts["cycle2"] = cycle(repo_dir, e, rec, "c2", port, CYCLE_BOUND_S // 2, fork)
    rec.add(run("c2-stop", [unbidden(), "stop", "--json"], cwd=repo_dir, env_=e, timeout_s=300))
    rec.facts["fork_after_c2"] = fork_state(fork["slug"], fork["base"])
    if lab_info:
        rec.facts["lab_after_c2"] = labs.observe(repo["lab"], LAB)
    rec.facts["status_final"] = (
        rec.add(run("status-final", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=120)).json() or {}
    ).get("agent")
    rec.facts["egress"] = _egress_summary(
        rec.add(run("egress", [unbidden(), "egress", "--json"], cwd=repo_dir, env_=e, timeout_s=300))
    )
    rec.facts["ledger_after"] = ledger(envelope)
    rec.facts["run_spend"] = run_spend(e["UNBIDDEN_RUN"], e["UNBIDDEN_ENVELOPE"])
    rec.facts["spent_usd"] = rec.facts["run_spend"]["usd"]
    rec.facts["archive"] = archive(repo_dir, f"{name}-B{run_no}-{phase}")
    if lab_info:
        labs.down(repo["lab"], LAB)
    path = rec.write(out_dir / name / f"B{run_no}.json")
    c1, c2 = rec.facts["cycle1"]["counts"], rec.facts["cycle2"]["counts"]
    return {
        "name": name,
        "run": f"B{run_no}",
        "mode": rec.facts["mode_got"],
        "record": str(path),
        "proposals_c1": len(c1.get("proposals", [])),
        "proposals_c2": len(c2.get("proposals", [])),
        "pulls_after": len(rec.facts["fork_after_c2"].get("pulls") or []),
        "spent_usd": rec.facts["spent_usd"],
        "blocks": rec.blocks,
        "wall_s": round(
            sum(s["seconds"] for s in rec.steps) + rec.facts["cycle1"]["waited_s"] + rec.facts["cycle2"]["waited_s"], 1
        ),
    }


def _egress_summary(step: Step) -> dict[str, Any]:
    rows = step.json() or []
    by: dict[str, int] = {}
    for r in rows if isinstance(rows, list) else []:
        key = f"{r.get('destination')}:{r.get('purpose')}:{r.get('status')}"
        by[key] = by.get(key, 0) + 1
    return by


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--port", type=int, default=8860)
    parser.add_argument("--candidate", default="", help="a named candidate in the corpus (confirm: phase 7)")
    args = parser.parse_args()
    corpus = yaml.safe_load(Path(args.corpus).read_text())
    repo = next(r for r in corpus["repos"] if r["name"] == args.repo)
    out = Path(args.out).expanduser().resolve()  # absolute: the browser check runs from frontend/
    candidate, wheel = candidate_of(corpus, args.candidate)
    line = level_b(repo, args.run, args.phase, out, args.port, candidate, wheel)
    summary_path = out / "summary-B.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else []
    summary = [s for s in summary if not (s["name"] == line["name"] and s["run"] == line["run"])] + [line]
    summary_path.write_text(json.dumps(summary, indent=1, default=str))
    print(scrub(json.dumps(line, default=str))[:900])


if __name__ == "__main__":
    main()
