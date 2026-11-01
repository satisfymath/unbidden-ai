"""Campaign 12, seeded scenarios: the product's mechanisms exercised on purpose, apart from natural findings.

    uv run python -m bench.campaign12.scenarios --out docs/bench/campaign12/scenarios [--only a,b]

Each scenario states what is done, what the product should show, and what was observed; exit codes alone decide
nothing. Deterministic scenarios need no model (US$0); the ones that do say so and run under `s12-pilot`. The
workspace is a clean clone of a small library of the corpus (humanize) in the campaign lab; scenario HOMEs are
throwaway and never touch the machine's ledger unless said.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from bench.campaign12.common import env, run, scrub, unbidden
from bench.campaign12.level_a import clone, key_from_machine

OUT: list[dict[str, Any]] = []
REPO = {
    "name": "humanize",
    "url": "https://github.com/python-humanize/humanize",
    "commit": "6b817b963dbb091b9ad20a746cb6a26653a93b95",
}


def record(name: str, expected: str, observed: dict[str, Any], verdict: str) -> None:
    OUT.append({"scenario": name, "expected": expected, "observed": observed, "verdict": verdict})
    print(json.dumps({"scenario": name, "verdict": verdict}, ensure_ascii=False), flush=True)


def fresh_workspace(e: dict[str, str], *, budget: str = "0", key: str | None = None) -> Path:
    repo_dir, _ = clone(REPO)
    stdin = (key if key is not None else key_from_machine()) + "\n"
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
            "--private-code",
            "allow",
            "--budget",
            budget,
            "--dashboard",
            "later",
            "--model-key-stdin",
            "--yes",
            "--json",
        ],
        cwd=repo_dir,
        env_=e,
        timeout_s=600,
        stdin=stdin,
    )
    return repo_dir


def scenario_home(name: str, *, verified_usd: float | None = None) -> dict[str, str]:
    """A throwaway HOME and ledger: nothing of the machine's credentials or budget is used."""
    home = Path(tempfile.mkdtemp(prefix=f"c12-scn-{name}-"))
    e = env("none", f"c12-scn-{name}")
    e.update(HOME=str(home), UNBIDDEN_HOME=str(home / ".unbidden"))
    e.pop("UNBIDDEN_ENVELOPE", None)
    if verified_usd is not None:
        run(
            "verified",
            [
                unbidden(),
                "spend",
                "--verified-balance",
                str(verified_usd),
                "--source",
                f"scenario {name}",
                "--reserve",
                "0",
            ],
            cwd=home,
            env_=e,
            timeout_s=60,
        )
        run("release", [unbidden(), "spend", "--release-reserve"], cwd=home, env_=e, timeout_s=60)
    return e


def s_credential_rejected() -> None:
    e = scenario_home("badkey", verified_usd=1.0)
    repo_dir = fresh_workspace(e, budget="1", key="sk-invalid-campaign-scenario-0000")
    doctor = run("doctor", [unbidden(), "doctor", "--json"], cwd=repo_dir, env_=e, timeout_s=300).json() or {}
    meta = next((c for c in doctor.get("checks", []) if c["check"] == "meta api"), {})
    chat = (
        run(
            "chat",
            [unbidden(), "chat", "--json", "¿Por qué no hay oportunidades y qué revisarías?"],
            cwd=repo_dir,
            env_=e,
            timeout_s=300,
        ).json()
        or {}
    )
    route = chat.get("route") or {}
    egress = run("egress", [unbidden(), "egress", "--json"], cwd=repo_dir, env_=e, timeout_s=120).json() or []
    record(
        "credential rejected",
        "doctor says the listing refuses the key; an analysis is refused or fails with the "
        "provider's status, never answered by rules as analysis; no key value in any output",
        {
            "doctor_meta": meta.get("detail"),
            "chat_planner": chat.get("planner"),
            "chat_blocked": route.get("blocked"),
            "chat_content": scrub(str(chat.get("content", "")))[:200],
            "egress_rows": len(egress),
            "key_leaked": "sk-invalid-campaign" in json.dumps(chat) + json.dumps(doctor),
        },
        "pass"
        if (route.get("blocked") or chat.get("planner") == "rule") and "sk-invalid-campaign" not in json.dumps(chat)
        else "fail",
    )
    shutil.rmtree(Path(e["HOME"]), ignore_errors=True)


