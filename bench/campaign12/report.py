# ruff: noqa: E501
"""Campaign 12 aggregate: the records of a phase into tables (per repository, per family, aggregate), with
numerators and denominators and Wilson 95% intervals for rates. Classes (dev / independent / frontier) and seeded
scenarios are never mixed.

    uv run python -m bench.campaign12.report docs/bench/campaign12/pilot [more dirs] --corpus bench/campaign12/corpus.yaml
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%, 95% CI {100 * lo:.0f}-{100 * hi:.0f}%)" if n else "0/0"


def load(dirs: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    a: list[dict[str, Any]] = []
    b: list[dict[str, Any]] = []
    for d in dirs:
        for f in sorted(d.glob("*/A.json")):
            a.append(json.loads(f.read_text()))
        for f in sorted(d.glob("*/B*.json")):
            b.append(json.loads(f.read_text()))
    return a, b


def level_a_table(records: list[dict[str, Any]], corpus: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "| repo | class | family | setup | doctor | checks | collected | image | opps | agent | ui | spent | wall s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        f = r["facts"]
        meta = corpus.get(r["repo"], {})
        ch = f.get("checks", {})
        life = f.get("lifecycle", {})
        agent_ok = all(life.get(k) for k in ("started", "second_start_refused", "stopped")) and not life.get(
            "kill_file"
        )
        image = ch.get("image_age") or {}
        lines.append(
            f"| {r['repo']} | {meta.get('class')} | {meta.get('family')} | {'ok' if f.get('setup', {}).get('ok') else 'FAIL'} "
            f"| {'ok' if f.get('doctor', {}).get('ok') else 'required missing'} | {ch.get('status')} | {ch.get('collected') or ''} "
            f"| {'built' if image.get('built_in_this_run') else ('cached' if image else '')} | {f.get('inbox', {}).get('total')} "
            f"| {'ok' if agent_ok else 'FAIL'} | {'ok' if f.get('ui', {}).get('opened') and f.get('ui', {}).get('session_ok') else 'FAIL'} "
            f"| {f.get('spent_usd')} | {round(sum(s['seconds'] for s in r['steps']) + (ch.get('waited_s') or 0))} |"
        )
    return lines


def level_a_summary(records: list[dict[str, Any]], corpus: dict[str, dict[str, Any]]) -> list[str]:
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_class[corpus.get(r["repo"], {}).get("class", "?")].append(r)
    out = []
    for cls, rs in by_class.items():
        n = len(rs)
        inside = [r for r in rs if corpus.get(r["repo"], {}).get("support") == "inside"]
        setup = sum(1 for r in rs if r["facts"].get("setup", {}).get("ok"))
        doctor = sum(1 for r in rs if r["facts"].get("doctor", {}).get("ok"))
        checks_any = [r for r in inside if r["facts"].get("checks", {}).get("status") in ("passed", "failed")]
        green = sum(1 for r in checks_any if r["facts"]["checks"]["status"] == "passed")
        project_fail = sum(1 for r in checks_any if r["facts"]["checks"]["status"] == "failed")
        infra = sum(1 for r in inside if r["facts"].get("checks", {}).get("status") in ("infra_failed", "blocked"))
        none = sum(
            1 for r in inside if r["facts"].get("checks", {}).get("status") in (None, "out_of_scope", "no_tests")
        )
        agent = sum(
            1
            for r in rs
            if all(r["facts"].get("lifecycle", {}).get(k) for k in ("started", "second_start_refused", "stopped"))
        )
        ui = sum(1 for r in rs if r["facts"].get("ui", {}).get("session_ok"))
        spent = round(sum(r["facts"].get("spent_usd") or 0 for r in rs), 4)
        out += [
            f"**{cls}** (n={n}; inside support {len(inside)})",
            f"- installations/onboardings completed: {rate(setup, n)}; doctor without a missing requirement: {rate(doctor, n)}",
            f"- checks executed (passed or failed, tests collected): {rate(len(checks_any), len(inside))} of those inside support; "
            f"green {green}, project failures {project_fail}, environment failures/blocked {infra}, not reached/no tests {none}",
            f"- agent start/second start refused/stop: {rate(agent, n)}; dashboard opened and answered: {rate(ui, n)}; spend US${spent}",
            "",
        ]
    return out


def level_b_table(records: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| repo | run | mode | c1 proposals | c2 proposals | agent PRs on copy | CI | merged | deploys seen | duplicates | blocks | spent | UI | chat analyze |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        f = r["facts"]
        c1 = f.get("cycle1", {}).get("counts", {})
        c2 = f.get("cycle2", {}).get("counts", {})
        pulls = _agent_pulls(f.get("fork_after_c2", {}))
        merged = sum(1 for p in pulls if p.get("merged_at"))
        ci = ",".join(_ci_of(p) for p in pulls) or "-"
        prs_c1 = len(_agent_pulls(f.get("fork_after_c1", {})))
        dup = "none" if len(pulls) == prs_c1 or len({p.get("head") for p in pulls}) == len(pulls) else "CHECK"
        deploys = (c2.get("events") or {}).get("operations.deployed", 0)
        ui = f.get("ui1", {})
        ok_ui = "ok" if ui.get("opened") and (ui.get("browser") or {}).get("ok") else "FAIL"
        an = (ui.get("chat_analyze") or {}).get("route") or {}
        lines.append(
            f"| {r['repo']} | {r['run']} | {f.get('mode_got')} | {len(c1.get('proposals', []))} | {len(c2.get('proposals', []))} "
            f"| {len(pulls)} | {ci} | {merged} | {deploys} | {dup} | {len(r.get('blocks', []))} | {f.get('spent_usd')} | {ok_ui} "
            f"| {an.get('tier') or an.get('blocked', '')} |"
        )
    return lines


AGENT = "satisfymath"  # the token's user: pull requests by anyone else (a bot) are not the agent's


def _agent_pulls(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        p
        for p in (state.get("pulls") or [])
        if str(p.get("head", "")).startswith("unbidden/") and p.get("user", AGENT) == AGENT
    ]


def _ci_of(pr: dict[str, Any]) -> str:
    """What CI did on the pull request's exact head: none, pending, green, red (or mixed)."""
    runs = pr.get("checks") or []
    if not runs:
        return "none"
    if any(r.get("status") != "completed" for r in runs):
        return "pending"
    concl = {r.get("conclusion") for r in runs}
    if concl <= {"success", "skipped", "neutral"}:
        return "green"
    return (
        "red" if "failure" in concl or "timed_out" in concl else f"other ({', '.join(sorted(str(c) for c in concl))})"
    )


