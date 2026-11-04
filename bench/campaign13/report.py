# ruff: noqa: E501
"""Campaign 13 aggregate: the records of a phase into tables (per repository, per family, aggregate), with
numerators and denominators and Wilson 95% intervals for rates. Classes (dev / independent / frontier) and seeded
scenarios are never mixed. Everything is regenerated from the records only (A.json, B<n>.json, verify*.json and the
campaign-12 baseline file); nothing is typed in.

    uv run python -m bench.campaign13.report docs/bench/campaign13/final --corpus bench/campaign13/corpus.yaml \
        [--baseline bench/campaign13/baseline-c12.json] [--out docs/bench/campaign13/final/REPORT-aggregate.md]

Tables: Level A per class and per repository; Level B's nine dimensions per class; one joined row per repository
(Level A and B together: checks, opportunities by class, experiments, proposals, pull requests, CI, merges, deploys,
the highest evidence level with its criteria, the independent verification, spend, cost per pull request, time to
the first pull request, the questions answered and by which rule); and the comparison with campaign 12 by dimension.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
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


def load_verify(dirs: list[Path]) -> list[dict[str, Any]]:
    """verify.py's records: `<dir>/<repo>/verify*.json` or `<dir>/verify/*.json`."""
    out: list[dict[str, Any]] = []
    for d in dirs:
        for f in sorted({*d.glob("*/verify*.json"), *d.glob("verify/*.json")}):
            data = json.loads(f.read_text())
            if isinstance(data, dict) and data.get("slug"):
                out.append(data)
    return out


def _could_not_run(ch: dict[str, Any]) -> str:
    cnr = ch.get("could_not_run") or {}
    return f"{cnr['tests']} ({', '.join(cnr.get('lacks') or [])})" if cnr.get("tests") else ""


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
            f"| {ch.get('failed') if ch.get('failed') is not None else ''} | {_could_not_run(ch)} "
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
        pulls = _agent_pulls(f.get("fork_after_c2", {}), r.get("started_at"))
        merged = sum(1 for p in pulls if p.get("merged_at"))
        ci = ",".join(_ci_of(p) for p in pulls) or "-"
        prs_c1 = len(_agent_pulls(f.get("fork_after_c1", {}), r.get("started_at")))
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


def _agent_pulls(state: dict[str, Any], since: str | None = None) -> list[dict[str, Any]]:
    """The agent's pull requests on the copy; with `since` (the run's start, ISO), only those created in the run:
    the copy keeps closed and merged pull requests of earlier runs (a merged one cannot be closed by the restore)."""
    return [
        p
        for p in (state.get("pulls") or [])
        if str(p.get("head", "")).startswith("unbidden/")
        and p.get("user", AGENT) == AGENT
        and (since is None or _utc(p.get("created_at")) >= _utc(since))
    ]


def _utc(stamp: str | None) -> str:
    """ISO stamps compared as UTC text (records write the local offset, GitHub writes Z)."""
    from datetime import datetime

    if not stamp:
        return ""
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC).isoformat()


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
        pulls = [p for r in rs for p in _agent_pulls(r["facts"].get("fork_after_c2") or {}, r.get("started_at"))]
        runs_with_pr = sum(1 for r in rs if _agent_pulls(r["facts"].get("fork_after_c2") or {}, r.get("started_at")))
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
            if len(_agent_pulls(r["facts"].get("fork_after_c2") or {}, r.get("started_at")))
            != len(_agent_pulls(r["facts"].get("fork_after_c1") or {}, r.get("started_at")))
            and len({p["head"] for p in _agent_pulls(r["facts"].get("fork_after_c2") or {}, r.get("started_at"))})
            != len(_agent_pulls(r["facts"].get("fork_after_c2") or {}, r.get("started_at")))
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


def _last_counts(f: dict[str, Any]) -> dict[str, Any]:
    for c in ("cycle2", "cycle1"):
        counts = (f.get(c) or {}).get("counts") or {}
        if counts and "error" not in counts:
            return counts
    return {}


def _criteria_name(criteria: Any) -> str:
    if not isinstance(criteria, dict):
        return ""
    return str(criteria.get("criteria_version") or criteria.get("version") or "unversioned")


def _level(counts: dict[str, Any]) -> str:
    top = int(counts.get("level_max") or 0)
    if not top:
        return "-"
    crit = _criteria_name(counts.get("level_max_criteria"))
    outcome = counts.get("level_max_outcome") or {}
    if top >= 5 and outcome:
        return f"L{top} ({crit}; {outcome.get('result')} after deploy {outcome.get('deploy')})"
    return f"L{top}" + (f" ({crit})" if crit else "")


def _minutes_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    a = datetime.fromisoformat(start.replace("Z", "+00:00"))
    b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return round((b - a).total_seconds() / 60, 1)


def _slug_matches(slug: str, name: str) -> bool:
    repo = slug.rsplit("/", 1)[-1]
    return repo == name or repo.endswith(f"-{name}")


