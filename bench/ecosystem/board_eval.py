"""Measure the page goal: perception apart from repair, three observation methods on equal terms.

    uv run python -m bench.ecosystem.board_eval perception <worktree> --set dev --out DIR [--methods ...] [--reps N]
    uv run python -m bench.ecosystem.board_eval cycle <worktree> --set dev --out DIR [--methods ...]

The harness prepares and measures; it never tells the agent the case, the culprit file or the expected patch.

*Perception*: for each state, the lab is reset to it; the checker (`board_check`, model-free) records which rows a
person sees wrongly; the agent's scanner scans the page once; that same scan and the same expected values (the
truth's numbers, as a complete read gives them) go to each method: `dom`, `vision` (+ screenshots), `vision_sam`
(+ SAM regions). Scored per method: detection, rows named (precision and recall against the checker's rows), cause
localization (the stated cause names the culprit, by a rubric fixed per case before any run), false alarms on
healthy states, unreadable answers, latency and cost.

*Cycle*: for each case and method, from a reset lab and a fresh workspace, the real cycle (`unbidden watch --once`)
twice; then the checker. Scored: goal completed (checker verified), false verification (the agent said fixed or
fine, the checker did not verify), regressions (checker problems the case did not have), unnecessary changes (a
commit on a healthy board, or in the second cycle), interventions, model calls, latency and spend.
Code and harness come from the same worktree; records keep its commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from bench.ecosystem import board_check, board_lab

LAB = Path.home() / "unbidden-lab"
FIELDS = ("quantity", "reserved", "incoming")
# name: (case, variants, seed, bins, cause rubric: a regex the stated cause must match to localize the culprit)
SETS: dict[str, dict[str, tuple[str, list[str], int, int, str]]] = {
    "dev": {
        "healthy": ("healthy", [], 5_2026, 24, ""),
        "healthy-dark": ("healthy", ["dark"], 5_2026, 24, ""),
        "healthy-red-zone": ("healthy", ["red_zone"], 5_2026, 24, ""),
        "healthy-red-text": ("healthy", ["red_text"], 5_2026, 24, ""),
        "healthy-state-first": ("healthy", ["state_first", "big_badges"], 5_2026, 24, ""),
        "healthy-by-shortfall": ("healthy", ["by_shortfall"], 5_2026, 24, ""),
        "overlay": ("overlay", [], 5_2026, 24, r"summary|footer|fixed"),
        "overlay-reordered": ("overlay", ["by_shortfall"], 5_2026, 24, r"summary|footer|fixed"),
        "overlay-partial": ("overlay_partial", [], 5_2026, 24, r"help|aside|fixed|panel"),
        "overlay-partial-big": ("overlay_partial", ["big_badges"], 5_2026, 24, r"help|aside|fixed|panel"),
        "formula": ("formula", [], 5_2026, 24, r"reserved"),
        "formula-state-first": ("formula", ["state_first"], 5_2026, 24, r"reserved"),
        "style": ("style", [], 5_2026, 24, r"badge|short|colou?r|green|style"),
        "style-red-zone": ("style", ["red_zone"], 5_2026, 24, r"badge|short|colou?r|green|style"),
    },
    # Evaluation B (stage 5): other data (seed, 36 bins), other designs, other defects. Fixed before it ran.
    "eval": {
        "e-healthy-grid": ("healthy", ["grid"], 9_3131, 36, ""),
        "e-healthy-brand": ("healthy", ["brand"], 9_3131, 36, ""),
        "e-healthy-compact": ("healthy", ["compact", "by_shortfall"], 9_3131, 36, ""),
        "e-shifted": ("shifted", [], 9_3131, 36, r"top|position|relative|offset|shift"),
        "e-shifted-grid": ("shifted", ["grid"], 9_3131, 36, r"top|position|relative|offset|shift"),
        "e-faded": ("faded", ["brand"], 9_3131, 36, r"opacity|transparen|fade"),
        "e-banner": ("banner", [], 9_3131, 36, r"notice|banner|absolute|stocktake"),
        "e-banner-compact": ("banner", ["compact"], 9_3131, 36, r"notice|banner|absolute|stocktake"),
        "e-window": ("window", [], 9_3131, 36, r"30|window|interval|days"),
        "e-wording": ("wording", ["grid"], 9_3131, 36, r"SHORT|text|label|word"),
    },
    "eval-cycle": {
        "e-healthy-brand": ("healthy", ["brand"], 9_3131, 36, ""),
        "e-shifted-grid": ("shifted", ["grid"], 9_3131, 36, r"top|position|relative|offset|shift"),
        "e-faded": ("faded", ["brand"], 9_3131, 36, r"opacity|transparen|fade"),
        "e-banner": ("banner", [], 9_3131, 36, r"notice|banner|absolute|stocktake"),
        "e-window": ("window", [], 9_3131, 36, r"30|window|interval|days"),
    },
    "dev-cycle": {
        "healthy": ("healthy", [], 5_2026, 24, ""),
        "overlay": ("overlay", [], 5_2026, 24, r"summary|footer|fixed"),
        "overlay-partial": ("overlay_partial", [], 5_2026, 24, r"help|aside|fixed|panel"),
        "formula": ("formula", [], 5_2026, 24, r"reserved"),
        "style": ("style", [], 5_2026, 24, r"badge|short|colou?r|green|style"),
    },
}


def wrong_rows(verdict: dict[str, Any]) -> list[str]:
    """Rows a person sees wrongly, by the checker."""
    out = set(verdict["false_flags"]) | (set(verdict["short"]) - set(verdict["flagged"]))
    out |= {
        b for b, j in verdict["bins"].items() if not j.get("numbers_right", True) or not j.get("amount_right", True)
    }
    return sorted(out)


def prepare(name: str, spec: tuple[str, list[str], int, int, str], out: Path) -> dict[str, Any]:
    case, variants, seed, bins, _ = spec
    board_lab.reset(LAB, case, variants, seed, bins)
    verdict = board_check.check(LAB, out / "checker-before")
    return {"state": name, "case": case, "variants": variants, "wrong": wrong_rows(verdict),
            "healthy": verdict["verified"]}  # fmt: skip


def workspace(worktree: Path, policy: str, perception: str) -> Path:
    subprocess.run(
        ["uv", "run", "python", "-m", "bench.ecosystem.board_workspace", str(worktree), "--policy", policy,
         "--perception", perception],
        cwd=worktree, check=True, capture_output=True,
    )  # fmt: skip
    return board_lab.repo_dir(LAB)


def score_found(found: list[dict[str, Any]], wrong: list[str]) -> dict[str, Any]:
    named = sorted({str(d["key"]) for d in found})
    hit = sorted(set(named) & set(wrong))
    return {
        "named": named, "true_rows": hit, "extra_rows": sorted(set(named) - set(wrong)),
        "missed_rows": sorted(set(wrong) - set(named)), "detected": bool(named) if wrong else None,
        "false_alarm": bool(named) if not wrong else None,
        "precision": round(len(hit) / len(named), 3) if named else None,
        "recall": round(len(hit) / len(wrong), 3) if wrong else None,
    }  # fmt: skip


async def _perceive_all(worktree: Path, methods: list[str], scan_dir: Path, want: dict[str, Any]) -> list[Any]:
    from unbidden.director.presentation import perceive
    from unbidden.lab.ui import scan
    from unbidden.runtime import Runtime
    from unbidden.workspace import Workspace

    runtime = Runtime.open(Workspace.find(board_lab.repo_dir(LAB)))
    mandate = runtime.workspace.mandate()
    goal = mandate.goals[0]
    seen = scan(board_lab.URL, scan_dir)
    results = []
    for method in methods:
        started = time.monotonic()
        try:
            found = await perceive(runtime.brain, runtime.store, mandate, goal, seen, want, method, source="synthetic")
        except Exception as exc:  # an unusable answer or a refused call is a result, kept
            found = {"discrepancies": [], "cause": "", "error": f"{type(exc).__name__}: {exc}"[:300]}
        found["wall_s"] = round(time.monotonic() - started, 2)
        results.append(found)
    return [seen.digests(), results]


def perception(worktree: Path, states: dict[str, Any], methods: list[str], out: Path, reps: int, policy: str) -> None:
    rows = []
    for name, spec in states.items():
        for rep in range(1, reps + 1):
            where = out / f"{name}-r{rep}"
            where.mkdir(parents=True, exist_ok=True)
            prepared = prepare(name, spec, where)
            workspace(worktree, policy, "vision_sam")  # screenshots allowed; each method decides what it sends
            # The values a complete read of the two sources gives (the fields the agent's own plan reads).
            truth, stock = board_check.truth(LAB), board_lab.baseline(LAB)["bins"]
            want = {
                b: {"fields": {"picks_7d": t["picks"], **{f: stock[b][f] for f in FIELDS}},
                    "value": float(t["picks"] - t["supply"]), "flag": t["shortfall"] > 0}
                for b, t in truth.items()
            }  # fmt: skip
            digests, results = asyncio.run(_perceive_all(worktree, methods, where / "scan", want))
            for method, found in zip(methods, results, strict=True):
                scored = score_found(found.get("discrepancies", []), prepared["wrong"])
                rubric = spec[4]
                localized = bool(rubric and re.search(rubric, found.get("cause", ""), re.IGNORECASE)) if prepared[
                    "wrong"] else None  # fmt: skip
                row = {**prepared, "rep": rep, "method": method, **scored, "cause": found.get("cause"),
                       "cause_localized": localized, "error": found.get("error"), "model": found.get("model"),
                       "sam": found.get("sam"), "wall_s": found.get("wall_s"), "screenshots": digests}  # fmt: skip
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("state", "rep", "method", "detected", "false_alarm", "precision",
                                                      "recall", "cause_localized", "wall_s")}), flush=True)  # fmt: skip
            (out / "perception.json").write_text(json.dumps(rows, indent=1))


def _state(repo: Path) -> dict[str, Any]:
    from unbidden.contracts.llm import ModelRun
    from unbidden.director.goals import GoalRun
    from unbidden.store import Store

    store = Store(repo / ".unbidden" / "state.db")
    runs = store.list("goal_runs", GoalRun)
    models = store.list("model_runs", ModelRun)
    return {
        "goal_runs": [{"status": r.status, "note": (r.notes or [""])[-1][:300], "evidence": r.evidence} for r in runs],
        "model_runs": [
            {
                "purpose": m.purpose,
                "model": m.model,
                "tier": m.tier.value,
                "ok": m.ok,
                "usd": m.cost.usd_remote,
                "route": m.route_reason,
            }
            for m in models
        ],
    }


def cycle(worktree: Path, states: dict[str, Any], methods: list[str], out: Path, policy: str) -> None:
    rows = []
    for name, spec in states.items():
        for method in methods:
            where = out / f"{name}-{method}"
            where.mkdir(parents=True, exist_ok=True)
            prepared = prepare(name, spec, where)
            repo = workspace(worktree, policy, method)
            base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                                  check=True).stdout.strip()  # fmt: skip
            logs, started = [], time.monotonic()
            for _ in range(2):
                ran = subprocess.run(["uv", "run", "--project", str(worktree), "unbidden", "watch", "--once"],
                                     cwd=repo, capture_output=True, text=True, timeout=3600)  # fmt: skip
                logs.append((ran.stdout + ran.stderr)[-6000:])
            wall = round(time.monotonic() - started, 1)
            after = board_check.check(LAB, where / "checker-after")
            commits = subprocess.run(["git", "-C", str(repo), "log", "--format=%h %s", f"{base}..HEAD"],
                                     capture_output=True, text=True, check=False).stdout.splitlines()  # fmt: skip
            state = _state(repo)
            page_runs = [r for r in state["goal_runs"] if r["status"].startswith("page_")]
            final = page_runs[-1]["status"] if page_runs else (state["goal_runs"][-1]["status"] if state["goal_runs"]
                                                                else "none")  # fmt: skip
            agent_says_good = bool(page_runs) and page_runs[-1]["status"] in ("page_ok", "page_fixed")
            first_fix = next((i for i, r in enumerate(page_runs) if r["status"] == "page_fixed"), None)
            later_commit = first_fix is not None and len(commits) > sum(
                len([a for a in r["evidence"].get("attempts", []) if a.get("commit")])
                for r in page_runs[: first_fix + 1]
            )
            regressions = sorted(set(wrong_rows(after)) - set(prepared["wrong"]))
            row = {
                **prepared, "method": method, "policy": policy, "verified": after["verified"],
                "agent_final": final, "agent_says_good": agent_says_good,
                "false_verification": agent_says_good and not after["verified"],
                "regressions": regressions, "preserved": after["preserved"],
                "commits": commits, "unnecessary_change": (prepared["healthy"] and bool(commits)) or later_commit,
                "interventions": 0, "wall_s": wall,
                "model_calls": len(state["model_runs"]), "usd": round(sum(m["usd"] for m in state["model_runs"]), 4),
                "models": sorted({m["model"] for m in state["model_runs"]}),
                "sam_calls": sum(len(r["evidence"].get("before", {}).get("sam", []) or []) for r in page_runs),
                "problems_after": after["problems"][:5],
            }  # fmt: skip
            (where / "state.json").write_text(json.dumps(state, indent=1, default=str))
            (where / "logs.txt").write_text("\n\n---\n\n".join(logs))
            rows.append(row)
            shown = ("state", "method", "verified", "agent_final", "false_verification", "unnecessary_change",
                     "model_calls", "usd", "wall_s")  # fmt: skip
            print(json.dumps({k: row[k] for k in shown}), flush=True)
            (out / "cycle.json").write_text(json.dumps(rows, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["perception", "cycle"])
    parser.add_argument("worktree")
    parser.add_argument("--set", required=True, choices=sorted(SETS))
    parser.add_argument("--states", help="comma-separated subset")
    parser.add_argument("--methods", default="dom,vision,vision_sam")
    parser.add_argument("--policy", default="spark", choices=["local", "spark", "wonder"])
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    worktree, out = Path(args.worktree).expanduser(), Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    states = SETS[args.set]
    if args.states:
        states = {k: v for k, v in states.items() if k in args.states.split(",")}
    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()  # fmt: skip
    (out / "run.json").write_text(json.dumps({"mode": args.mode, "set": args.set, "states": list(states),
                                              "methods": args.methods, "policy": args.policy, "reps": args.reps,
                                              "commit": commit}, indent=1))  # fmt: skip
    methods = args.methods.split(",")
    if args.mode == "perception":
        perception(worktree, states, methods, out, args.reps, args.policy)
    else:
        cycle(worktree, states, methods, out, args.policy)


if __name__ == "__main__":
    main()