def level_b_dimensions(records: list[dict[str, Any]], corpus: dict[str, dict[str, Any]]) -> list[str]:
    """The nine dimensions David asked to be reported apart, per class (development results are calibration, never
    independent evidence), with numerators and denominators over runs."""
    out: list[str] = []
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_class[corpus.get(r["repo"], {}).get("class", "?")].append(r)
    for cls in ("independent", "dev", "frontier", "?"):
        rs = by_class.get(cls)
        if not rs:
            continue
        n = len(rs)
        repos = sorted({r["repo"] for r in rs})
        setup = sum(1 for r in rs if (r["facts"].get("setup") or {}).get("ok"))
        doctor = sum(1 for r in rs if (r["facts"].get("doctor") or {}).get("ok"))
        autonomous = sum(1 for r in rs if r["facts"].get("mode_got") == "autonomous")
        with_opps = sum(
            1
            for r in rs
            if ((r["facts"].get("cycle2") or {}).get("counts") or {}).get("docs", {}).get("opportunities", 0) > 0
        )
        with_exps = sum(
            1
            for r in rs
            if ((r["facts"].get("cycle2") or {}).get("counts") or {}).get("docs", {}).get("experiments", 0) > 0
        )
        pulls = [p for r in rs for p in _agent_pulls(r["facts"].get("fork_after_c2") or {})]
        runs_with_pr = sum(1 for r in rs if _agent_pulls(r["facts"].get("fork_after_c2") or {}))
        ci = defaultdict(int)
        for p in pulls:
            ci[_ci_of(p)] += 1
        merged = [p for p in pulls if p.get("merged_at")]
        deployed = sum(
            ((r["facts"].get("cycle2") or {}).get("counts") or {}).get("events", {}).get("operations.deployed", 0)
            for r in rs
        )
        drills = sum(1 for r in rs if (r["facts"].get("mode") or {}).get("drill_code") == 0)
        lab_ok_after = sum(1 for r in rs if (r["facts"].get("lab_after_c2") or {}).get("health_status") == 200)
        labs_n = sum(1 for r in rs if r["facts"].get("lab"))
        ui_ok = sum(
            1
            for r in rs
            if (r["facts"].get("ui1") or {}).get("opened")
            and ((r["facts"].get("ui1") or {}).get("browser") or {}).get("ok")
        )
        chat_an = sum(
            1 for r in rs if ((r["facts"].get("ui1") or {}).get("chat_analyze") or {}).get("route", {}).get("tier")
        )
        c2_started = sum(1 for r in rs if (r["facts"].get("cycle2") or {}).get("started"))
        stopped = sum(1 for r in rs if not ((r["facts"].get("status_final") or {}).get("running")))
        dup = sum(
            1
            for r in rs
            if len(_agent_pulls(r["facts"].get("fork_after_c2") or {}))
            != len(_agent_pulls(r["facts"].get("fork_after_c1") or {}))
            and len({p["head"] for p in _agent_pulls(r["facts"].get("fork_after_c2") or {})})
            != len(_agent_pulls(r["facts"].get("fork_after_c2") or {}))
        )
        interventions = sum(1 for r in rs if r["facts"].get("intervention"))
        prep_min = round(sum(h.get("minutes", 0) for r in rs for h in r.get("human", [])), 1)
        bounds = sum(1 for r in rs for c in ("cycle1", "cycle2") if (r["facts"].get(c) or {}).get("bound_hit"))
        wall = sum(
            ((r["facts"].get("cycle1") or {}).get("waited_s", 0) + (r["facts"].get("cycle2") or {}).get("waited_s", 0))
            for r in rs
        )
        spent = round(sum(float(r["facts"].get("spent_usd") or 0) for r in rs), 4)
        calls = sum(int((r["facts"].get("run_spend") or {}).get("calls") or 0) for r in rs)
        blocks = sum(len(r.get("blocks", [])) for r in rs)
        note = " (calibration: not independent evidence)" if cls == "dev" else ""
        out += [
            f"### Level B, class **{cls}**{note}: {n} run(s) on {len(repos)} repositories ({', '.join(repos)})",
            "",
            f"1. Installation and onboarding: setup applied {rate(setup, n)}; doctor without a missing requirement {rate(doctor, n)}; autonomous granted by the product {rate(autonomous, n)} (drill passed {drills}/{labs_n} lab runs).",
            "2. Checks reproduced and coverage: Level A (same pins) is the record; a Level B cycle starts experiments only after them.",
            f"3. Discovery and experiments: runs with ≥1 opportunity {rate(with_opps, n)}; with ≥1 experiment {rate(with_exps, n)}.",
            f"4. Pull requests published by the agent: {len(pulls)} in {runs_with_pr}/{n} runs (duplicated effects between cycles: {dup}).",
            "5. CI observed on the exact head of those pull requests: "
            + (", ".join(f"{k} {v}" for k, v in sorted(ci.items())) or "no pull request")
            + f" / {len(pulls)}.",
            f"6. Merges effective (on the copy, by the product): {len(merged)}/{len(pulls)} pull requests.",
            f"7. Deploys and verified effects: `operations.deployed` events {deployed} (the drill's deploy included); lab healthy after the second cycle {lab_ok_after}/{labs_n}.",
            f"8. UI and recovery: dashboard served and the browser walk passed {rate(ui_ok, n)}; a routed chat analysis {rate(chat_an, n)}; second start after stop {rate(c2_started, n)}; agent stopped at the end {rate(stopped, n)}.",
            f"9. Interventions, latency and cost: interventions during autonomous runs {interventions} (any ends the attempt); human preparation {prep_min} min counted apart; cycles that hit their bound {bounds}; agent wall time {round(wall / 60)} min; {calls} model calls, US${spent} (ledger, list price); blocks recorded {blocks}.",
            "",
        ]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dirs", nargs="+")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    corpus = {r["name"]: r for r in yaml.safe_load(Path(args.corpus).read_text())["repos"]}
    a, b = load([Path(d) for d in args.dirs])
    lines = ["# Campaign 12: aggregate (generated by bench/campaign12/report.py)", "", "## Level A", ""]
    lines += (
        level_a_summary(a, corpus)
        + level_a_table(a, corpus)
        + ["", "## Level B", ""]
        + level_b_dimensions(b, corpus)
        + level_b_table(b)
    )
    scn = Path(args.dirs[0]).parent / "scenarios" / "scenarios.json"
    if scn.exists():
        lines += ["", "## Seeded scenarios (apart from natural findings)", "", "| scenario | verdict |", "|---|---|"]
        lines += [f"| {s['scenario']} | {s['verdict']} |" for s in json.loads(scn.read_text())]
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
