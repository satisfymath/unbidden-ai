"""The harness's checker for the restock board goal: model-free, independent of the board's code and of the agent's.

    uv run python -m bench.ecosystem.board_check [--out DIR]

Truth: the harness's own SQL on `boardpicks` and its own read of the board's Depot (never the board's formula).
Page: `board_check_page.py` in a Playwright container on the board's compose network. The rules are amendment 1 of
`docs/bench/2026-10-28-multimodal-objective.md`: flagged = bound to its row, legible, a red alert (computed style
and screenshot pixels), at most 10 % occluded at some scroll position; every bin once, numbers right; inventory and
history untouched. Writes check.json, screenshots and verdict.json; prints the verdict.
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bench.ecosystem import board_lab
from bench.ecosystem import lab as base

PAGE_SCRIPT = Path(__file__).with_name("board_check_page.py")
IMAGE = "unbidden-lab-check:1.49.1"
MAX_OCCLUDED = 0.10
FLAG_RULES = ("bound", "legible", "alert_style", "alert_pixels", "visible")


def truth(lab: Path) -> dict[str, dict[str, int]]:
    """{bin: {supply, picks, shortfall}} from the sources, by the harness's own definition."""
    rows = base._docker(  # pyright: ignore[reportPrivateUsage]
        "exec", base.PG, "psql", "-U", "postgres", "-d", board_lab.DB, "-At", "-c",
        "SELECT bin, sum(units) FROM picks WHERE picked_at > now() - interval '7 days' GROUP BY bin",
    ).stdout.splitlines()  # fmt: skip
    picks = {b: int(u) for b, u in (line.split("|") for line in rows if line)}
    out = {}
    for name, b in board_lab.baseline(lab)["bins"].items():
        supply = int(b["quantity"]) - int(b["reserved"]) + int(b["incoming"])
        out[name] = {"supply": supply, "picks": picks.get(name, 0), "shortfall": max(0, picks.get(name, 0) - supply)}
    return out


def _rgb(css: str) -> tuple[float, float, float, float] | None:
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", css or "")
    if not m:
        return None
    return float(m[1]), float(m[2]), float(m[3]), float(m[4]) if m[4] is not None else 1.0


def red(rgb: tuple[float, ...] | list[int] | None) -> bool:
    if rgb is None or (len(rgb) == 4 and rgb[3] < 0.5):
        return False
    h, lightness, s = colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    return (h * 360 <= 20 or h * 360 >= 340) and s >= 0.4 and 0.25 <= lightness <= 0.65