def s_budget_exhausted() -> None:
    e = scenario_home("nobudget", verified_usd=0.0001)
    repo_dir = fresh_workspace(e, budget="1")
    chat = (
        run(
            "chat",
            [unbidden(), "chat", "--json", "¿Por qué no hay oportunidades y qué revisarías?"],
            cwd=repo_dir,
            env_=e,
            timeout_s=300,
        ).json()
        or {}
    )
    route = chat.get("route") or {}
    record(
        "budget exhausted (machine ledger)",
        "the call is refused before it is sent, with the ledger's reason and a hint",
        {"blocked": route.get("blocked"), "hint": route.get("hint"), "planner": chat.get("planner")},
        "pass" if route.get("blocked") and "refused" in str(route.get("blocked")) else "fail",
    )
    e2 = env("s12-pilot", "c12-scn-cap0")
    repo_dir2 = fresh_workspace(e2, budget="0")
    chat2 = (
        run(
            "chat",
            [unbidden(), "chat", "--json", "¿Por qué no hay oportunidades y qué revisarías primero?"],
            cwd=repo_dir2,
            env_=e2,
            timeout_s=300,
        ).json()
        or {}
    )
    route2 = chat2.get("route") or {}
    record(
        "budget exhausted (mandate cap 0)",
        "refused with the cap's reason; US$0 spent",
        {"blocked": route2.get("blocked"), "hint": route2.get("hint")},
        "pass" if route2.get("blocked") and "cap" in str(route2.get("blocked")) else "fail",
    )
    shutil.rmtree(Path(e["HOME"]), ignore_errors=True)


def s_docker_down() -> None:
    e = env("s12-pilot", "c12-scn-nodocker") | {"DOCKER_HOST": "tcp://127.0.0.1:1"}
    repo_dir = fresh_workspace(e)
    doctor = run("doctor", [unbidden(), "doctor", "--json"], cwd=repo_dir, env_=e, timeout_s=300)
    d = doctor.json() or {}
    docker = {
        c["check"]: (c["ok"], c["required"], c["detail"])
        for c in d.get("checks", [])
        if c["check"].startswith("docker")
    }
    scan = run("scan", [unbidden(), "scan", "--json"], cwd=repo_dir, env_=e, timeout_s=900)
    record(
        "Docker not available",
        "doctor fails the required docker checks and explains; scan records the problem instead of crashing",
        {
            "doctor_exit": doctor.code,
            "docker_checks": docker,
            "scan_exit": scan.code,
            "scan_problems": (scan.json() or {}).get("problems"),
            "scan_stderr": scrub(scan.stderr[-200:]),
        },
        "pass" if doctor.code != 0 and docker.get("docker", (True,))[0] is False else "fail",
    )


