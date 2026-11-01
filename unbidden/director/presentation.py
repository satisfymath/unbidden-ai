"""A goal about what a page shows: the data says what must be shown; the page says what a person sees; the code is
where they part. A second investigation pattern beside the reconciliation in `goals.py`, which reads the data.

1. *Expected*: for every key of the goal's data (read by `goals._read`, complete or not at all), the value the goal
   is about and whether it must be flagged, computed by Unbidden from the plan's expression.
2. *Observed*: the page scanned top to bottom in the confined browser (`lab/ui.scan`): rows, their marks with
   computed style and hit-tested visibility, fixed overlays, one screenshot per step. What a model is shown of it is
   the configured perception, each adding to the previous one with everything else equal:
   `dom` the browser's observations as text; `vision` plus the screenshots; `vision_sam` plus SAM's regions for a
   red label, mapped to the rows they fall in (SAM predicts; its regions are observations, not measurements).
3. *Discrepancies*: the model compares, row by row, and names the likely cause (`director.page_check`).
4. *Repair*, within the goal's `max_changes` per day: a model proposes a change of the application's tracked files
   (`lab.page_fix`); Unbidden applies it in a git worktree, refuses one that drops or empties a file, runs the
   application's declared checks offline (`operations.check_steps`), commits, and deploys with the declared steps
   (`operate.deploy`, under the mandate's `deploy`). Then it scans again with the same perception: every key must
   still be on exactly one row, and the discrepancies must be gone; otherwise the previous commit is redeployed.
Unbidden's own verdict is the agent's view, not an acceptance: a deployment is judged by checks that are not the
model's (the application's checks, the rows still there, and whatever independent checker the person runs).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.prompts import load_prompt
from unbidden.contracts.common import utc_now
from unbidden.contracts.guardian import ActionRequest, Goal, Mandate
from unbidden.contracts.llm import Image, LLMRequest, Message, Source, Tier
from unbidden.guardian.policy import PolicyEngine
from unbidden.lab.fixlab import unified_patch
from unbidden.store import Store

PERCEPTIONS = ("dom", "vision", "vision_sam")
TRANSPARENT = ("rgba(0, 0, 0, 0)", "transparent")
SAM_PROMPT = "red label"
MAX_FILE_BYTES = 60_000
CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["discrepancies", "cause"],
    "properties": {
        "discrepancies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "kind", "evidence"],
                "properties": {
                    "key": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["not_flagged", "flagged_wrongly", "wrong_value", "missing_row"],
                    },
                    "evidence": {"type": "string"},
                },
            },
        },
        "cause": {"type": "string"},
        "flag": {
            "type": ["object", "null"],
            "required": ["text_contains", "background"],
            "properties": {"text_contains": {"type": "string"}, "background": {"type": "string"}},
        },
    },
}


def served(brain: Any, purpose: str, started: float) -> dict[str, Any]:
    """Which model answered a call, why, and what it cost (the router's own record)."""
    run = getattr(brain, "served_by", {}).get(purpose)
    return {
        "model": run.model if run else None, "tier": run.tier.value if run else None,
        "route": run.route_reason if run else None, "usd": run.cost.usd_remote if run else None,
        "tokens": [run.usage.prompt_tokens, run.usage.completion_tokens] if run else None,
        "seconds": round(time.monotonic() - started, 2),
    }  # fmt: skip


def expected(rows: list[dict[str, Any]], key: str, values: dict[str, float]) -> dict[str, dict[str, Any]]:
    """{key: {fields, value, flag}} for every key of the data."""
    out = {}
    for row in rows:
        k = str(row.get(key))
        fields = {f: v for f, v in row.items() if f != key and isinstance(v, int | float) and not isinstance(v, bool)}
        value = values.get(k, 0.0)
        out[k] = {"fields": fields, "value": value, "flag": value > 0}
    return out


def colour_name(css: str) -> str:
    """A computed CSS colour in words, as a person would name it ("very light red (pale pink)", "dark green"), so a
    goal stated in colours can be compared with what the page shows. Transparent is said so."""
    import colorsys
    import re

    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", css or "")
    if not m:
        return "unknown"
    if m[4] is not None and float(m[4]) < 0.1:
        return "transparent"
    h, light, sat = colorsys.rgb_to_hls(float(m[1]) / 255, float(m[2]) / 255, float(m[3]) / 255)
    if sat < 0.15 or light > 0.97 or light < 0.06:
        return "white" if light > 0.9 else "black" if light < 0.15 else "light grey" if light > 0.6 else "grey"
    hue = h * 360
    name = next(n for limit, n in HUES if hue < limit)
    shade = "very light " if light > 0.85 else "light " if light > 0.7 else "dark " if light < 0.3 else ""
    pastel = " (pale pink)" if name == "red" and light > 0.8 else ""
    return f"{shade}{name}{pastel}"


HUES = ((15, "red"), (45, "orange"), (70, "yellow"), (165, "green"), (200, "cyan"), (255, "blue"),
        (290, "purple"), (345, "pink"), (361, "red"))  # fmt: skip


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def expected_lines(want: dict[str, dict[str, Any]]) -> str:
    return "\n".join(
        f"- {k}: {', '.join(f'{f}={_num(v)}' for f, v in w['fields'].items())}; value {_num(w['value'])}; "
        f"{'must be flagged' if w['flag'] else 'must not be flagged'}"
        for k, w in sorted(want.items())
    )


def rows_by_key(page: dict[str, Any], keys: set[str]) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    for row in page["rows"]:
        for k in keys:
            if k in row["cells"]:
                found.setdefault(k, []).append(row)
    return found


def observed_lines(page: dict[str, Any], keys: set[str] | None = None) -> str:
    """The browser's observations, compact: one line per row, then the overlays."""
    lines = []
    for row in page["rows"]:
        if keys is not None and not keys & set(row["cells"]):
            continue
        # A mark that only repeats its cell, unstyled and fully visible, says nothing the cells do not.
        telling = [
            m for m in row["marks"]
            if not (m["text"] in row["cells"] and m["background"] in TRANSPARENT and m.get("visible") == 1)
        ]  # fmt: skip
        marks = "; ".join(
            f"{m['text']!r} bg {m['background']} ({colour_name(m['background'])}) fg {m['color']} "
            f"({colour_name(m['color'])}) {m['font_px']:.0f}px"
            f"{'' if m.get('opacity', 1) >= 1 else f' opacity {m["opacity"]}'}"
            f"{'' if m.get('visibility') == 'visible' else ' ' + str(m.get('visibility'))}"
            f" visible {m['visible'] if m['visible'] is not None else 'never in view'}"
            f"{' covered by ' + ', '.join(m['covered_by']) if m.get('covered_by') else ''}"
            for m in telling
        )
        lines.append(f"- row {row['row']} (page y {row['box']['y']:.0f}-{row['box']['y'] + row['box']['h']:.0f}): "
                     f"cells {row['cells']}; marks: {marks}")  # fmt: skip
    for o in page.get("overlays", []):
        box = o["viewport_box"]
        where = f"x {box['x']:.0f} y {box['y']:.0f} w {box['w']:.0f} h {box['h']:.0f}"
        lines.append(
            f"- overlay {o['tag']}.{o['cls']} ({o['position']}, bg {o['background']}) at viewport {where}: "
            f"{o['text'][:60]!r}"
        )
    return "\n".join(lines)


def sam_regions(
    scan: Any, keys: set[str], *, store: Store, mandate: Mandate, key: str
) -> tuple[str, list[dict[str, Any]]]:
    """SAM's regions on every step's screenshot, mapped to the rows they fall in. Returns the text shown to the
    model, and the call records."""
    from unbidden.lab.sam import SamRefused, segment, to_page

    page, records, by_row = scan.page, [], {}
    scale = float(page.get("scale", 1.0))
    for scroll_y, png in scan.screenshots:
        try:
            boxes, record = segment(png, SAM_PROMPT, store=store, mandate=mandate, key=key)
        except SamRefused as exc:
            records.append({"error": str(exc)[:200]})
            continue
        records.append({**record, "regions": len(boxes), "scroll_y": scroll_y})
        for box in boxes:
            region = to_page(box, scale, scroll_y)
            centre = region.y + region.h / 2
            row = next((r for r in page["rows"] if r["box"]["y"] <= centre <= r["box"]["y"] + r["box"]["h"]), None)
            if row is None:
                continue
            k = next((c for c in row["cells"] if c in keys), f"row {row['row']}")
            seen = by_row.setdefault(k, {})
            spot = (round(region.x), round(region.y))
            seen[spot] = max(seen.get(spot, 0.0), region.confidence or 0.0)  # the same region seen on two steps
    lines = [f"- {k}: {len(v)} region(s), confidence {', '.join(f'{c:.2f}' for c in v.values())}"
             for k, v in sorted(by_row.items())]  # fmt: skip
    none = sorted(keys - by_row.keys())
    text = (
        f"\nSAM 3.1 (a segmentation model; its regions are predictions, not measurements) looked for {SAM_PROMPT!r} "
        f"on every screenshot. Regions, by the row they fall in:\n" + ("\n".join(lines) or "- none")
        + f"\nRows with no such region: {', '.join(none) or 'none'}"
    )  # fmt: skip
    return text, records


async def perceive(
    brain: Any, store: Store, mandate: Mandate, goal: Goal, scan: Any, want: dict[str, dict[str, Any]],
    perception: str, *, source: Source,
) -> dict[str, Any]:  # fmt: skip
    """The discrepancies a model finds between the data and the page, under one perception."""
    if perception not in PERCEPTIONS:
        raise ValueError(f"unknown perception {perception!r}")
    keys = set(want)
    extra, images, sam = "", [], []
    how = "text, styles, geometry and hit-testing"
    if perception in ("vision", "vision_sam"):
        images = [Image.of(png) for _, png in scan.screenshots]
        offsets = ", ".join(f"screenshot {i + 1} at scroll {y}px" for i, (y, _) in enumerate(scan.screenshots))
        scale = scan.page.get("scale", 1.0)
        extra = (f"\nThe screenshots of the page are attached in scroll order ({offsets}); a screenshot pixel is "
                 f"{scale} CSS pixel(s), page y = screenshot y / {scale} + scroll.")  # fmt: skip
        how += "; screenshots attached"
    if perception == "vision_sam":
        from unbidden.guardian.credentials import broker

        text, sam = sam_regions(
            scan, keys, store=store, mandate=mandate, key=broker().get("MODEL_API_KEY", "model.remote") or ""
        )
        extra += text
        how += "; SAM regions"
    prompt = load_prompt("page_check")
    content = prompt.render(
        goal=goal.statement, expected=expected_lines(want), how=how, observed=observed_lines(scan.page),
        extra=extra, schema=json.dumps(CHECK_SCHEMA),
    )  # fmt: skip
    started = time.monotonic()
    messages = [Message(role="user", content=content, source=source, images=images)]
    problems: list[str] = []
    answer: dict[str, Any] | None = None
    for _ in range(CHECK_ATTEMPTS):
        response = await brain.complete(
            LLMRequest(
                purpose="director.page_check", tier=Tier.LOCAL, response_schema=CHECK_SCHEMA, max_tokens=3000,
                prompt_sha256=prompt.sha256, correlation_id=goal.id, messages=messages,  # type: ignore[arg-type]
            )
        )  # fmt: skip
        answer, problem = read_answer(response.content, keys)
        if problem is None:
            break
        problems.append(problem)
        answer = None
        messages = [*messages, Message(role="assistant", content=response.content[:4000] or "(nothing)", source=source),
                    Message(role="user", content=f"That answer cannot be used: {problem}. Answer again, JSON only.",
                            source="prompt")]  # fmt: skip
    return {
        "perception": perception,
        # Inconclusive: no usable answer within the attempts. Never "no discrepancies": nothing was concluded.
        "conclusive": answer is not None,
        "discrepancies": answer["discrepancies"] if answer else [],
        "cause": answer.get("cause", "") if answer else "",
        "flag": answer.get("flag") if answer else None,
        "problems": problems,
        "model": served(brain, "director.page_check", started),
        "sam": sam, "screenshots": scan.digests(),
    }  # fmt: skip


CHECK_ATTEMPTS = 2


def read_answer(text: str, keys: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    """The page check's answer, or why it cannot be used: not JSON, not the schema, or naming rows the data does not
    have. Nothing in it is dropped quietly: an answer with one bad entry is not used at all."""
    from jsonschema import Draft202012Validator

    try:
        answer = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"not JSON ({exc.msg})"
    errors = sorted(Draft202012Validator(CHECK_SCHEMA).iter_errors(answer), key=lambda e: list(e.path))
    if errors:
        return None, f"not the schema: {errors[0].message[:160]}"
    unknown = sorted({str(d["key"]) for d in answer["discrepancies"]} - keys)
    if unknown:
        return None, f"names rows the data does not have: {', '.join(unknown[:5])}"
    return answer, None


def app_files(repo: Path) -> dict[str, str]:
    """The application's tracked text files a fix may need, within a size bound; never env files or secrets."""
    listed = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True).stdout
    files, total = {}, 0
    for path in sorted(listed.split()):
        name = Path(path).name
        if name.startswith(".env") or name.endswith((".lock", ".png", ".jpg", ".ico")) or "secret" in name.lower():
            continue
        try:
            text = (repo / path).read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if total + len(text) > MAX_FILE_BYTES:
            break
        files[path], total = text, total + len(text)
    return files


HISTORY_BYTES = 12_000


def recent_history(repo: Path, paths: list[str], commits: int = 5) -> str:
    """What changed lately in the application's files, newest first, bounded: where a regression usually shows."""
    out = subprocess.run(
        ["git", "-C", str(repo), "log", f"-{commits}", "-p", "--format=commit %h %ad %s", "--date=short", "--",
         *paths],
        capture_output=True, text=True, check=False,
    ).stdout  # fmt: skip
    return out[:HISTORY_BYTES] + ("\n[... older changes not shown]" if len(out) > HISTORY_BYTES else "")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Unbidden", "-c", "user.email=unbidden@localhost", *args],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def run_checks(tree: Path, mandate: Mandate) -> dict[str, Any]:
    """The application's declared checks, offline, in its declared image, on a copy of the changed tree."""
    ops = mandate.operations
    if not ops.check_steps or not ops.check_image:
        return {
            "ok": False,
            "ran": False,
            "log": "the mandate declares no checks for the application (operations.check_steps)",
        }
    verdict = PolicyEngine(mandate).evaluate(
        ActionRequest(capability="sandbox.run", purpose="the application's checks")
    )
    if not verdict.allowed:
        return {"ok": False, "ran": False, "log": "; ".join(verdict.reasons)}
    from unbidden.guardian.killswitch import labels

    log = []
    for argv in ops.check_steps:
        out = subprocess.run(
            ["docker", "run", "--rm", *labels(), "--network", "none", "--read-only", "--tmpfs", "/tmp",
             "-e", "PYTHONDONTWRITEBYTECODE=1", "--memory", "1g", "--pids-limit", "256", "--cap-drop", "ALL",
             "-v", f"{tree}:/app:ro", "-w", "/app", ops.check_image, *argv],
            capture_output=True, text=True, check=False, timeout=600,
        )  # fmt: skip
        log.append(f"$ {' '.join(argv)} -> {out.returncode}\n{(out.stdout + out.stderr)[-1500:]}")
        if out.returncode != 0:
            return {"ok": False, "log": "\n".join(log)}
    return {"ok": True, "log": "\n".join(log)}


async def propose(
    brain: Any, goal: Goal, repo: Path, scan: Any, found: dict[str, Any], feedback: str | None
) -> tuple[dict[str, str] | None, str, dict[str, Any]]:
    """A model's change of the application's files, and its stated cause."""
    files = app_files(repo)
    keys = {str(d["key"]) for d in found["discrepancies"]}
    listed = "\n".join(f"- {d['key']}: {d['kind']}: {d['evidence']}" for d in found["discrepancies"])
    if feedback:
        listed += f"\nA previous change was deployed and did not resolve it: {feedback}"
    prompt = load_prompt("page_fix")
    content = prompt.render(
        goal=goal.statement, discrepancies=listed, observed=observed_lines(scan.page, keys),
        files="\n\n".join(f"# file: {p}\n```\n{t}```" for p, t in files.items()),
        history=recent_history(repo, list(files)) or "(no history)",
    )  # fmt: skip
    started = time.monotonic()
    response = await brain.complete(
        LLMRequest(
            purpose="lab.page_fix",
            tier=Tier.LOCAL,
            expect_files=True,
            max_tokens=8000,
            prompt_sha256=prompt.sha256,
            correlation_id=goal.id,
            messages=[Message(role="user", content=content, source="repo")],
        )
    )
    model = served(brain, "lab.page_fix", started)
    cause = response.content.split("# file:", 1)[0].strip()[:400]
    try:
        changed = parse_files(response.content)
    except CodeBlockError:
        return None, cause, model
    # Only the application's own tracked files, and none emptied: anything else is not a fix of this page.
    changed = {p: c for p, c in changed.items() if p in files and c.strip()}
    changed = {p: c for p, c in changed.items() if c != files[p]}
    return (changed or None), cause, model


def conditions(
    want: dict[str, dict[str, Any]], flag: dict[str, Any], page: dict[str, Any], mandate: Mandate
) -> list[Any]:
    """What a change must satisfy, fixed before it is made, each with where it comes from."""
    from unbidden.contracts.acceptance import Condition
    from unbidden.director.acceptance import info_lines

    keys = sorted(want)
    out = [
        Condition(id="checks", kind="checks_pass", source="mandate", what="the application's declared checks pass",
                  spec={"steps": mandate.operations.check_steps}, satisfies="every declared step exits 0"),
        Condition(id="rows", kind="keys_once", source="data", what="every key of the data is on exactly one row",
                  spec={"keys": keys}, satisfies="no key hidden, dropped or duplicated"),
        Condition(id="marks", kind="marks", source="model",
                  what=f"rows the goal flags carry {flag['text_contains']!r} on {flag['background']}; no other does",
                  spec={"text_contains": flag["text_contains"], "background": flag["background"], "min_visible": 0.9,
                        "flag_keys": [k for k in keys if want[k]["flag"]],
                        "plain_keys": [k for k in keys if not want[k]["flag"]]},
                  satisfies="each flagged key's row has such a mark at least 90 % visible; no other row has one"),
    ]  # fmt: skip
    if "lines" in page:
        out.append(Condition(id="information", kind="information_kept", source="project",
                             what="what the page said besides the rows is still said",
                             spec={"lines": sorted(info_lines(page["lines"], set(keys))), "keys": keys},
                             satisfies="every such line still on the page (digits may change)"))  # fmt: skip
    return out


def changes_today(store: Store, goal: Goal, window: str) -> int:
    return sum(1 for d in store.get_value(f"page_changes:{goal.id}", []) if d.startswith(window))


async def pursue_page(
    brain: Any, store: Store, mandate: Mandate, goal: Goal, run: Any, want: dict[str, dict[str, Any]], url: str, *,
    repo: Path, artifacts: Path, perception: str, window: str, source: Source,
) -> None:  # fmt: skip
    """Observe, compare, and within bounds repair and verify. Sets `run.status` and records the evidence."""
    from unbidden.director import acceptance as accept
    from unbidden.lab.ui import scan as scan_page
    from unbidden.operate.deploy import OperationRefused, deploy

    accept.refresh(store, f"page:{goal.id}:", _git(repo, "rev-parse", "HEAD").stdout.strip())
    out = artifacts / "pages" / run.id
    before = scan_page(url, out / "before")
    found = await perceive(brain, store, mandate, goal, before, want, perception, source=source)
    run.evidence = {"url": url, "perception": perception, "before": {"dir": str(out / "before"), **found}}
    if not found["conclusive"]:
        run.status = "page_inconclusive"
        run.notes.append(f"the page check gave no usable answer: {'; '.join(found['problems'])[:300]}")
        return
    shown = rows_by_key(before.page, set(want))
    missing = sorted(k for k in want if len(shown.get(k, [])) != 1)
    if not found["discrepancies"] and not missing:
        run.status, run.notes = "page_ok", [*run.notes, f"the page shows what the data says ({len(want)} keys)"]
        return
    run.findings = found["discrepancies"]
    limit = int(goal.bounds.get("max_changes", 0) or 0)
    if limit <= 0 or changes_today(store, goal, window) >= limit:
        run.status = "page_reported"
        run.notes.append(f"{len(found['discrepancies'])} discrepancies; no change allowed now (max_changes {limit})")
        return
    flag = found.get("flag") or {}
    if not flag.get("text_contains") or not flag.get("background"):
        # How a flagged row must look is neither in the goal nor in the page: a person says, before anything changes.
        run.status = "page_needs_clarification"
        run.notes.append("the goal and the page do not say how a flagged row is marked; nothing changed")
        return
    acc = accept.fix(f"page:{goal.id}:{run.id}", conditions(want, flag, before.page, mandate))
    store.put(accept.COLLECTION, acc)
    run.evidence["acceptance"] = acc.id
    feedback: str | None = None
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    attempts: list[dict[str, Any]] = []
    for attempt in (1, 2):
        files, cause, model = await propose(brain, goal, repo, before, found, feedback)
        record: dict[str, Any] = {"attempt": attempt, "cause": cause, "model": model}
        attempts.append(record)
        run.evidence["attempts"] = attempts
        if files is None:
            record["result"] = "no usable change proposed"
            feedback = "your answer changed no file of the application"
            continue
        tree = artifacts / "worktrees" / f"{run.id}-{attempt}"
        branch = f"unbidden/{goal.id}-{run.id[-8:]}-{attempt}"
        added = _git(repo, "worktree", "add", "-b", branch, str(tree), "HEAD")
        if added.returncode != 0:
            record["result"] = f"worktree: {added.stderr.strip()[:200]}"
            break
        try:
            for path, content in files.items():
                (tree / path).write_text(content)
            record["patch"] = unified_patch(repo, files)
            record["patch_sha256"] = hashlib.sha256(record["patch"].encode()).hexdigest()
            checks = run_checks(tree, mandate)
            record["checks"] = checks
            if not checks["ok"]:
                record["result"] = "the application's checks failed"
                feedback = f"the application's checks failed: {checks['log'][-600:]}"
                continue
            _git(tree, "add", "-A")
            committed = _git(tree, "commit", "-qm", f"unbidden: {goal.id}: {cause[:120] or 'page fix'}")
            if committed.returncode != 0:
                record["result"] = f"commit: {committed.stderr.strip()[:200]}"
                break
            commit = _git(tree, "rev-parse", "HEAD").stdout.strip()
            record["commit"] = commit
        finally:
            _git(repo, "worktree", "remove", "--force", str(tree))
        try:
            deployed = deploy(repo, store, mandate, commit, reason=f"goal {goal.id}: {cause[:120]}")
        except OperationRefused as exc:
            record["result"] = f"not deployed: {exc}"
            run.status = "blocked"
            run.notes.append(f"a change was ready and not deployed: {exc}")
            return
        record["deploy"] = {"ok": deployed.ok, "log": deployed.log[-1500:]}
        store.set_value(f"page_changes:{goal.id}", [*store.get_value(f"page_changes:{goal.id}", []),
                                                    utc_now().isoformat()])  # fmt: skip
        if not deployed.ok:
            record["result"] = "the deploy failed"
            deploy(repo, store, mandate, base, reason=f"goal {goal.id}: undo a failed deploy", rollback=True)
            break
        after = scan_page(url, out / f"after-{attempt}")
        again = await perceive(brain, store, mandate, goal, after, want, perception, source=source)
        record["after"] = {"dir": str(out / f"after-{attempt}"), **again}
        claim = "unusable" if not again["conclusive"] else "unresolved" if again["discrepancies"] else "resolved"
        acc.change = {"commit": commit, "patch_sha256": record["patch_sha256"], "attempt": attempt}
        accept.judge(acc, {"checks": checks, "page": after.page}, commit, claim)
        store.put(accept.COLLECTION, acc)
        record["acceptance"] = {"state": acc.state, "why": acc.why, "model_claim": claim,
                                "outcomes": [o.model_dump(mode="json") for o in acc.outcomes]}  # fmt: skip
        if acc.state == "accepted":
            record["result"] = "accepted: every fixed condition holds on what is deployed"
            run.status = "page_fixed"
            run.notes.append(
                f"{len(found['discrepancies'])} discrepancies fixed by {commit[:12]}, accepted: {cause[:160]}"
            )
            return
        # Rejected or inconclusive: what cannot be accepted is not left deployed.
        record["result"] = f"{acc.state}: {acc.why}; the previous commit is redeployed"
        deploy(repo, store, mandate, base, reason=f"goal {goal.id}: a change was {acc.state}", rollback=True)
        if acc.state == "inconclusive":
            run.status = "page_inconclusive"
            run.notes.append(record["result"])
            return
        failed = [o for o in acc.outcomes if o.status == "failed"]
        feedback = "; ".join(f"{o.condition}: {json.dumps(o.observation)[:200]}" for o in failed)[:800]
        if changes_today(store, goal, window) >= limit:
            break
    run.status = "page_unresolved"
    run.notes.append(f"discrepancies remain after {len(attempts)} attempt(s)")