def contrast(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    def lum(c: tuple[float, ...]) -> float:
        ch = [x / 255 for x in c[:3]]
        lin = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def judge_flag(state: dict[str, Any], row: dict[str, Any], seen: list[dict[str, Any]]) -> dict[str, Any]:
    """Each property of the contract, with what was observed."""
    box, rbox = state["box"], row["box"]
    centre = box["y"] + box["h"] / 2
    bg, fg = _rgb(state["background"]), _rgb(state["color"])
    visible = max((s["visible"] for s in seen), default=0.0)
    pixels = next((s["rgb"] for s in sorted(seen, key=lambda s: -s["visible"]) if s.get("rgb")), None)
    out = {
        "bound": rbox["y"] <= centre <= rbox["y"] + rbox["h"],
        "legible": bool(
            bg
            and fg
            and contrast(bg, fg) >= 4.5
            and state["font_px"] >= 11
            and state["opacity"] > 0.5
            and state["visibility"] == "visible"
            and state["display"] != "none"
            and box["w"] >= 8
            and box["h"] >= 8
        ),
        "alert_style": red(bg),
        "alert_pixels": red(pixels),
        "visible": visible >= 1 - MAX_OCCLUDED,
        "visible_share": round(visible, 2),
        "contrast": round(contrast(bg, fg), 2) if bg and fg else None,
        "pixels": pixels,
    }
    out["flagged"] = all(out[k] for k in FLAG_RULES)
    out["red_alert_visible"] = out["alert_style"] and out["alert_pixels"] and out["visible"]
    return out


def judge(page: dict[str, Any], true: dict[str, dict[str, int]]) -> dict[str, Any]:
    by_bin: dict[str, list[dict[str, Any]]] = {}
    for row in page["rows"]:
        for name in true:
            if name in row["cells"]:
                by_bin.setdefault(name, []).append(row)
    bins, problems = {}, []
    for name, t in sorted(true.items()):
        rows = by_bin.get(name, [])
        if len(rows) != 1:
            problems.append(f"{name}: shown {len(rows)} times")
            bins[name] = {"rows": len(rows), "short": t["shortfall"] > 0, "flagged": False, "false_flag": False}
            continue
        row = rows[0]
        numbers = {int(n) for c in row["cells"] for n in re.findall(r"\d+", c)}
        shown_right = t["supply"] in numbers and t["picks"] in numbers
        states = [(s, judge_flag(s, row, page["seen"].get(s["id"], []))) for s in row["states"]]
        short_states = [(s, j) for s, j in states if "SHORT" in s["text"]]
        flagged = any(j["flagged"] for _, j in short_states)
        amount_right = all(int(m) == t["shortfall"] for s, _ in short_states for m in re.findall(r"\d+", s["text"]))
        is_short = t["shortfall"] > 0
        false_flag = not is_short and (bool(short_states) or any(j["red_alert_visible"] for _, j in states))
        bins[name] = {
            "short": is_short, "flagged": flagged, "false_flag": false_flag, "numbers_right": shown_right,
            "amount_right": amount_right, "dom_short": bool(short_states),
            "states": [{"text": s["text"], **j} for s, j in states],
        }  # fmt: skip
        if is_short and not flagged:
            failed = [f"{s['text']!r} " + ", ".join(k for k in FLAG_RULES if not j[k]) for s, j in short_states]
            problems.append(
                f"{name}: short by {t['shortfall']}, not flagged: " + ("; ".join(failed) or "no SHORT state")
            )
        if false_flag:
            problems.append(f"{name}: not short, flagged")
        if not shown_right:
            problems.append(f"{name}: numbers shown {sorted(numbers)}, truth supply {t['supply']} picks {t['picks']}")
        if not amount_right:
            problems.append(f"{name}: shortfall shown differs from {t['shortfall']}")
    return {"bins": bins, "problems": problems}


def ensure_image() -> None:
    from unbidden.lab.ui import PLAYWRIGHT_IMAGE, ensure_image

    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode == 0:
        return
    ensure_image()
    dockerfile = f"FROM {PLAYWRIGHT_IMAGE}\nRUN pip install --no-cache-dir --break-system-packages pillow==11.0.0\n"
    subprocess.run(["docker", "build", "-q", "-t", IMAGE, "-"], input=dockerfile, text=True, check=True,
                   capture_output=True)  # fmt: skip


def capture(out: Path) -> dict[str, Any]:
    ensure_image()
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o777)
    subprocess.run(
        ["docker", "run", "--rm", "--network", f"{board_lab.PROJECT}_default", "--label", base.LABEL,
         "-v", f"{PAGE_SCRIPT}:/check/page.py:ro", "-v", f"{out}:/out", "--user", "1001:1001", "-e", "HOME=/tmp",
         IMAGE, "python", "/check/page.py", "http://board:8000/board", "/out"],
        check=True, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    return json.loads((out / "check.json").read_text())


def information(lines: list[str], bins: set[str]) -> set[str]:
    """What a person reads on the page besides the bins' rows, digits normalised (a count may change)."""
    return {re.sub(r"\d+", "#", line) for line in lines if not any(b in line for b in bins)}


def baseline_page(lab: Path) -> None:
    """The page as the case left it, before the agent: what information it carries."""
    page = capture(lab / "board-baseline-page")
    (lab / "board-baseline-lines.json").write_text(json.dumps(page["lines"]))


def check(lab: Path, out: Path) -> dict[str, Any]:
    before = json.loads((lab / "board-baseline.json").read_text())
    now = board_lab.baseline(lab)
    preserved: dict[str, Any] = {
        "inventory": now["bins"] == before["bins"],
        "history": now["picks"] == before["picks"],
    }
    true = truth(lab)
    page = capture(out)
    shown_before = lab / "board-baseline-lines.json"
    if shown_before.exists():
        lost = information(json.loads(shown_before.read_text()), set(true)) - information(page["lines"], set(true))
        preserved["information"] = not lost
        if lost:
            preserved["lost"] = sorted(lost)
    judged = judge(page, true)
    short = sorted(b for b, t in true.items() if t["shortfall"] > 0)
    verdict = {
        "verified": not judged["problems"] and all(v for k, v in preserved.items() if k != "lost"),
        "short": short,
        "flagged": sorted(b for b, j in judged["bins"].items() if j["flagged"]),
        "false_flags": sorted(b for b, j in judged["bins"].items() if j["false_flag"]),
        "dom_short": sorted(b for b, j in judged["bins"].items() if j.get("dom_short")),
        "preserved": preserved,
        "problems": judged["problems"],
        "bins": judged["bins"],
        "screenshots": {
            s["screenshot"]: hashlib.sha256((out / s["screenshot"]).read_bytes()).hexdigest() for s in page["steps"]
        },
        "app_commit": subprocess.run(
            ["git", "-C", str(board_lab.repo_dir(lab)), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1))
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--dir", default=os.path.expanduser("~/unbidden-lab"))
    args = parser.parse_args()
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="board-check-"))
    verdict = check(Path(args.dir), out)
    print(json.dumps({k: verdict[k] for k in ("verified", "short", "flagged", "false_flags", "preserved",
                                              "problems")}, indent=1))  # fmt: skip
    print(f"records: {out}")


if __name__ == "__main__":
    main()
