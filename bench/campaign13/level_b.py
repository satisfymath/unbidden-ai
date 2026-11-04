"""Campaign 13, Level B: autonomous runs per chosen repository, from the same restored state, on the installed
product, with a campaign copy for pull requests and merges, and a deploy target for applications: a hand lab
(fst, spoolman: `labs.py`) or the product's own `unbidden host up` (operations.self_host) for every other application.
Libraries and CLIs, and applications the product could not bring up, run in a custom mode: pull requests opened and
merged on the team's green CI, nothing deployed (the `autonomous` preset needs deploy steps and a passed drill).

    uv run python -m bench.campaign13.level_b bench/campaign13/corpus.yaml --repo spoolman --run 1 --phase pilot \
        --out docs/bench/campaign13/pilot [--port 8860 --lab-port 18230 --lab-db-port 55530]

Parallel-safe (run_final.py runs several at once): every port comes from the arguments (the worker's range), each
repository writes under its own directory (`<out>/<repo>/`), and `summary-B.json` is updated under a file lock.
After each run the product's own `unbidden export` (when the installed version has it) writes the evidence into
`<out>/<repo>/export/`, with the workspace archive beside it unless it is larger than 25 MB.

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
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from bench.campaign13 import labs
from bench.campaign13.asks import REGISTRIES, Policy, answer_open
from bench.campaign13.common import (
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
    sha256_of,
    unbidden,
    update_summary,
)
from bench.campaign13.copies import ci_pending, copy_state, ensure_copy
from bench.campaign13.level_a import _checks_record, archive, key_from_machine  # pyright: ignore[reportPrivateUsage]

CYCLE_BOUND_S = 5400
IDLE_POLL_S = 20
HOST_UP_S = 3600
GH = "satisfymath"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
ARCHIVE_COPY_MAX_BYTES = 25 * 1024 * 1024  # larger archives stay in the lab's archive dir, for a release asset
# Merges on the team's green CI, nothing deployed: the mode of a repository with nothing to deploy. The product's
# `autonomous` preset (guardian/mandate_edit.py MODES) also allows deploy and rollback and needs deploy steps and a
# passed drill; `Publisher.merge` itself asks L4, green CI on the measured head, and a verdict on the previous deploy
# only once two deploys exist (none here), so this combination merges.
CUSTOM_AUTONOMY = {
    "open_pull_requests": "allow",
    "merge_pull_requests": "allow",
    "deploy": "deny",
    "rollback": "deny",
    "use_new_capabilities": "allow",
}
UNKNOWN_COMMAND = ("no such command", "unknown command", "invalid choice", "usage:")


def is_app_family(family: str | None) -> bool:
    """An application the product can bring up itself (operations.self_host): api-* and web-* families."""
    return bool(family) and str(family).startswith(("api-", "web-"))


def deploy_target(repo: dict[str, Any]) -> str:
    """`lab` (a hand lab: fst, spoolman), `self_host` (an application without one) or `none` (libraries, CLIs, ...)."""
    if repo.get("lab"):
        return "lab"
    return "self_host" if is_app_family(repo.get("family")) else "none"


def command_missing(step: Step) -> bool:
    """The installed product does not know the command (an older wheel): exit 2 from the parser, or its words."""
    text = f"{step.stdout}\n{step.stderr}".lower()
    return step.code != 0 and not step.timed_out and (step.code == 2 or any(w in text for w in UNKNOWN_COMMAND))


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
    """The campaign copy (`satisfymath/c13-<name>`, a plain public repository at the pin, its default branch the
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
    budget: str = "5",
    self_host: bool = False,
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
                budget,  # the project's monthly cap: US$5 in campaign 13 (PROTOCOL.md §5)
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
    # The final pass's mandate, "every permission" (PROTOCOL.md §5): registries, models, capabilities, connections.
    m["egress"]["package_registries"] = list(REGISTRIES)
    m["models"]["private_code_to_frontier"] = "allow"  # public repositories, declared
    m["models"]["screenshots_to_frontier"] = "allow"
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
    elif self_host:
        # An application without a hand lab: the product brings it up from the repository's own compose file
        # (`unbidden host up`), writes the deploy steps and the health URL, and runs the drill. labs.py is not used.
        ops = m.get("operations") if isinstance(m.get("operations"), dict) else {}
        m["operations"] = {**ops, "self_host": "allow"}
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


def host_up(repo_dir: Path, e: dict[str, str], rec: Record) -> dict[str, Any]:
    """The product brings the application up by itself (`unbidden host up`): compose project, deploy steps and health
    URL into the mandate, the drill. The whole answer is the record; an older product without the command says so."""
    step = rec.add(
        run("host-up", [unbidden(), "host", "up", "--yes", "--json"], cwd=repo_dir, env_=e, timeout_s=HOST_UP_S)
    )
    if command_missing(step):
        return {"ok": False, "available": False, "why": "`unbidden host` unavailable in the installed product"}
    data = step.json()
    out: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
    out["ok"] = bool(out.get("ok")) and step.code == 0
    out.setdefault("why", None if out["ok"] else scrub((step.stderr or step.stdout)[-300:]) or f"exit {step.code}")
    out["code"] = step.code
    return out


def host_down(repo_dir: Path, e: dict[str, str], rec: Record) -> dict[str, Any]:
    step = rec.add(run("host-down", [unbidden(), "host", "down", "--json"], cwd=repo_dir, env_=e, timeout_s=900))
    return {"code": step.code, "answer": step.json()}


def _autonomy_now(repo_dir: Path) -> dict[str, Any]:
    raw = yaml.safe_load((repo_dir / ".unbidden" / "mandate.yaml").read_text()) or {}
    return dict((raw.get("mandate") or {}).get("autonomy") or {})


def custom_autonomy(repo_dir: Path, rec: Record, why: str) -> str:
    """Nothing to deploy: the autonomy fields written directly in the mandate (merge on green CI, no deploy)."""
    path = repo_dir / ".unbidden" / "mandate.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["mandate"].setdefault("autonomy", {}).update(CUSTOM_AUTONOMY)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    rec.human.append({"step": "mandate autonomy: merge on green CI, no deploy", "minutes": 1, "why": why})
    rec.facts["mode"] = {"asked": "custom", "got": "custom", "why": why}
    rec.facts["autonomy"] = {"mode": "custom", "why": why, "fields": _autonomy_now(repo_dir)}
    return "custom"


def enable_autonomy(
    repo_dir: Path, lab: dict[str, Any] | None, e: dict[str, str], rec: Record, hosted: dict[str, Any] | None = None
) -> str:
    """With a deploy target (a hand lab, or the product's own `host up`): map, the rollback drill (the hand lab's;
    `host up` ran its own), then `mode autonomous` through the product's own command (its conditions enforced by
    it). Without one, or when the product refuses: the custom mode (merges, no deploy)."""
    if not lab and not (hosted and hosted.get("ok")):
        why = "nothing to deploy: " + (
            f"`unbidden host up` did not bring it up ({hosted.get('why')})" if hosted else "not an application"
        )
        return custom_autonomy(repo_dir, rec, why)
    rec.add(run("map", [unbidden(), "map", "--json"], cwd=repo_dir, env_=e, timeout_s=900))
    drill_code: int | None = None
    if lab:
        drill = rec.add(run("drill", [unbidden(), "drill", "--json"], cwd=repo_dir, env_=e, timeout_s=1800))
        drill_code = drill.code
        rec.human.append(
            {
                "step": "rollback drill (the product's command; the lab's steps)",
                "minutes": round(drill.seconds / 60, 1),
                "why": "autonomous requires a passed drill",
            }
        )
    else:
        drill_code = 0 if ((hosted or {}).get("drill") or {}).get("ok") else 1
    mode = rec.add(
        run("mode-autonomous", [unbidden(), "mode", "autonomous", "--json"], cwd=repo_dir, env_=e, timeout_s=300)
    )
    if mode.code != 0:
        rec.blocks.append(f"autonomous refused by the product: {scrub((mode.stderr or mode.stdout)[-300:])}")
        got = custom_autonomy(repo_dir, rec, "autonomous refused by the product")
        rec.facts["mode"] = {"asked": "autonomous", "got": got, "drill_code": drill_code, "mode_code": mode.code}
        return got
    rec.facts["mode"] = {"asked": "autonomous", "got": "autonomous", "drill_code": drill_code}
    rec.facts["autonomy"] = {"mode": "autonomous", "deploy_target": "lab" if lab else "self_host",
                             "fields": _autonomy_now(repo_dir)}  # fmt: skip
    return "autonomous"


def _store_counts(repo_dir: Path) -> dict[str, Any]:
    """What the workspace's store holds, read apart from the product's commands: counts, the opportunities with their
    class (category, source, level, the live outcome a deploy gave), experiments, verdicts' criteria, proposals."""
    import sqlite3

    try:
        c = sqlite3.connect(str(repo_dir / ".unbidden" / "state.db"))
        events = dict(c.execute("select type, count(*) from events group by type").fetchall())
        docs = dict(c.execute("select collection, count(*) from docs group by collection").fetchall())
        jobs = dict(c.execute("select status, count(*) from jobs group by status").fetchall())

        def collection(name: str) -> list[dict[str, Any]]:
            return [json.loads(r[0]) for r in c.execute("select doc from docs where collection=?", (name,))]

        proposals = collection("proposals")
        opportunities = collection("opportunities")
        verdicts = collection("verdicts")
        c.close()
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    return summarize_store(events, docs, jobs, proposals, opportunities, verdicts)


def summarize_store(
    events: dict[str, int],
    docs: dict[str, int],
    jobs: dict[str, int],
    proposals: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    criteria_of = {v.get("experiment_id"): v.get("criteria") for v in verdicts}
    opps = []
    for o in opportunities:
        outcome = (o.get("details") or {}).get("outcome") or {}
        row = {k: o.get(k) for k in ("id", "source", "category", "evidence_level", "status")}
        if outcome:
            row["outcome"] = {k: outcome.get(k) for k in ("result", "deploy", "criteria", "promoted")}
        opps.append(row)
    levels = [int(o.get("evidence_level") or 0) for o in opportunities]
    top = max(levels, default=0)
    top_opp = next((o for o in opps if int(o.get("evidence_level") or 0) == top), None) if top else None
    top_props = [p for p in proposals if top_opp and p.get("opportunity_id") == top_opp["id"]]
    level_criteria = (
        (top_opp or {}).get("outcome", {}).get("criteria")
        if top >= 5
        else (criteria_of.get(top_props[0].get("experiment_id")) if top_props else None)
    )
    return {
        "events": events,
        "docs": docs,
        "jobs": jobs,
        "experiments": docs.get("experiments", 0),
        "opportunities": opps,
        "level_max": top,
        "level_max_criteria": level_criteria,
        "level_max_outcome": (top_opp or {}).get("outcome"),
        "proposals": [
            {
                k: p.get(k)
                for k in ("id", "opportunity_id", "experiment_id", "status", "branch", "evidence_level", "title")
            }
            | {"pr": (p.get("pr") or {}).get("url"), "criteria": criteria_of.get(p.get("experiment_id"))}
            for p in proposals
        ],
    }


def export_workspace(repo_dir: Path, e: dict[str, str], dest: Path, rec: Record, runner: Any = run) -> dict[str, Any]:
    """The product's own export of the workspace's evidence (`unbidden export --out DIR`). An installed product
    without the command is recorded as such ("export unavailable") and the run goes on."""
    dest.mkdir(parents=True, exist_ok=True)
    step = runner("export", [unbidden(), "export", "--out", str(dest)], cwd=repo_dir, env_=e, timeout_s=900)
    rec.add(step)
    if command_missing(step):
        return {"available": False, "why": "export unavailable", "code": step.code}
    files = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    return {"available": True, "ok": step.code == 0, "code": step.code, "dir": str(dest), "files": len(files),
            "answer": step.json()}  # fmt: skip


def keep_archive(archive_path: str | None, dest_dir: Path, limit: int = ARCHIVE_COPY_MAX_BYTES) -> dict[str, Any]:
    """The workspace archive next to the export unless it is larger than the limit: then its sha256 and size are
    recorded and it stays in the lab's archive dir, to be uploaded as a release asset."""
    if not archive_path or not Path(archive_path).exists():
        return {"kept": False, "why": "no archive"}
    src = Path(archive_path)
    size = src.stat().st_size
    out: dict[str, Any] = {"name": src.name, "bytes": size, "sha256": sha256_of(src)}
    if size > limit:
        return out | {
            "kept": False,
            "where": str(src),
            "why": f"larger than {limit // (1024 * 1024)} MB: release asset",
        }
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / src.name)
    return out | {"kept": True, "where": str(dest_dir / src.name)}


def cycle(
    repo_dir: Path,
    e: dict[str, str],
    rec: Record,
    label: str,
    port: int,
    bound_s: float,
    copy: dict[str, Any] | None = None,
    policy: Policy | None = None,
) -> dict[str, Any]:
    """One bounded cycle of the daemon serving its dashboard: start, answer the agent's questions by the protocol's
    table (PROTOCOL.md §7, recorded), wait until the product says it is idle twice in a row (or the bound), read the
    state, stop. The agent is never helped otherwise."""
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
    idle_ticks = 0
    last: dict[str, Any] = {}
    answered: list[dict[str, Any]] = []
    while time.monotonic() - began < bound_s:
        time.sleep(IDLE_POLL_S)
        st = run("status", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=120).json() or {}
        agent = st.get("agent") or {}
        last = st
        if not agent.get("running"):
            break
        if policy is not None and st.get("asks"):
            answered += answer_open(repo_dir, e, policy)
            idle_ticks = 0
            continue
        # The product's own idle signal (0.13.0): only housekeeping is due. Two readings in a row, a poll apart.
        if st.get("idle"):
            idle_ticks += 1
            if idle_ticks >= 2:
                # An open pull request whose CI is still to come keeps the cycle observed (the agent polls it on its
                # own ticks; the harness only waits longer, within the bound; nothing is said to the agent).
                if copy and ci_pending(copy["slug"], copy["base"]):
                    idle_ticks = 0
                    continue
                break
        else:
            idle_ticks = 0
    waited = round(time.monotonic() - began, 1)
    out: dict[str, Any] = {
        "started": (start.json() or {}).get("started"),
        "waited_s": waited,
        "bound_hit": waited >= bound_s,
        "status_at_end": last.get("agent"),
        "open_asks_at_end": len(last.get("asks") or []),
        "open_blocks_at_end": [{"kind": b.get("kind"), "needs": b.get("needs")} for b in last.get("blocks") or []],
        "asks_answered": answered,
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
        ["node", str(FRONTEND / "scripts" / "c13_ui_check.mjs"), info["url"], str(shots)],
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
    repo: dict[str, Any],
    run_no: int,
    phase: str,
    out_dir: Path,
    port: int,
    candidate: str,
    wheel: str,
    budget: str = "2",
    lab_ports: tuple[int, int] | None = None,
) -> dict[str, Any]:
    name = repo["name"]
    target = deploy_target(repo)
    envelope = envelope_for(phase)
    e = env(envelope, f"c13-{phase}-B{run_no}-{name}")  # the phase in the tag: pilot and eval spend never mix
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
        lab_info = labs.up(repo["lab"], LAB, ports=lab_ports)  # compose, data, roles: human preparation
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
    rec.facts["deploy_target"] = target
    write_mandate(repo_dir, repo, fork, lab_info, e, rec, budget=budget, self_host=target == "self_host")
    rec.facts["doctor"] = (
        rec.add(run("doctor", [unbidden(), "doctor", "--json"], cwd=repo_dir, env_=e, timeout_s=600)).json() or {}
    )
    rec.facts["doctor"] = {k: rec.facts["doctor"].get(k) for k in ("ok", "failed_required", "requirements")}
    hosted: dict[str, Any] | None = None
    if target == "self_host":
        hosted = rec.facts["self_host"] = host_up(repo_dir, e, rec)
    rec.facts["mode_got"] = enable_autonomy(repo_dir, lab_info, e, rec, hosted)
    deployable = lab_info is not None or bool(hosted and hosted.get("ok"))
    # The agent's questions are answered by the protocol's table only (PROTOCOL.md §7); every answer is recorded.
    policy = Policy(mode=rec.facts["mode_got"], lab=deployable,
                    credentials={"MODEL_API_KEY": key_from_machine()})  # fmt: skip
    rec.facts["cycle1"] = cycle(repo_dir, e, rec, "c1", port, CYCLE_BOUND_S, fork, policy)
    rec.facts["ui1"] = ui_and_chat(repo_dir, e, rec, out_dir / name / f"B{run_no}", "c1")
    rec.add(run("c1-stop", [unbidden(), "stop", "--json"], cwd=repo_dir, env_=e, timeout_s=300))
    rec.facts["fork_after_c1"] = fork_state(fork["slug"], fork["base"])
    if lab_info:
        rec.facts["lab_after_c1"] = labs.observe(repo["lab"], LAB, port=lab_info["port"])
    # the second cycle: from the same workspace, after a stop; nothing done must be done twice
    rec.facts["cycle2"] = cycle(repo_dir, e, rec, "c2", port, CYCLE_BOUND_S // 2, fork, policy)
    rec.facts["asks_answered"] = policy.answered
    rec.add(run("c2-stop", [unbidden(), "stop", "--json"], cwd=repo_dir, env_=e, timeout_s=300))
    rec.facts["fork_after_c2"] = fork_state(fork["slug"], fork["base"])
    if lab_info:
        rec.facts["lab_after_c2"] = labs.observe(repo["lab"], LAB, port=lab_info["port"])
    rec.facts["status_final"] = (
        rec.add(run("status-final", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=120)).json() or {}
    ).get("agent")
    rec.facts["egress"] = _egress_summary(
        rec.add(run("egress", [unbidden(), "egress", "--json"], cwd=repo_dir, env_=e, timeout_s=300))
    )
    rec.facts["checks"] = _checks_record(repo_dir)  # the project's own checks at the base, as the agent recorded them
    rec.facts["ledger_after"] = ledger(envelope)
    rec.facts["run_spend"] = run_spend(e["UNBIDDEN_RUN"], e["UNBIDDEN_ENVELOPE"])
    rec.facts["spent_usd"] = rec.facts["run_spend"]["usd"]
    export_dir = out_dir / name / ("export" if run_no == 1 else f"export-B{run_no}")
    rec.facts["export"] = export_workspace(repo_dir, e, export_dir, rec)
    rec.facts["archive"] = archive(repo_dir, f"{name}-B{run_no}-{phase}")
    rec.facts["archive_kept"] = keep_archive(rec.facts["archive"], export_dir)
    if lab_info:
        labs.down(repo["lab"], LAB)
    if hosted is not None and hosted.get("available", True):
        rec.facts["self_host_down"] = host_down(repo_dir, e, rec)
    path = rec.write(out_dir / name / f"B{run_no}.json")
    c1, c2 = rec.facts["cycle1"]["counts"], rec.facts["cycle2"]["counts"]
    return {
        "name": name,
        "run": f"B{run_no}",
        "mode": rec.facts["mode_got"],
        "deploy_target": target,
        "self_host_ok": (hosted or {}).get("ok"),
        "export": rec.facts["export"].get("available") and rec.facts["export"].get("ok"),
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
    parser.add_argument("--port", type=int, default=8860, help="the dashboard's port (one per parallel worker)")
    parser.add_argument("--lab-port", type=int, help="the hand lab's application port (default: labs.PORTS)")
    parser.add_argument("--lab-db-port", type=int, help="the hand lab's database port (default: labs.PORTS)")
    parser.add_argument("--candidate", default="", help="a named candidate in the corpus (confirm: phase 7)")
    parser.add_argument("--budget", default="2", help="the project's monthly cap in US$ (variant; default 2)")
    args = parser.parse_args()
    corpus = yaml.safe_load(Path(args.corpus).read_text())
    repo = next(r for r in corpus["repos"] if r["name"] == args.repo)
    out = Path(args.out).expanduser().resolve()  # absolute: the browser check runs from frontend/
    candidate, wheel = candidate_of(corpus, args.candidate)
    lab_ports = (args.lab_port, args.lab_db_port) if args.lab_port and args.lab_db_port else None
    line = level_b(
        repo, args.run, args.phase, out, args.port, candidate, wheel, budget=args.budget, lab_ports=lab_ports
    )
    update_summary(out / "summary-B.json", line, keys=("name", "run"))
    print(scrub(json.dumps(line, default=str))[:900])


if __name__ == "__main__":
    main()