def joined_row(
    name: str, meta: dict[str, Any], a: dict[str, Any] | None, b: dict[str, Any] | None, verify: list[dict[str, Any]]
) -> dict[str, Any]:
    """One repository's (or one Level B run's) row, from its records only."""
    fa = (a or {}).get("facts") or {}
    fb = (b or {}).get("facts") or {}
    checks = fb.get("checks") or fa.get("checks") or {}
    counts = _last_counts(fb)
    if counts.get("opportunities") is not None:
        opps = Counter(str(o.get("category") or o.get("source") or "?") for o in counts.get("opportunities") or [])
    else:
        opps = Counter((fa.get("inbox") or {}).get("by_source") or {})
    pulls = _agent_pulls(fb.get("fork_after_c2") or {}, (b or {}).get("started_at")) if b else []
    urls = [f"#{p.get('number')}" for p in pulls]
    numbers = {p.get("number") for p in pulls}
    verdicts = [
        v.get("verdict") for v in verify if _slug_matches(str(v.get("slug")), name) and v.get("number") in numbers
    ]
    spent = round(float(fa.get("spent_usd") or 0) + float(fb.get("spent_usd") or 0), 4)
    first = min((str(p.get("created_at")) for p in pulls if p.get("created_at")), default=None)
    asks = fb.get("asks_answered") or []
    rules = Counter(str(x.get("rule")) for x in asks)
    proposals = counts.get("proposals") or []
    return {
        "name": name,
        "run": (b or {}).get("run") or "A",
        "class": meta.get("class"),
        "family": meta.get("family"),
        "mode": (fb.get("autonomy") or {}).get("mode") or fb.get("mode_got") or ("-" if b else "A only"),
        "checks": checks.get("status"),
        "collected": checks.get("collected"),
        "opportunities": dict(sorted(opps.items())),
        "experiments": counts.get("experiments", (counts.get("docs") or {}).get("experiments")) if b else None,
        "proposals": [f"L{p.get('evidence_level')}" for p in proposals],
        "pulls": urls,
        "ci": [_ci_of(p) for p in pulls],
        "merged": sum(1 for p in pulls if p.get("merged_at")),
        "deploys": (counts.get("events") or {}).get("operations.deployed", 0) if b else None,
        "level": _level(counts) if b else "-",
        "verify": verdicts,
        "spent_usd": spent,
        "cost_per_pr": round(spent / len(pulls), 4) if pulls else None,
        "first_pr_min": _minutes_between((b or {}).get("started_at"), first) if first else None,
        "asks": len(asks),
        "ask_rules": dict(sorted(rules.items())),
        "export": (fb.get("export") or {}).get("why") or ("ok" if (fb.get("export") or {}).get("ok") else "-")
        if b
        else "-",
    }


def joined_rows(
    a: list[dict[str, Any]], b: list[dict[str, Any]], verify: list[dict[str, Any]], corpus: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every corpus repository at least once (in corpus order), one row per Level B run where there are runs."""
    a_by = {r["repo"]: r for r in a}
    b_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in b:
        b_by[r["repo"]].append(r)
    names = list(corpus) + sorted({*a_by, *b_by} - set(corpus))
    rows: list[dict[str, Any]] = []
    for name in names:
        runs = sorted(b_by.get(name, []), key=lambda r: str(r.get("run")))
        for rb in runs or [None]:
            rows.append(joined_row(name, corpus.get(name, {}), a_by.get(name), rb, verify))
    return rows


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return ", ".join(f"{k} {v}" for k, v in value.items()) or "-"
    if isinstance(value, list):
        return ",".join(str(v) for v in value) or "-"
    return str(value)


JOINED = [
    ("repo", "name"), ("run", "run"), ("class", "class"), ("family", "family"), ("mode", "mode"),
    ("checks", "checks"), ("collected", "collected"), ("opportunities by class", "opportunities"),
    ("experiments", "experiments"), ("proposals", "proposals"), ("PRs", "pulls"), ("CI", "ci"), ("merged", "merged"),
    ("deploys", "deploys"), ("highest level (criteria)", "level"), ("verify.py", "verify"), ("spent US$", "spent_usd"),
    ("US$/PR", "cost_per_pr"), ("first PR (min)", "first_pr_min"), ("asks", "asks"), ("ask rules", "ask_rules"),
    ("export", "export"),
]  # fmt: skip


def joined_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["| " + " | ".join(h for h, _ in JOINED) + " |", "|" + "---|" * len(JOINED)]
    lines += ["| " + " | ".join(_cell(r.get(k)).replace("|", "/") for _, k in JOINED) + " |" for r in rows]
    return lines


def campaign13_figures(
    a: list[dict[str, Any]], b: list[dict[str, Any]], verify: list[dict[str, Any]], corpus: dict[str, dict[str, Any]]
) -> dict[str, dict[str, tuple[int, int]]]:
    """Campaign 13's (k, n) per dimension and class, for the same dimensions as the campaign-12 baseline."""
    cls = lambda r: corpus.get(r["repo"], {}).get("class", "?")  # noqa: E731
    out: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)

    def put(dim: str, rows: list[dict[str, Any]], ok: Any) -> None:
        by: dict[str, list[bool]] = defaultdict(list)
        for r in rows:
            by[cls(r)].append(bool(ok(r)))
        for c, v in by.items():
            out[dim][c] = (sum(v), len(v))

    life = ("started", "second_start_refused", "stopped")
    put("setup applied (Level A)", a, lambda r: (r["facts"].get("setup") or {}).get("ok"))
    put("doctor without a missing requirement (Level A)", a, lambda r: (r["facts"].get("doctor") or {}).get("ok"))
    put("start / second start refused / stop (Level A)", a,
        lambda r: all((r["facts"].get("lifecycle") or {}).get(k) for k in life))  # fmt: skip
    # checks over every repository: Level A where it ran, else the Level B record's baseline
    by_repo = {r["repo"]: r for r in b} | {r["repo"]: r for r in a}
    put("checks executed, tests collected (Level A)", list(by_repo.values()),
        lambda r: (r["facts"].get("checks") or {}).get("status") in ("passed", "failed"))  # fmt: skip
    put(
        "Level B runs with >=1 opportunity",
        b,
        lambda r: (_last_counts(r["facts"]).get("docs") or {}).get("opportunities", 0) > 0,
    )
    put(
        "Level B runs with >=1 experiment",
        b,
        lambda r: (_last_counts(r["facts"]).get("docs") or {}).get("experiments", 0) > 0,
    )
    put(
        "Level B runs with a pull request",
        b,
        lambda r: _agent_pulls(r["facts"].get("fork_after_c2") or {}, r.get("started_at")),
    )
    pulls = [(r, p) for r in b for p in _agent_pulls(r["facts"].get("fork_after_c2") or {}, r.get("started_at"))]
    pr_rows = [{"repo": r["repo"], "pr": p} for r, p in pulls]
    put("pull requests green on the exact head", pr_rows, lambda x: _ci_of(x["pr"]) == "green")
    put("pull requests merged by the product", pr_rows, lambda x: x["pr"].get("merged_at"))
    put("pull requests verified independently", pr_rows, lambda x: any(
        v.get("verdict") == "verified" and v.get("number") == x["pr"].get("number") and _slug_matches(str(v.get("slug")), x["repo"])
        for v in verify))  # fmt: skip
    put(
        "Level B runs with a verified live effect (L5)",
        b,
        lambda r: int(_last_counts(r["facts"]).get("level_max") or 0) >= 5,
    )
    return out