def s_second_start_and_crash() -> None:
    e = env("s12-pilot", "c12-scn-starts")
    repo_dir = fresh_workspace(e)
    procs = [
        subprocess.Popen(
            [unbidden(), "start", "--interval", "3600", "--json"],
            cwd=repo_dir,
            env=e,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outs = [p.communicate(timeout=120)[0] for p in procs]
    results = [json.loads(o) if o.strip().startswith("{") else {"raw": o[-200:]} for o in outs]
    started = sum(1 for r in results if r.get("started"))
    time.sleep(3)
    # agents of THIS workspace (other campaign runs may have their own): the lock names the owner; the process list
    # is kept for the record
    watchers = subprocess.run(["pgrep", "-f", "unbidden.cli watch"], capture_output=True, text=True).stdout.split()
    tree = (
        subprocess.run(
            ["ps", "-o", "pid=,ppid=,etime=,command=", "-p", ",".join(watchers)], capture_output=True, text=True
        )
        .stdout.strip()
        .splitlines()
        if watchers
        else []
    )
    status = run("status", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=60).json() or {}
    pid = (status.get("agent") or {}).get("pid")
    if pid:
        os.kill(int(pid), 9)
    time.sleep(2)
    after = run("status-after-crash", [unbidden(), "status", "--json"], cwd=repo_dir, env_=e, timeout_s=60).json() or {}
    restart = (
        run(
            "start-after-crash",
            [unbidden(), "start", "--interval", "3600", "--json"],
            cwd=repo_dir,
            env_=e,
            timeout_s=120,
        ).json()
        or {}
    )
    time.sleep(5)
    log = (repo_dir / ".unbidden" / "logs" / "agent.log").read_text(errors="replace")
    stop = run("stop", [unbidden(), "stop", "--json"], cwd=repo_dir, env_=e, timeout_s=120).json() or {}
    record(
        "two simultaneous starts, then a crash during a job",
        "exactly one agent starts (the other reports already running); after kill -9 status says stale with the job "
        "left running; the next start resumes it; stop is clean",
        {
            "started": started,
            "already": sum(1 for r in results if r.get("already")),
            "watch_processes_on_host": len(watchers),
            "owner_pid": (status.get("agent") or {}).get("pid"),
            "watch_tree": [scrub(t)[:160] for t in tree],
            "after_crash": after.get("agent"),
            "restart": restart.get("started"),
            "resumed_line": "resumed" in log,
            "stop": stop,
        },
        "pass"
        if started == 1 and (after.get("agent") or {}).get("stale") and restart.get("started") and stop.get("stopped")
        else "fail",
    )


def s_ui_port_busy_and_reopen() -> None:
    e = env("s12-pilot", "c12-scn-ui")
    repo_dir = fresh_workspace(e)
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 8871))
    holder.listen(1)
    try:
        ui = run("ui", [unbidden(), "ui", "--json", "--port", "8871"], cwd=repo_dir, env_=e, timeout_s=120).json() or {}
        info = json.loads((repo_dir / ".unbidden" / "ui.json").read_text())
        base, headers = f"http://127.0.0.1:{info['port']}", {"Authorization": f"Bearer {info['token']}"}
        sid = httpx.get(f"{base}/api/session", headers=headers, timeout=10).json()["sources"][0]["id"]
        with httpx.stream(
            "POST",
            f"{base}/api/ws/{sid}/chat",
            headers=headers,
            timeout=120,
            json={"content": "Añade una tabla con las oportunidades", "selected": [], "planner": "rule"},
        ) as r:
            for _ in r.iter_lines():
                pass
        before = httpx.get(f"{base}/api/ws/{sid}/presentation", headers=headers, timeout=30).json()
        run("ui-stop", [unbidden(), "ui", "--stop", "--json"], cwd=repo_dir, env_=e, timeout_s=60)
        ui2 = (
            run("ui2", [unbidden(), "ui", "--json", "--port", "8871"], cwd=repo_dir, env_=e, timeout_s=120).json() or {}
        )
        info2 = json.loads((repo_dir / ".unbidden" / "ui.json").read_text())
        base2, headers2 = f"http://127.0.0.1:{info2['port']}", {"Authorization": f"Bearer {info2['token']}"}
        after = httpx.get(f"{base2}/api/ws/{sid}/presentation", headers=headers2, timeout=30).json()
        run("ui-stop2", [unbidden(), "ui", "--stop", "--json"], cwd=repo_dir, env_=e, timeout_s=60)
        holder.getsockname()
        record(
            "UI port busy; close and reopen",
            "the dashboard takes the next free port without touching what holds 8871; after stop and reopen the "
            "same widgets are there; the empty opportunities table is a complete read of zero rows",
            {
                "port_taken": ui.get("port"),
                "reused_second_time": ui2.get("reused"),
                "port2": ui2.get("port"),
                "widgets_before": [w["id"] for w in before.get("widgets", [])],
                "widgets_after": [w["id"] for w in after.get("widgets", [])],
                "completeness": [w.get("provenance", {}).get("completeness") for w in after.get("widgets", [])],
            },
            "pass"
            if ui.get("port") not in (None, 8871)
            and [w["id"] for w in before.get("widgets", [])] == [w["id"] for w in after.get("widgets", [])]
            and len(after.get("widgets", [])) >= 1  # the layout persists across scenario runs (same source id)
            else "fail",
        )
    finally:
        holder.close()


