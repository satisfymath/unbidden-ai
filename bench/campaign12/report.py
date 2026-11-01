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
        "| repo | run | mode | c1 proposals | c2 proposals | PRs on fork | merged | deploys seen | duplicates | blocks | spent | UI | chat analyze |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        f = r["facts"]
        c1 = f.get("cycle1", {}).get("counts", {})
        c2 = f.get("cycle2", {}).get("counts", {})
        pulls = f.get("fork_after_c2", {}).get("pulls") or []
        merged = sum(1 for p in pulls if p.get("merged_at"))
        prs_c1 = len(f.get("fork_after_c1", {}).get("pulls") or [])
        dup = "none" if len(pulls) == prs_c1 or len({p.get("head") for p in pulls}) == len(pulls) else "CHECK"
        deploys = (c2.get("events") or {}).get("operations.deployed", 0)
        ui = f.get("ui1", {})
        ok_ui = "ok" if ui.get("opened") and (ui.get("browser") or {}).get("ok") else "FAIL"
        an = (ui.get("chat_analyze") or {}).get("route") or {}
        lines.append(
            f"| {r['repo']} | {r['run']} | {f.get('mode_got')} | {len(c1.get('proposals', []))} | {len(c2.get('proposals', []))} "
            f"| {len(pulls)} | {merged} | {deploys} | {dup} | {len(r.get('blocks', []))} | {f.get('spent_usd')} | {ok_ui} "
            f"| {an.get('tier') or an.get('blocked', '')} |"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dirs", nargs="+")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    corpus = {r["name"]: r for r in yaml.safe_load(Path(args.corpus).read_text())["repos"]}
    a, b = load([Path(d) for d in args.dirs])
    lines = ["# Campaign 12: aggregate (generated by bench/campaign12/report.py)", "", "## Level A", ""]
    lines += level_a_summary(a, corpus) + level_a_table(a, corpus) + ["", "## Level B", ""] + level_b_table(b)
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