def comparison(
    baseline: dict[str, Any], figures: dict[str, dict[str, tuple[int, int]]], b: list[dict[str, Any]]
) -> list[str]:
    """Campaign 13 beside campaign 12, dimension by dimension and class by class, each with its Wilson 95% interval
    and where the campaign-12 figure comes from. A dimension or class one campaign lacks is said, never filled."""
    lines = [
        f"Campaign 12 figures from `{baseline.get('source', '?')}`" if baseline else "No campaign-12 baseline given.",
        "",
        "| dimension | class | campaign 12 | campaign 13 | campaign-12 source |",
        "|---|---|---|---|---|",
    ]
    dims = baseline.get("dimensions") or {}
    for dim in list(dims) + [d for d in figures if d not in dims]:
        base = (dims.get(dim) or {}).get("by_class") or {}
        now = figures.get(dim) or {}
        for c in ("dev", "independent", "frontier"):
            if c not in base and c not in now:
                continue
            old = rate(*base[c]) if c in base else "not measured"
            new = rate(*now[c]) if c in now else "no record"
            lines.append(f"| {dim} | {c} | {old} | {new} | {(dims.get(dim) or {}).get('where', '-')} |")
    spend = baseline.get("spend") or {}
    total = round(sum(float(r["facts"].get("spent_usd") or 0) for r in b), 4)
    lines += [
        "",
        f"Level B spend: campaign 12 US${spend.get('level_b_usd', '?')} over {spend.get('level_b_runs', '?')} runs "
        f"({spend.get('where', '-')}); campaign 13 US${total} over {len(b)} runs (ledger by run tag).",
    ]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dirs", nargs="+")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out")
    parser.add_argument("--baseline", default=str(Path(__file__).with_name("baseline-c12.json")),
                        help="campaign 12's figures by dimension (JSON); '' for none")  # fmt: skip
    args = parser.parse_args()
    corpus = {r["name"]: r for r in yaml.safe_load(Path(args.corpus).read_text())["repos"]}
    dirs = [Path(d) for d in args.dirs]
    a, b = load(dirs)
    verify = load_verify(dirs)
    baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else {}
    lines = ["# Campaign 13: aggregate (generated by bench/campaign13/report.py)", "", "## Level A", ""]
    lines += (
        level_a_summary(a, corpus)
        + level_a_table(a, corpus)
        + ["", "## Level B", ""]
        + level_b_dimensions(b, corpus)
        + level_b_table(b)
        + ["", "## Per repository, Level A and B joined", ""]
        + joined_table(joined_rows(a, b, verify, corpus))
        + ["", "## Campaign 13 against campaign 12, by dimension", ""]
        + comparison(baseline, campaign13_figures(a, b, verify, corpus), b)
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