def s_kill_switch() -> None:
    e = env("s12-pilot", "c12-scn-kill")
    repo_dir = fresh_workspace(e)
    run("kill", [unbidden(), "kill", "scenario"], cwd=repo_dir, env_=e, timeout_s=60)
    start = (
        run("start", [unbidden(), "start", "--interval", "15", "--json"], cwd=repo_dir, env_=e, timeout_s=120).json()
        or {}
    )
    time.sleep(8)
    log1 = (repo_dir / ".unbidden" / "logs" / "agent.log").read_text(errors="replace")
    run("ui", [unbidden(), "ui", "--json", "--port", "8872"], cwd=repo_dir, env_=e, timeout_s=120)
    info = json.loads((repo_dir / ".unbidden" / "ui.json").read_text())
    base, headers = f"http://127.0.0.1:{info['port']}", {"Authorization": f"Bearer {info['token']}"}
    sid = httpx.get(f"{base}/api/session", headers=headers, timeout=10).json()["sources"][0]["id"]
    summary = httpx.get(f"{base}/api/ws/{sid}/summary", headers=headers, timeout=30).json()
    resume = httpx.post(
        f"{base}/api/ws/{sid}/actions",
        headers=headers,
        timeout=30,
        json={"operation": "resume", "idempotency_key": "scn-resume"},
    ).json()
    time.sleep(40)  # two ticks of the loop (interval 15 s): a released agent should have worked
    log2 = (repo_dir / ".unbidden" / "logs" / "agent.log").read_text(errors="replace")
    run("ui-stop", [unbidden(), "ui", "--stop", "--json"], cwd=repo_dir, env_=e, timeout_s=60)
    stop = run("stop", [unbidden(), "stop", "--json"], cwd=repo_dir, env_=e, timeout_s=120).json() or {}
    record(
        "kill switch engaged before start; inspect and resume from the dashboard",
        "the agent starts but waits ('kill switch engaged'); the dashboard opens, shows the switch and releases it; "
        "the agent then works; stop is clean",
        {
            "started": start.get("started"),
            "waiting_logged": "kill switch engaged" in log1,
            "dashboard_kill_switch": summary["connection"].get("kill_switch"),
            "resume_effect": resume.get("effect"),
            "worked_after": ("observe" in log2.lower() or "checks" in log2.lower())
            and not (repo_dir / ".unbidden" / "KILL").exists(),
            "stop": stop.get("stopped"),
        },
        "pass"
        if start.get("started")
        and "kill switch engaged" in log1
        and summary["connection"].get("kill_switch")
        and resume.get("effect") == "done"
        and stop.get("stopped")
        else "fail",
    )


def s_partial_read() -> None:
    e = env("s12-pilot", "c12-scn-partial")
    repo_dir = fresh_workspace(e)
    run("scan", [unbidden(), "scan", "--json"], cwd=repo_dir, env_=e, timeout_s=900)
    run("ui", [unbidden(), "ui", "--json", "--port", "8873"], cwd=repo_dir, env_=e, timeout_s=120)
    info = json.loads((repo_dir / ".unbidden" / "ui.json").read_text())
    base, headers = f"http://127.0.0.1:{info['port']}", {"Authorization": f"Bearer {info['token']}"}
    sid = httpx.get(f"{base}/api/session", headers=headers, timeout=10).json()["sources"][0]["id"]
    full = httpx.post(f"{base}/api/ws/{sid}/data", headers=headers, timeout=30, json={"dataset": "events"}).json()
    partial = httpx.post(
        f"{base}/api/ws/{sid}/data", headers=headers, timeout=30, json={"dataset": "events", "transform": {"limit": 2}}
    ).json()
    missing = httpx.post(
        f"{base}/api/ws/{sid}/data",
        headers=headers,
        timeout=30,
        json={"dataset": "experiment.samples", "params": {"experiment_id": "exp_none"}},
    ).json()
    run("ui-stop", [unbidden(), "ui", "--stop", "--json"], cwd=repo_dir, env_=e, timeout_s=60)
    record(
        "partial read vs complete vs missing",
        "a limited read says partial with its limit; the whole collection says complete; an entity the record does "
        "not hold says missing",
        {
            "full": (full.get("provenance") or {}).get("completeness"),
            "full_rows": len(full.get("rows", [])),
            "partial": (partial.get("provenance") or {}).get("completeness"),
            "partial_limit": (partial.get("provenance") or {}).get("limit"),
            "missing": (missing.get("provenance") or {}).get("completeness"),
        },
        "pass"
        if (full.get("provenance") or {}).get("completeness") == "complete"
        and (partial.get("provenance") or {}).get("completeness") == "partial"
        and (missing.get("provenance") or {}).get("completeness") == "missing"
        else "fail",
    )


SCENARIOS = {
    "credential": s_credential_rejected,
    "budget": s_budget_exhausted,
    "docker": s_docker_down,
    "starts": s_second_start_and_crash,
    "ui": s_ui_port_busy_and_reopen,
    "kill": s_kill_switch,
    "partial": s_partial_read,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = {n for n in args.only.split(",") if n}
    for name, fn in SCENARIOS.items():
        if only and name not in only:
            continue
        try:
            fn()
        except Exception as exc:  # a scenario that breaks is a result too
            record(name, "see the scenario", {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}, "error")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scenarios.json").write_text(json.dumps(OUT, indent=1, ensure_ascii=False, default=str))
    print(json.dumps({s["scenario"]: s["verdict"] for s in OUT}, ensure_ascii=False))


if __name__ == "__main__":
    main()
